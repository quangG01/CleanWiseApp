from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.common.permissions import IsCustomerRole
from apps.worker.assignment_service import expire_unclaimed_schedules
from apps.worker.models import BookingAssignment

from .schemas import (
    BOOKING_CUSTOMER_SCHEMA,
    BOOKING_DETAIL_CUSTOMER_SCHEMA,
)
from .models import Booking
from .serializers import (
    BookingCreateSerializer,
    BookingDetailSerializer,
    BookingListSerializer,
)


class BookingPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


@BOOKING_CUSTOMER_SCHEMA
class BookingListCreateView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    pagination_class = BookingPagination

    def get_queryset(self):
        expire_unclaimed_schedules()

        queryset = (
            Booking.objects
            .filter(
                customer=self.request.user,
            )
            .select_related('service')
            .order_by('-created_at')
        )

        status_param = self.request.query_params.get('status')

        if status_param:
            status_param = status_param.upper()

            if status_param not in Booking.Status.values:
                raise ValidationError({
                    'status': 'Trạng thái đơn hàng không hợp lệ.',
                })

            queryset = queryset.filter(
                status=status_param,
            )

        return queryset

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return BookingCreateSerializer

        return BookingListSerializer

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        paginator = self.pagination_class()

        page = paginator.paginate_queryset(
            queryset,
            request,
            view=self,
        )

        serialized = BookingListSerializer(
            page,
            many=True,
        ).data

        return Response({
            'message': 'Lấy danh sách đơn hàng thành công.',
            'data': {
                'results': serialized,
                'count': paginator.page.paginator.count,
                'page': paginator.page.number,
                'total_pages': paginator.page.paginator.num_pages,
                'has_next': paginator.page.has_next(),
                'has_previous': paginator.page.has_previous(),
                'page_size': paginator.get_page_size(request),
            },
        })

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        booking = serializer.save()

        return Response(
            {
                'message': 'Đặt dịch vụ thành công.',
                'data': BookingDetailSerializer(
                    booking,
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )


@BOOKING_DETAIL_CUSTOMER_SCHEMA
class BookingDetailView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = BookingDetailSerializer

    def get_object(self):
        expire_unclaimed_schedules()

        accepted_assignments = (
            BookingAssignment.objects
            .filter(
                status=BookingAssignment.Status.ACCEPTED,
            )
            .select_related(
                'worker',
                'worker__worker_profile',
            )
        )

        return get_object_or_404(
            Booking.objects
            .filter(
                pk=self.kwargs['pk'],
                customer=self.request.user,
            )
            .select_related('service')
            .prefetch_related(
                Prefetch(
                    'schedules__assignments',
                    queryset=accepted_assignments,
                ),
            ),
        )

    def get(self, request, *args, **kwargs):
        booking = self.get_object()

        serializer = self.get_serializer(
            booking,
        )

        return Response({
            'message': 'Lấy chi tiết đơn hàng thành công.',
            'data': serializer.data,
        })