from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.common.permissions import IsAdminRole, IsCustomerRole, IsWorkerRole
from .address_service import set_default_address, soft_delete_address
from .models import Area, CustomerAddress, UserVoucher, Voucher, WorkerWorkingArea
from .schemas import (
    ADMIN_VOUCHER_BY_CODE_SCHEMA,
    ADMIN_VOUCHER_DETAIL_SCHEMA,
    ADMIN_VOUCHER_LIST_CREATE_SCHEMA,
    BOOKING_CUSTOMER_SCHEMA,
    BOOKING_DETAIL_CUSTOMER_SCHEMA,
    BOOKING_ADMIN_SCHEMA,
    CUSTOMER_CODE_VOUCHER_CLAIM_SCHEMA,
    CUSTOMER_VOUCHER_WALLET_LIST_SCHEMA,
    WORKER_ACTIVE_AREA_LIST_SCHEMA,
    WORKER_WORKING_AREA_DETAIL_SCHEMA,
    WORKER_WORKING_AREA_LIST_CREATE_SCHEMA,
)
from .serializers import (
    CustomerAddressSerializer,
    UserVoucherSerializer,
    VoucherAdminSerializer,
    VoucherAdminWriteSerializer,
    VoucherCodeClaimSerializer,
    VoucherPublicSerializer,
    VoucherValidationSerializer,
    AreaSummarySerializer,
    WorkerWorkingAreaSerializer,
)
from .voucher_service import (
    claim_voucher_by_code,
    validate_and_calculate_voucher,
)

from .models import Booking
from .serializers import (
    BookingCreateSerializer,
    BookingDetailSerializer,
    BookingListSerializer,
)

from .worker_serializers import AdminAssignWorkerSerializer
from rest_framework.pagination import PageNumberPagination


@WORKER_ACTIVE_AREA_LIST_SCHEMA
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
            queryset = queryset.filter(
                Q(name__icontains=search.strip()) | Q(city__icontains=search.strip())
            )
        return queryset


@WORKER_WORKING_AREA_LIST_CREATE_SCHEMA
class WorkerWorkingAreaListCreateView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerWorkingAreaSerializer

    def get_queryset(self):
        return (
            WorkerWorkingArea.objects
            .filter(worker=self.request.user)
            .select_related('area')
            .order_by('area__city', 'area__name')
        )

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách khu vực làm việc thành công.',
            'data': self.get_serializer(self.get_queryset(), many=True).data,
        })

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        working_area = serializer.save()
        return Response({
            'message': 'Thêm khu vực làm việc thành công.',
            'data': self.get_serializer(working_area).data,
        }, status=status.HTTP_201_CREATED)


@WORKER_WORKING_AREA_DETAIL_SCHEMA
class WorkerWorkingAreaDetailView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerWorkingAreaSerializer

    def get_object(self):
        return get_object_or_404(
            WorkerWorkingArea.objects.select_related('area'),
            pk=self.kwargs['pk'],
            worker=self.request.user,
        )

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy chi tiết khu vực làm việc thành công.',
            'data': self.get_serializer(self.get_object()).data,
        })

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            self.get_object(),
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        working_area = serializer.save()
        return Response({
            'message': 'Cập nhật khu vực làm việc thành công.',
            'data': self.get_serializer(working_area).data,
        })

    def delete(self, request, *args, **kwargs):
        self.get_object().delete()
        return Response({'message': 'Xóa khu vực làm việc thành công.'})


class CustomerAddressListCreateView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = CustomerAddressSerializer

    def get_queryset(self):
        return CustomerAddress.objects.filter(
            customer=self.request.user,
            is_active=True,
        ).order_by('-is_default', '-created_at')

    @extend_schema(
        operation_id='customer_address_list',
        summary='Danh sách địa chỉ của khách hàng',
        description='Lấy toàn bộ địa chỉ đang hoạt động của khách hàng, ưu tiên địa chỉ mặc định lên đầu.',
        tags=['Address - Customer'],
    )
    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách địa điểm thành công.',
            'data': self.get_serializer(self.get_queryset(), many=True).data,
        })

    @extend_schema(
        operation_id='customer_address_create',
        summary='Thêm địa chỉ mới cho khách hàng',
        description='Tạo một địa chỉ giao dịch mới và tự xác định địa chỉ mặc định nếu đây là địa chỉ đầu tiên hoặc người dùng yêu cầu.',
        tags=['Address - Customer'],
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        address = serializer.save()
        return Response({
            'message': 'Thêm địa điểm thành công.',
            'data': self.get_serializer(address).data,
        }, status=status.HTTP_201_CREATED)


class CustomerAddressDetailView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = CustomerAddressSerializer

    def get_object(self):
        return get_object_or_404(
            CustomerAddress.objects,
            pk=self.kwargs['pk'],
            customer=self.request.user,
            is_active=True,
        )

    @extend_schema(
        operation_id='customer_address_detail',
        summary='Chi tiết địa chỉ khách hàng',
        description='Lấy thông tin chi tiết của một địa chỉ theo ID, chỉ trả về địa chỉ thuộc về tài khoản hiện tại.',
        tags=['Address - Customer'],
    )
    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy chi tiết địa điểm thành công.',
            'data': self.get_serializer(self.get_object()).data,
        })

    @extend_schema(
        operation_id='customer_address_update',
        summary='Cập nhật địa chỉ khách hàng',
        description='Sửa một phần hoặc toàn bộ thông tin địa chỉ của khách hàng. Có thể cập nhật và đặt lại địa chỉ mặc định.',
        tags=['Address - Customer'],
    )
    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        address = serializer.save()
        return Response({
            'message': 'Cập nhật địa điểm thành công.',
            'data': self.get_serializer(address).data,
        })

    @extend_schema(
        operation_id='customer_address_delete',
        summary='Xóa địa chỉ khách hàng',
        description='Xóa mềm địa chỉ: địa chỉ sẽ bị vô hiệu hóa nhưng dữ liệu vẫn được lưu lại cho hệ thống.',
        tags=['Address - Customer'],
    )
    def delete(self, request, *args, **kwargs):
        soft_delete_address(self.get_object())
        return Response({'message': 'Xóa địa điểm thành công.'})


class CustomerAddressSetDefaultView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = CustomerAddressSerializer

    def get_object(self):
        return get_object_or_404(
            CustomerAddress.objects,
            pk=self.kwargs['pk'],
            customer=self.request.user,
            is_active=True,
        )

    @extend_schema(
        operation_id='customer_address_set_default',
        summary='Đặt địa chỉ mặc định',
        description='Thiết lập địa chỉ được chọn làm địa chỉ mặc định cho tài khoản khách hàng.',
        tags=['Address - Customer'],
    )
    def patch(self, request, *args, **kwargs):
        address = set_default_address(self.get_object())
        return Response({
            'message': 'Đặt địa điểm mặc định thành công.',
            'data': self.get_serializer(address).data,
        })


class CustomerVoucherListView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = VoucherPublicSerializer

    def get_queryset(self):
        now = timezone.now()
        return (
            Voucher.objects.filter(
                distribution_type=Voucher.DistributionType.PUBLIC,
                is_active=True,
                start_at__lte=now,
                end_at__gte=now,
            )
            .filter(Q(issuance_limit__isnull=True) | Q(issued_count__lt=F('issuance_limit')))
            .exclude(user_vouchers__user=self.request.user)
            .order_by('end_at', 'id')
        )

    @extend_schema(
        operation_id='customer_voucher_list',
        summary='Danh sách voucher public có thể nhận',
        tags=['Voucher - Customer'],
    )
    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách voucher có thể nhận thành công.',
            'data': self.get_serializer(self.get_queryset(), many=True).data,
        })


class CustomerVoucherDetailView(CustomerVoucherListView):
    @extend_schema(
        operation_id='customer_voucher_detail',
        summary='Chi tiết voucher public có thể nhận',
        tags=['Voucher - Customer'],
    )
    def get(self, request, *args, **kwargs):
        voucher = get_object_or_404(self.get_queryset(), pk=self.kwargs['pk'])
        return Response({
            'message': 'Lấy chi tiết voucher thành công.',
            'data': self.get_serializer(voucher).data,
        })


@CUSTOMER_VOUCHER_WALLET_LIST_SCHEMA
class CustomerVoucherWalletListView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = UserVoucherSerializer

    def get_queryset(self):
        return UserVoucher.objects.filter(
            user=self.request.user,
        ).select_related('voucher').order_by('-created_at')

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách voucher trong ví thành công.',
            'data': self.get_serializer(self.get_queryset(), many=True).data,
        })


@CUSTOMER_CODE_VOUCHER_CLAIM_SCHEMA
class CustomerCodeVoucherClaimView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = VoucherCodeClaimSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_voucher = claim_voucher_by_code(
            code=serializer.validated_data['code'],
            customer=request.user,
        )
        return Response({
            'message': 'Nhận voucher bằng mã thành công.',
            'data': UserVoucherSerializer(
                user_voucher,
                context=self.get_serializer_context(),
            ).data,
        }, status=status.HTTP_201_CREATED)


class CustomerVoucherValidateView(generics.GenericAPIView):
    """Kiểm tra mã voucher và xem trước số tiền giảm; không giữ lượt sử dụng."""

    permission_classes = [IsCustomerRole]
    serializer_class = VoucherValidationSerializer

    @extend_schema(
        operation_id='customer_voucher_validate',
        summary='Kiểm tra voucher trước khi đặt dịch vụ',
        tags=['Voucher - Customer'],
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = validate_and_calculate_voucher(
            code=serializer.validated_data['code'],
            customer=request.user,
            subtotal_amount=serializer.validated_data['subtotal_amount'],
        )
        return Response({
            'message': 'Voucher hợp lệ.',
            'data': {
                'voucher': VoucherPublicSerializer(
                    result['voucher'],
                    context=self.get_serializer_context(),
                ).data,
                'subtotal_amount': result['subtotal_amount'],
                'discount_amount': result['discount_amount'],
                'total_amount': result['total_amount'],
            },
        })


@ADMIN_VOUCHER_LIST_CREATE_SCHEMA
class AdminVoucherListCreateView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = VoucherAdminSerializer

    def get_queryset(self):
        queryset = Voucher.objects.all().order_by('-created_at')
        is_active = self.request.query_params.get('is_active')
        discount_type = self.request.query_params.get('discount_type')
        distribution_type = self.request.query_params.get('distribution_type')
        search = self.request.query_params.get('search')
        if is_active is not None:
            if is_active.lower() not in {'true', 'false'}:
                raise ValidationError({'is_active': 'Giá trị phải là true hoặc false.'})
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        if discount_type:
            discount_type = discount_type.upper()
            if discount_type not in Voucher.DiscountType.values:
                raise ValidationError({'discount_type': 'Loại giảm giá không hợp lệ.'})
            queryset = queryset.filter(discount_type=discount_type)
        if distribution_type:
            distribution_type = distribution_type.upper()
            if distribution_type not in Voucher.DistributionType.values:
                raise ValidationError({'distribution_type': 'Cách phát hành voucher không hợp lệ.'})
            queryset = queryset.filter(distribution_type=distribution_type)
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))
        return queryset

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách voucher thành công.',
            'data': self.get_serializer(self.get_queryset(), many=True).data,
        })

    def post(self, request, *args, **kwargs):
        serializer = VoucherAdminWriteSerializer(
            data=request.data,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        voucher = serializer.save()
        return Response({
            'message': 'Tạo voucher thành công.',
            'data': self.get_serializer(voucher).data,
        }, status=status.HTTP_201_CREATED)


@ADMIN_VOUCHER_DETAIL_SCHEMA
class AdminVoucherDetailView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = VoucherAdminSerializer
    queryset = Voucher.objects.all()

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy chi tiết voucher thành công.',
            'data': self.get_serializer(self.get_object()).data,
        })

    def patch(self, request, *args, **kwargs):
        serializer = VoucherAdminWriteSerializer(
            self.get_object(),
            data=request.data,
            partial=True,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        voucher = serializer.save()
        return Response({
            'message': 'Cập nhật voucher thành công.',
            'data': self.get_serializer(voucher).data,
        })

    def delete(self, request, *args, **kwargs):
        voucher = self.get_object()
        voucher.is_active = False
        voucher.save(update_fields=['is_active', 'updated_at'])
        return Response({'message': 'Ngừng sử dụng voucher thành công.'})


@ADMIN_VOUCHER_BY_CODE_SCHEMA
class AdminVoucherByCodeDetailView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = VoucherAdminSerializer

    def get(self, request, *args, **kwargs):
        voucher = get_object_or_404(
            Voucher.objects.all(),
            code__iexact=self.kwargs['code'].strip(),
        )
        return Response({
            'message': 'Lấy chi tiết voucher theo mã thành công.',
            'data': self.get_serializer(voucher).data,
        })

class BookingPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


@BOOKING_CUSTOMER_SCHEMA
class BookingListCreateView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    pagination_class = BookingPagination

    def get_queryset(self):
        queryset = Booking.objects.filter(
            customer=self.request.user,
        ).select_related('service').order_by('-created_at')

        status_param = self.request.query_params.get('status')
        if status_param:
            status_param = status_param.upper()
            if status_param not in Booking.Status.values:
                raise ValidationError({'status': 'Trạng thái đơn hàng không hợp lệ.'})
            queryset = queryset.filter(status=status_param)

        return queryset

    def get_serializer_class(self):
        return BookingCreateSerializer if self.request.method == 'POST' else BookingListSerializer

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serialized = BookingListSerializer(page, many=True).data
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
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()
        return Response({
            'message': 'Đặt dịch vụ thành công.',
            'data': BookingDetailSerializer(booking).data,
        }, status=status.HTTP_201_CREATED)


@BOOKING_DETAIL_CUSTOMER_SCHEMA
class BookingDetailView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = BookingDetailSerializer

    def get_object(self):
        return get_object_or_404(
            Booking.objects.select_related('service').prefetch_related('schedules'),
            pk=self.kwargs['pk'],
            customer=self.request.user,
        )

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy chi tiết đơn hàng thành công.',
            'data': self.get_serializer(self.get_object()).data,
        })


@BOOKING_ADMIN_SCHEMA
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
        return Response({
            'message': 'Gán nhân viên thành công.',
            'data': {'assignment_id': assignment.id},
        }, status=status.HTTP_201_CREATED)