from django.db.models import Prefetch, Q
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsAdminRole, IsWorkerRole

from . import assignment_service
from .models import Area, BookingAssignment, WorkerWorkingArea

from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError
from .serializers import WorkerMyScheduleSerializer 
from apps.bookings.models import BookingSchedule

from .serializers import (
    AdminAssignWorkerSerializer,
    AreaSummarySerializer,
    CancelAssignmentSerializer,
    WorkerScheduleSerializer,
    WorkerWorkingAreaSerializer,
    WorkerWorkingAreaBulkUpdateSerializer,
    ScheduleImageUploadSerializer
)

from .schemas import (
    WORKER_ACTIVE_AREA_SCHEMA,
    WORKER_WORKING_AREA_SCHEMA,
    WORKER_AVAILABLE_SCHEDULE_SCHEMA,
    WORKER_MY_SCHEDULE_SCHEMA,
    WORKER_CLAIM_SCHEDULE_SCHEMA,
    WORKER_CANCEL_ASSIGNMENT_SCHEMA,
    ADMIN_ASSIGN_WORKER_SCHEMA,
)

from rest_framework.parsers import FormParser, MultiPartParser

from . import checkin_service

# select_related dùng chung: customer_avatar/customer_name/payment_status/
# service_data/form_schema đều đọc qua booking__customer và booking__service,
# nếu không select_related trước sẽ bị N+1 query (1 query/booking) khi
# serializer truy cập instance.booking.customer, instance.booking.service.
def _base_select_related(queryset):
    return queryset.select_related(
        'booking', 'booking__customer', 'booking__service', 'booking__address',
    )


def _prefetch_assignments(queryset, *, with_images=False):
    queryset = _base_select_related(queryset).prefetch_related(
        Prefetch('assignments', queryset=BookingAssignment.objects.filter(status=BookingAssignment.Status.ACCEPTED)),
    )
    if with_images:
        # Ảnh trước/sau chỉ cần ở my-schedules (WorkerMyScheduleSerializer),
        # không cần ở available nên tách riêng bằng cờ with_images.
        queryset = queryset.prefetch_related('images')
    return queryset


def _parse_date_param(request, name):
    raw = request.query_params.get(name)
    if not raw:
        return None
    parsed = parse_date(raw)
    if parsed is None:
        raise ValidationError({name: 'Định dạng ngày phải là YYYY-MM-DD.'})
    return parsed


@WORKER_ACTIVE_AREA_SCHEMA
class WorkerActiveAreaListView(generics.ListAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = AreaSummarySerializer

    def get_queryset(self):
        queryset = Area.objects.filter(is_active=True)
        city = self.request.query_params.get('city')
        search = self.request.query_params.get('search')
        if city:
            queryset = queryset.filter(city__iexact=city.strip())
        if search:
            queryset = queryset.filter(Q(name__icontains=search.strip()) | Q(city__icontains=search.strip()))
        return queryset


@WORKER_WORKING_AREA_SCHEMA
class WorkerWorkingAreaView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]

    def get_queryset(self):
        return (
            WorkerWorkingArea.objects.filter(worker=self.request.user)
            .select_related('area')
            .order_by('area__city', 'area__name')
        )

    def get(self, request, *args, **kwargs):
        serializer = WorkerWorkingAreaSerializer(self.get_queryset(), many=True)
        return Response({'message': 'Lấy danh sách khu vực làm việc thành công.', 'data': serializer.data})

    def put(self, request, *args, **kwargs):
        serializer = WorkerWorkingAreaBulkUpdateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        queryset = serializer.save()
        return Response({
            'message': 'Cập nhật khu vực làm việc thành công.',
            'data': WorkerWorkingAreaSerializer(queryset, many=True).data,
        })


@WORKER_AVAILABLE_SCHEDULE_SCHEMA
class WorkerAvailableScheduleListView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerScheduleSerializer

    def get(self, request, *args, **kwargs):
        booking_id = request.query_params.get('booking_id')
        if booking_id and not booking_id.isdigit():
            raise ValidationError({'booking_id': 'booking_id phải là số nguyên.'})
        queryset = _prefetch_assignments(assignment_service.list_available_schedules_for_worker(
            request.user,
            booking_id=int(booking_id) if booking_id else None,
            date_from=_parse_date_param(request, 'date_from'),
            date_to=_parse_date_param(request, 'date_to'),
        ))
        return Response({
            'message': 'Lấy danh sách buổi làm việc khả dụng thành công.',
            'data': self.get_serializer(queryset, many=True).data,
        })

@WORKER_MY_SCHEDULE_SCHEMA
class WorkerMyScheduleListView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerMyScheduleSerializer

    def get(self, request, *args, **kwargs):
        schedule_status = request.query_params.get('status')
        if schedule_status:
            schedule_status = schedule_status.upper()
            if schedule_status not in BookingSchedule.Status.values:
                raise ValidationError({'status': 'Trạng thái buổi làm không hợp lệ.'})
        queryset = _prefetch_assignments(
            assignment_service.list_my_schedules(request.user, schedule_status=schedule_status),
            with_images=True,
        )
        return Response({
            'message': 'Lấy danh sách buổi làm việc của tôi thành công.',
            'data': self.get_serializer(queryset, many=True).data,
        })


class WorkerClaimScheduleView(APIView):
    permission_classes = [IsWorkerRole]

    def post(self, request, *args, **kwargs):
        assignment = assignment_service.claim_schedule(schedule_id=kwargs['schedule_id'], worker=request.user)
        return Response({
            'message': 'Nhận việc thành công.',
            'data': {
                'assignment_id': assignment.id,
                'schedule_id': assignment.schedule_id,
                'status': assignment.status,
            },
        }, status=201)


@WORKER_CANCEL_ASSIGNMENT_SCHEMA
class WorkerCancelAssignmentView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = CancelAssignmentSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = assignment_service.cancel_assignment(
            assignment_id=kwargs['assignment_id'], worker=request.user,
            reason=serializer.validated_data['reason'],
        )
        return Response({
            'message': 'Hủy nhận việc thành công.',
            'data': {
                'assignment_id': assignment.id,
                'schedule_id': assignment.schedule_id,
                'status': assignment.status,
            },
        })


@ADMIN_ASSIGN_WORKER_SCHEMA
class AdminAssignWorkerView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminAssignWorkerSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = assignment_service.admin_assign_worker(
            schedule_id=kwargs['schedule_id'],
            worker_id=serializer.validated_data['worker_id'],
            admin_user=request.user,
            note=serializer.validated_data.get('note'),
        )
        return Response({'message': 'Gán nhân viên thành công.', 'data': {'assignment_id': assignment.id}}, status=201)



class WorkerCheckInView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]

    def post(self, request, *args, **kwargs):
        schedule = checkin_service.check_in(
            schedule_id=kwargs['schedule_id'],
            worker=request.user,
        )
        return Response({
            'message': 'Check-in thành công.',
            'data': WorkerMyScheduleSerializer(schedule).data,
        })


class WorkerCheckOutView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]

    def post(self, request, *args, **kwargs):
        schedule = checkin_service.check_out(
            schedule_id=kwargs['schedule_id'],
            worker=request.user,
        )
        return Response({
            'message': 'Check-out thành công.',
            'data': WorkerMyScheduleSerializer(schedule).data,
        })


class WorkerScheduleImageUploadView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = ScheduleImageUploadSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        image = checkin_service.upload_schedule_image(
            schedule_id=kwargs['schedule_id'],
            worker=request.user,
            file=serializer.validated_data['image'],
            image_type=serializer.validated_data['image_type'],
            note=serializer.validated_data.get('note'),
        )
        return Response({
            'message': 'Tải ảnh thành công.',
            'data': BookingScheduleImageSerializer(image).data,
        })