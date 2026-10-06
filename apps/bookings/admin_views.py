from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Exists, F, Min, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.complaints.models import Complaint
from apps.common.distributed_lock import distributed_lock
from apps.common.idempotency import idempotent
from apps.common.permissions import IsAdminRole
from apps.worker import assignment_service
from apps.worker.models import BookingAssignment

from .admin_serializers import (
    AdminAssignWorkerSerializer,
    AdminAvailableWorkerSerializer,
    AdminBookingCreateSerializer,
    AdminBookingDetailSerializer,
    AdminBookingListSerializer,
    AdminBookingUpdateSerializer,
    AdminBulkAssignSerializer,
    AdminCustomerSearchSerializer,
    AdminUserSummarySerializer,
    AdminCompleteScheduleSerializer,
    AdminReasonSerializer,
    AdminScheduleSerializer,
    AdminScheduleUpdateSerializer,
    BookingActivitySerializer,
)
from .admin_services import (
    cancel_booking_by_admin,
    complete_schedule_by_admin,
    unassign_worker_by_admin,
    update_booking_by_admin,
    update_schedule_by_admin,
)
from .models import Booking, BookingActivity, BookingSchedule

User = get_user_model()


class AdminBookingPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _page_response(*, paginator, data, message):
    return Response({
        'message': message,
        'data': {
            'results': data,
            'count': paginator.page.paginator.count,
            'page': paginator.page.number,
            'total_pages': paginator.page.paginator.num_pages,
            'has_next': paginator.page.has_next(),
            'has_previous': paginator.page.has_previous(),
            'page_size': paginator.get_page_size(paginator.request),
        },
    })


def _assignment_queryset():
    return BookingAssignment.objects.select_related(
        'worker', 'worker__worker_profile', 'worker__worker_profile__registered_service',
        'assigned_by',
    ).order_by('-assigned_at', '-id')


def _booking_detail_queryset():
    return (
        Booking.objects.select_related(
            'customer', 'service', 'address', 'delivery_address',
            'user_voucher', 'user_voucher__voucher', 'cancelled_by',
        )
        .prefetch_related(
            Prefetch(
                'schedules',
                queryset=BookingSchedule.objects.prefetch_related(
                    Prefetch('assignments', queryset=_assignment_queryset(), to_attr='admin_assignments'),
                    'images',
                ).order_by('scheduled_start', 'id'),
            ),
            'payments',
            Prefetch('complaints', queryset=Complaint.objects.select_related('issue_type')),
        )
    )


class AdminBookingListCreateView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    pagination_class = AdminBookingPagination

    def get_serializer_class(self):
        return AdminBookingCreateSerializer if self.request.method == 'POST' else AdminBookingListSerializer

    def get_queryset(self):
        accepted = BookingAssignment.Status.ACCEPTED
        queryset = (
            Booking.objects.select_related('customer', 'service')
            .annotate(
                total_schedules=Count(
                    'schedules',
                    filter=~Q(schedules__status=BookingSchedule.Status.CANCELLED),
                    distinct=True,
                ),
                assigned_schedules=Count(
                    'schedules',
                    filter=Q(schedules__assignments__status=accepted)
                    & ~Q(schedules__status=BookingSchedule.Status.CANCELLED),
                    distinct=True,
                ),
                completed_schedules=Count(
                    'schedules',
                    filter=Q(schedules__status=BookingSchedule.Status.COMPLETED),
                    distinct=True,
                ),
                next_schedule_start=Min(
                    'schedules__scheduled_start',
                    filter=Q(schedules__status__in=[
                        BookingSchedule.Status.PENDING,
                        BookingSchedule.Status.IN_PROGRESS,
                    ]),
                ),
            )
            .prefetch_related(
                Prefetch(
                    'schedules__assignments',
                    queryset=_assignment_queryset().filter(status=accepted),
                    to_attr='accepted_admin_assignments',
                ),
            )
        )

        params = self.request.query_params
        search = params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(booking_code__icontains=search)
                | Q(customer__username__icontains=search)
                | Q(customer__first_name__icontains=search)
                | Q(customer__last_name__icontains=search)
                | Q(customer__phone_number__icontains=search)
            )

        for field, values in (
            ('status', Booking.Status.values),
            ('payment_status', Booking.PaymentStatus.values),
        ):
            value = params.get(field)
            if value:
                value = value.upper()
                if value not in values:
                    raise ValidationError({field: 'Giá trị không hợp lệ.'})
                queryset = queryset.filter(**{field: value})

        if params.get('service_id'):
            queryset = queryset.filter(service_id=params['service_id'])
        if params.get('worker_id'):
            queryset = queryset.filter(
                schedules__assignments__worker_id=params['worker_id'],
                schedules__assignments__status=accepted,
            )
        if params.get('unassigned', '').lower() in ('true', '1'):
            accepted_assignment = BookingAssignment.objects.filter(
                schedule_id=OuterRef('pk'), status=accepted,
            )
            assignable_schedules = BookingSchedule.objects.filter(
                booking_id=OuterRef('pk'),
                status=BookingSchedule.Status.PENDING,
                scheduled_start__gt=timezone.now(),
            ).filter(~Exists(accepted_assignment))
            queryset = queryset.exclude(status=Booking.Status.FAILED).filter(
                Exists(assignable_schedules),
            )
        elif params.get('unassigned', '').lower() in ('false', '0'):
            queryset = queryset.filter(assigned_schedules__gte=F('total_schedules'))

        date_filters = {
            'created_from': 'created_at__date__gte',
            'created_to': 'created_at__date__lte',
            'scheduled_from': 'schedules__scheduled_start__date__gte',
            'scheduled_to': 'schedules__scheduled_start__date__lte',
        }
        for param, lookup in date_filters.items():
            raw = params.get(param)
            if raw:
                if not parse_date(raw):
                    raise ValidationError({param: 'Ngày phải có định dạng YYYY-MM-DD.'})
                queryset = queryset.filter(**{lookup: raw})

        sort_fields = {
            'created_at': ('created_at',),
            'updated_at': ('updated_at',),
            'total_amount': ('total_amount',),
            'next_schedule_start': ('next_schedule_start',),
            'status': ('status',),
            'customer': ('customer__first_name', 'customer__last_name', 'customer__username'),
            'service': ('service__name',),
        }
        ordering = params.get('ordering', '-created_at')
        descending = ordering.startswith('-')
        columns = sort_fields.get(ordering.removeprefix('-'))
        if not columns:
            raise ValidationError({'ordering': 'Kiểu sắp xếp không hợp lệ.'})
        # Đơn không có buổi sắp tới (next_schedule_start = NULL) luôn nằm cuối.
        expressions = [
            F(column).desc(nulls_last=True) if descending else F(column).asc(nulls_last=True)
            for column in columns
        ]
        return queryset.order_by(*expressions, '-id').distinct()

    def get(self, request):
        paginator = self.pagination_class()
        paginator.request = request
        page = paginator.paginate_queryset(self.get_queryset(), request, view=self)
        data = AdminBookingListSerializer(page, many=True).data
        return _page_response(paginator=paginator, data=data, message='Lấy danh sách đơn thành công.')

    @idempotent
    @transaction.atomic
    def post(self, request):
        serializer = AdminBookingCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()
        booking = _booking_detail_queryset().get(pk=booking.pk)
        return Response(
            {'message': 'Tạo đơn thay khách hàng thành công.', 'data': AdminBookingDetailSerializer(booking).data},
            status=status.HTTP_201_CREATED,
        )


class AdminBookingDetailView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminBookingDetailSerializer

    def get(self, request, pk):
        booking = get_object_or_404(_booking_detail_queryset(), pk=pk)
        return Response({'message': 'Lấy chi tiết đơn thành công.', 'data': AdminBookingDetailSerializer(booking).data})

    @transaction.atomic
    def patch(self, request, pk):
        serializer = AdminBookingUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        update_booking_by_admin(
            booking_id=pk,
            actor=request.user,
            validated_data=serializer.validated_data,
        )
        booking = _booking_detail_queryset().get(pk=pk)
        return Response({'message': 'Cập nhật đơn thành công.', 'data': AdminBookingDetailSerializer(booking).data})


class AdminBookingCancelView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminReasonSerializer

    @idempotent
    def post(self, request, pk):
        serializer = AdminReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with distributed_lock(f'booking:{pk}'):
            cancel_booking_by_admin(
                booking_id=pk,
                actor=request.user,
                reason=serializer.validated_data['reason'],
            )
        booking = _booking_detail_queryset().get(pk=pk)
        return Response({'message': 'Hủy đơn thành công.', 'data': AdminBookingDetailSerializer(booking).data})


class AdminBookingTimelineView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    pagination_class = AdminBookingPagination
    serializer_class = BookingActivitySerializer

    def get(self, request, pk):
        get_object_or_404(Booking, pk=pk)
        queryset = BookingActivity.objects.filter(booking_id=pk).select_related('actor')
        event_type = request.query_params.get('event_type')
        schedule_id = request.query_params.get('schedule_id')
        if event_type:
            if event_type not in BookingActivity.EventType.values:
                raise ValidationError({'event_type': 'Loại sự kiện không hợp lệ.'})
            queryset = queryset.filter(event_type=event_type)
        if schedule_id:
            queryset = queryset.filter(schedule_id=schedule_id)
        paginator = self.pagination_class()
        paginator.request = request
        page = paginator.paginate_queryset(queryset, request, view=self)
        return _page_response(
            paginator=paginator,
            data=BookingActivitySerializer(page, many=True).data,
            message='Lấy lịch sử đơn thành công.',
        )


class AdminBookingSummaryView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminBookingListSerializer

    def get(self, request):
        from django.utils import timezone

        today = timezone.localdate()
        data = {
            'today_total': Booking.objects.filter(created_at__date=today).count(),
            'pending': Booking.objects.filter(status=Booking.Status.PENDING).count(),
            'unassigned_schedules': BookingSchedule.objects.filter(
                status=BookingSchedule.Status.PENDING,
            ).exclude(assignments__status=BookingAssignment.Status.ACCEPTED).count(),
            'in_progress': Booking.objects.filter(status=Booking.Status.IN_PROGRESS).count(),
            'completed_today': Booking.objects.filter(
                status=Booking.Status.COMPLETED,
                updated_at__date=today,
            ).count(),
            'failed': Booking.objects.filter(status=Booking.Status.FAILED).count(),
        }
        return Response({'message': 'Lấy thống kê đơn thành công.', 'data': data})


class AdminScheduleUpdateView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminScheduleUpdateSerializer

    @transaction.atomic
    def patch(self, request, pk):
        serializer = AdminScheduleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = update_schedule_by_admin(
            schedule_id=pk,
            actor=request.user,
            validated_data=serializer.validated_data,
        )
        schedule = BookingSchedule.objects.prefetch_related(
            Prefetch('assignments', queryset=_assignment_queryset(), to_attr='admin_assignments'),
            'images',
        ).get(pk=schedule.pk)
        return Response({'message': 'Cập nhật buổi thành công.', 'data': AdminScheduleSerializer(schedule).data})


class AdminAvailableWorkerListView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    pagination_class = AdminBookingPagination
    serializer_class = AdminAvailableWorkerSerializer

    def get(self, request, pk):
        workers = assignment_service.list_available_workers_for_schedule(
            schedule_id=pk,
            search=request.query_params.get('search'),
        )
        ordering = request.query_params.get('ordering', 'rating')
        if ordering == 'rating':
            workers.sort(key=lambda w: (w.worker_profile.average_rating, -w.active_jobs_count), reverse=True)
        elif ordering == 'workload':
            workers.sort(key=lambda w: (w.active_jobs_count, -float(w.worker_profile.average_rating)))
        else:
            raise ValidationError({'ordering': 'Chỉ hỗ trợ rating hoặc workload.'})
        paginator = self.pagination_class()
        paginator.request = request
        page = paginator.paginate_queryset(workers, request, view=self)
        return _page_response(
            paginator=paginator,
            data=AdminAvailableWorkerSerializer(page, many=True).data,
            message='Lấy danh sách nhân viên phù hợp thành công.',
        )


class AdminScheduleAssignView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminAssignWorkerSerializer

    @idempotent
    def post(self, request, pk):
        serializer = AdminAssignWorkerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with distributed_lock(f'schedule:{pk}'):
            assignment = assignment_service.admin_assign_worker(
                schedule_id=pk,
                worker_id=serializer.validated_data['worker_id'],
                admin_user=request.user,
                note=serializer.validated_data.get('note') or serializer.validated_data.get('reason'),
            )
        assignment = _assignment_queryset().get(pk=assignment.pk)
        from .admin_serializers import AdminAssignmentSerializer
        return Response(
            {'message': 'Gán nhân viên thành công.', 'data': AdminAssignmentSerializer(assignment).data},
            status=status.HTTP_201_CREATED,
        )


class AdminScheduleUnassignView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminReasonSerializer

    @idempotent
    def post(self, request, pk):
        serializer = AdminReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with distributed_lock(f'schedule:{pk}'):
            assignment = unassign_worker_by_admin(
                schedule_id=pk,
                actor=request.user,
                reason=serializer.validated_data['reason'],
            )
        from .admin_serializers import AdminAssignmentSerializer
        return Response({'message': 'Bỏ phân công thành công.', 'data': AdminAssignmentSerializer(assignment).data})


class AdminScheduleCompleteView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminCompleteScheduleSerializer

    @idempotent
    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with distributed_lock(f'schedule:{pk}'):
            schedule = complete_schedule_by_admin(
                schedule_id=pk,
                actor=request.user,
                reason=serializer.validated_data['reason'],
                completion_note=serializer.validated_data.get('completion_note'),
            )
        schedule = BookingSchedule.objects.prefetch_related(
            Prefetch('assignments', queryset=_assignment_queryset(), to_attr='admin_assignments'),
            'images',
        ).get(pk=schedule.pk)
        return Response(
            {'message': 'Xác nhận hoàn thành buổi thành công.', 'data': AdminScheduleSerializer(schedule).data}
        )


class AdminBulkAssignView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminBulkAssignSerializer

    @idempotent
    def post(self, request):
        serializer = AdminBulkAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        schedule_ids = payload['schedule_ids']
        found = set(
            BookingSchedule.objects.filter(
                booking_id=payload['booking_id'], id__in=schedule_ids,
            ).values_list('id', flat=True)
        )
        if found != set(schedule_ids):
            raise ValidationError({'schedule_ids': 'Có buổi không thuộc đơn đã chọn hoặc không tồn tại.'})

        assigned = []
        skipped = []
        for schedule_id in schedule_ids:
            try:
                with distributed_lock(f'schedule:{schedule_id}'):
                    assignment = assignment_service.admin_assign_worker(
                        schedule_id=schedule_id,
                        worker_id=payload['worker_id'],
                        admin_user=request.user,
                        note=payload.get('note') or payload.get('reason'),
                    )
                assigned.append({'schedule_id': schedule_id, 'assignment_id': assignment.id})
            except ValidationError as exc:
                skipped.append({
                    'schedule_id': schedule_id,
                    'code': 'NOT_ASSIGNABLE',
                    'reason': exc.detail,
                })
        return Response(
            {
                'message': f'Đã gán {len(assigned)} buổi, bỏ qua {len(skipped)} buổi.',
                'data': {'assigned': assigned, 'skipped': skipped},
            },
            status=status.HTTP_201_CREATED if assigned else status.HTTP_400_BAD_REQUEST,
        )


class AdminWorkerSearchView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    pagination_class = AdminBookingPagination
    serializer_class = AdminUserSummarySerializer

    def get(self, request):
        queryset = User.objects.filter(
            role=User.Role.WORKER, is_active=True, worker_profile__status='ACTIVE',
        )
        search = request.query_params.get('search', '').strip()
        # Match every word, including names split across first_name/last_name.
        for word in search.split():
            matches = (
                Q(first_name__icontains=word) | Q(last_name__icontains=word)
                | Q(username__icontains=word) | Q(phone_number__icontains=word)
            )
            if word.isdecimal() and len(word) <= 18:
                matches |= Q(pk=int(word))
            queryset = queryset.filter(matches)
        paginator = self.pagination_class()
        paginator.request = request
        page = paginator.paginate_queryset(
            queryset.order_by('first_name', 'last_name', 'id'), request, view=self,
        )
        return _page_response(
            paginator=paginator,
            data=self.get_serializer(page, many=True).data,
            message='Tìm nhân viên thành công.',
        )


class AdminCustomerSearchView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    pagination_class = AdminBookingPagination
    serializer_class = AdminCustomerSearchSerializer

    def get(self, request):
        search = request.query_params.get('search', '').strip()
        queryset = User.objects.filter(role='CUSTOMER', is_active=True).prefetch_related('addresses')
        if search:
            queryset = queryset.filter(
                Q(username__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone_number__icontains=search)
            )
        paginator = self.pagination_class()
        paginator.request = request
        page = paginator.paginate_queryset(queryset.order_by('-created_at'), request, view=self)
        return _page_response(
            paginator=paginator,
            data=AdminCustomerSearchSerializer(page, many=True).data,
            message='Tìm khách hàng thành công.',
        )
