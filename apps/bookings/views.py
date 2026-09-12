from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.common.permissions import IsAdminRole, IsCustomerRole

from .address_service import set_default_address, soft_delete_address
from .models import BookingVoucher, CustomerAddress, UserVoucher, Voucher
from .schemas import (
    ADMIN_USER_VOUCHER_DETAIL_SCHEMA,
    ADMIN_USER_VOUCHER_LIST_CREATE_SCHEMA,
    CUSTOMER_ADDRESS_DETAIL_SCHEMA,
    CUSTOMER_ADDRESS_LIST_CREATE_SCHEMA,
    CUSTOMER_ADDRESS_SET_DEFAULT_SCHEMA,
    CUSTOMER_AVAILABLE_VOUCHER_SCHEMA,
    CUSTOMER_VOUCHER_CLAIM_CODE_SCHEMA,
    CUSTOMER_VOUCHER_CLAIM_SCHEMA,
    CUSTOMER_VOUCHER_DETAIL_SCHEMA,
    CUSTOMER_VOUCHER_LIST_SCHEMA,
    ADMIN_VOUCHER_DETAIL_SCHEMA,
    ADMIN_VOUCHER_LIST_CREATE_SCHEMA,
)
from .serializers import (
    CustomerAddressSerializer,
    UserVoucherAdminSerializer,
    UserVoucherCustomerSerializer,
    VoucherAdminSerializer,
    VoucherClaimCodeSerializer,
    VoucherPublicSerializer,
)
from .user_voucher_service import (
    claim_public_voucher,
    claim_voucher_by_code,
    revoke_user_voucher,
)


@CUSTOMER_ADDRESS_LIST_CREATE_SCHEMA
class CustomerAddressListCreateView(generics.GenericAPIView):
    """GET/POST /api/customer/addresses/"""

    permission_classes = [IsCustomerRole]
    serializer_class = CustomerAddressSerializer

    def get_queryset(self):
        return (
            CustomerAddress.objects
            .filter(customer=self.request.user, is_active=True)
            .order_by('-is_default', '-created_at')
        )

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return Response({
            'message': 'Lấy danh sách địa điểm thành công.',
            'data': serializer.data,
        }, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        address = serializer.save()
        return Response({
            'message': 'Thêm địa điểm thành công.',
            'data': self.get_serializer(address).data,
        }, status=status.HTTP_201_CREATED)


@CUSTOMER_ADDRESS_DETAIL_SCHEMA
class CustomerAddressDetailView(generics.GenericAPIView):
    """GET/PATCH/DELETE /api/customer/addresses/<address_id>/"""

    permission_classes = [IsCustomerRole]
    serializer_class = CustomerAddressSerializer

    def get_object(self):
        return get_object_or_404(
            CustomerAddress.objects,
            pk=self.kwargs['pk'],
            customer=self.request.user,
            is_active=True,
        )

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy chi tiết địa điểm thành công.',
            'data': self.get_serializer(self.get_object()).data,
        }, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            self.get_object(),
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        address = serializer.save()
        return Response({
            'message': 'Cập nhật địa điểm thành công.',
            'data': self.get_serializer(address).data,
        }, status=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        soft_delete_address(self.get_object())
        return Response({
            'message': 'Xóa địa điểm thành công.'
        }, status=status.HTTP_200_OK)


@CUSTOMER_ADDRESS_SET_DEFAULT_SCHEMA
class CustomerAddressSetDefaultView(generics.GenericAPIView):
    """PATCH /api/customer/addresses/<address_id>/default/"""

    permission_classes = [IsCustomerRole]
    serializer_class = CustomerAddressSerializer

    def get_object(self):
        return get_object_or_404(
            CustomerAddress.objects,
            pk=self.kwargs['pk'],
            customer=self.request.user,
            is_active=True,
        )

    def patch(self, request, *args, **kwargs):
        address = set_default_address(self.get_object())
        return Response({
            'message': 'Đặt địa điểm mặc định thành công.',
            'data': self.get_serializer(address).data,
        }, status=status.HTTP_200_OK)


@ADMIN_VOUCHER_LIST_CREATE_SCHEMA
class AdminVoucherListCreateView(generics.GenericAPIView):
    """GET/POST /api/admin/vouchers/"""

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
                from rest_framework.exceptions import ValidationError
                raise ValidationError({'is_active': 'Giá trị phải là true hoặc false.'})
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        if discount_type:
            queryset = queryset.filter(discount_type=discount_type.upper())
        if distribution_type:
            distribution_type = distribution_type.upper()
            if distribution_type not in Voucher.DistributionType.values:
                raise ValidationError({'distribution_type': 'Loại phát hành không hợp lệ.'})
            queryset = queryset.filter(distribution_type=distribution_type)
        if search:
            from django.db.models import Q
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))
        return queryset

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return Response({
            'message': 'Lấy danh sách voucher thành công.',
            'data': serializer.data,
        }, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        voucher = serializer.save()
        return Response({
            'message': 'Tạo voucher thành công.',
            'data': self.get_serializer(voucher).data,
        }, status=status.HTTP_201_CREATED)


@ADMIN_VOUCHER_DETAIL_SCHEMA
class AdminVoucherDetailView(generics.GenericAPIView):
    """GET/PATCH/DELETE /api/admin/vouchers/<voucher_id>/"""

    permission_classes = [IsAdminRole]
    serializer_class = VoucherAdminSerializer
    queryset = Voucher.objects.all()

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy chi tiết voucher thành công.',
            'data': self.get_serializer(self.get_object()).data,
        }, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            self.get_object(),
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        voucher = serializer.save()
        return Response({
            'message': 'Cập nhật voucher thành công.',
            'data': self.get_serializer(voucher).data,
        }, status=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        voucher = self.get_object()
        voucher.is_active = False
        voucher.save(update_fields=['is_active', 'updated_at'])
        return Response({
            'message': 'Ngừng sử dụng voucher thành công.'
        }, status=status.HTTP_200_OK)


def _customer_user_voucher_queryset(user):
    return (
        UserVoucher.objects.filter(user=user)
        .select_related('voucher')
        .annotate(
            customer_usage_count=Count(
                'voucher__booking_vouchers',
                filter=Q(
                    voucher__booking_vouchers__booking__customer=user,
                    voucher__booking_vouchers__status__in=[
                        BookingVoucher.Status.RESERVED,
                        BookingVoucher.Status.USED,
                    ],
                ),
                distinct=True,
            )
        )
    )


@CUSTOMER_AVAILABLE_VOUCHER_SCHEMA
class CustomerAvailableVoucherListView(generics.GenericAPIView):
    """GET /api/customer/vouchers/available/"""

    permission_classes = [IsCustomerRole]
    serializer_class = VoucherPublicSerializer

    def get(self, request, *args, **kwargs):
        now = timezone.now()
        queryset = (
            Voucher.objects.filter(
                distribution_type=Voucher.DistributionType.PUBLIC,
                is_active=True,
                start_at__lte=now,
                end_at__gte=now,
            )
            .exclude(user_vouchers__user=request.user)
            .filter(Q(usage_limit__isnull=True) | Q(used_count__lt=F('usage_limit')))
            .annotate(
                customer_usage_count=Count(
                    'booking_vouchers',
                    filter=Q(
                        booking_vouchers__booking__customer=request.user,
                        booking_vouchers__status__in=[
                            BookingVoucher.Status.RESERVED,
                            BookingVoucher.Status.USED,
                        ],
                    ),
                    distinct=True,
                )
            )
            .filter(customer_usage_count__lt=F('per_user_limit'))
            .order_by('end_at', '-created_at')
        )
        return Response({
            'message': 'Lấy danh sách voucher có thể nhận thành công.',
            'data': self.get_serializer(queryset, many=True).data,
        }, status=status.HTTP_200_OK)


@CUSTOMER_VOUCHER_CLAIM_SCHEMA
class CustomerVoucherClaimView(generics.GenericAPIView):
    """POST /api/customer/vouchers/available/<voucher_id>/claim/"""

    permission_classes = [IsCustomerRole]
    serializer_class = UserVoucherCustomerSerializer

    def post(self, request, *args, **kwargs):
        user_voucher, created = claim_public_voucher(
            user=request.user,
            voucher_id=self.kwargs['pk'],
        )
        return Response({
            'message': 'Nhận voucher thành công.' if created else 'Bạn đã nhận voucher này rồi.',
            'data': self.get_serializer(user_voucher).data,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@CUSTOMER_VOUCHER_CLAIM_CODE_SCHEMA
class CustomerVoucherClaimCodeView(generics.GenericAPIView):
    """POST /api/customer/vouchers/claim-code/"""

    permission_classes = [IsCustomerRole]
    serializer_class = VoucherClaimCodeSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_voucher, created = claim_voucher_by_code(
            user=request.user,
            code=serializer.validated_data['code'],
        )
        return Response({
            'message': 'Nhận voucher thành công.' if created else 'Bạn đã nhận voucher này rồi.',
            'data': UserVoucherCustomerSerializer(user_voucher).data,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@CUSTOMER_VOUCHER_LIST_SCHEMA
class CustomerVoucherListView(generics.GenericAPIView):
    """GET /api/customer/vouchers/"""

    permission_classes = [IsCustomerRole]
    serializer_class = UserVoucherCustomerSerializer

    def get(self, request, *args, **kwargs):
        requested_status = request.query_params.get('status')
        allowed_statuses = {
            'AVAILABLE', 'UPCOMING', 'EXPIRED', 'EXHAUSTED', 'DISABLED', 'REVOKED'
        }
        if requested_status:
            requested_status = requested_status.upper()
            if requested_status not in allowed_statuses:
                raise ValidationError({'status': 'Trạng thái lọc không hợp lệ.'})

        queryset = _customer_user_voucher_queryset(request.user)
        if requested_status != 'REVOKED':
            queryset = queryset.filter(is_visible=True)
        serialized = self.get_serializer(queryset, many=True).data
        if requested_status:
            serialized = [
                item for item in serialized
                if item['availability_status'] == requested_status
            ]
        return Response({
            'message': 'Lấy ví voucher thành công.',
            'data': serialized,
        }, status=status.HTTP_200_OK)


@CUSTOMER_VOUCHER_DETAIL_SCHEMA
class CustomerVoucherDetailView(generics.GenericAPIView):
    """GET/PATCH/DELETE /api/customer/vouchers/<user_voucher_id>/"""

    permission_classes = [IsCustomerRole]
    serializer_class = UserVoucherCustomerSerializer

    def get_object(self):
        return get_object_or_404(
            _customer_user_voucher_queryset(self.request.user),
            pk=self.kwargs['pk'],
        )

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy chi tiết voucher trong ví thành công.',
            'data': self.get_serializer(self.get_object()).data,
        }, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            self.get_object(),
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        user_voucher = serializer.save()
        return Response({
            'message': 'Cập nhật hiển thị voucher thành công.',
            'data': self.get_serializer(user_voucher).data,
        }, status=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        user_voucher = self.get_object()
        user_voucher.is_visible = False
        user_voucher.save(update_fields=['is_visible', 'updated_at'])
        return Response({
            'message': 'Đã ẩn voucher khỏi ví.'
        }, status=status.HTTP_200_OK)


@ADMIN_USER_VOUCHER_LIST_CREATE_SCHEMA
class AdminUserVoucherListCreateView(generics.GenericAPIView):
    """GET/POST /api/admin/user-vouchers/"""

    permission_classes = [IsAdminRole]
    serializer_class = UserVoucherAdminSerializer

    def get_queryset(self):
        queryset = UserVoucher.objects.select_related(
            'user', 'voucher', 'created_by'
        ).order_by('-received_at')
        for parameter in ('user_id', 'voucher_id'):
            value = self.request.query_params.get(parameter)
            if value:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise ValidationError({parameter: 'Giá trị phải là số nguyên.'})
                queryset = queryset.filter(**{parameter: value})

        status_value = self.request.query_params.get('status')
        if status_value:
            status_value = status_value.upper()
            if status_value not in UserVoucher.Status.values:
                raise ValidationError({'status': 'Trạng thái không hợp lệ.'})
            queryset = queryset.filter(status=status_value)

        source_value = self.request.query_params.get('source')
        if source_value:
            source_value = source_value.upper()
            if source_value not in UserVoucher.Source.values:
                raise ValidationError({'source': 'Nguồn cấp voucher không hợp lệ.'})
            queryset = queryset.filter(source=source_value)
        return queryset

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách voucher của người dùng thành công.',
            'data': self.get_serializer(self.get_queryset(), many=True).data,
        }, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_voucher = serializer.save()
        created = getattr(serializer, 'was_created', True)
        return Response({
            'message': 'Cấp voucher thành công.' if created else 'Người dùng đã có voucher này.',
            'data': self.get_serializer(user_voucher).data,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@ADMIN_USER_VOUCHER_DETAIL_SCHEMA
class AdminUserVoucherDetailView(generics.GenericAPIView):
    """GET/PATCH/DELETE /api/admin/user-vouchers/<id>/"""

    permission_classes = [IsAdminRole]
    serializer_class = UserVoucherAdminSerializer
    queryset = UserVoucher.objects.select_related('user', 'voucher', 'created_by')

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy chi tiết voucher của người dùng thành công.',
            'data': self.get_serializer(self.get_object()).data,
        }, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            self.get_object(),
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        user_voucher = serializer.save()
        return Response({
            'message': 'Cập nhật voucher của người dùng thành công.',
            'data': self.get_serializer(user_voucher).data,
        }, status=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        revoke_user_voucher(self.get_object())
        return Response({
            'message': 'Thu hồi voucher của người dùng thành công.'
        }, status=status.HTTP_200_OK)
