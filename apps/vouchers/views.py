from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.common.permissions import IsAdminRole, IsCustomerRole

from .models import UserVoucher, Voucher
from .serializers import (
    UserVoucherSerializer,
    VoucherAdminSerializer,
    VoucherAdminWriteSerializer,
    VoucherCodeClaimSerializer,
    VoucherPublicSerializer,
    VoucherValidationSerializer,
)
from .voucher_service import claim_voucher_by_code, validate_and_calculate_voucher

from .schemas import (
    VOUCHER_CUSTOMER_LIST_SCHEMA,
    VOUCHER_CUSTOMER_DETAIL_SCHEMA,
    VOUCHER_WALLET_SCHEMA,
    VOUCHER_CLAIM_SCHEMA,
    VOUCHER_VALIDATE_SCHEMA,
    VOUCHER_ADMIN_LIST_CREATE_SCHEMA,
    VOUCHER_ADMIN_DETAIL_SCHEMA,
    VOUCHER_ADMIN_BY_CODE_SCHEMA,
)

@VOUCHER_CUSTOMER_LIST_SCHEMA
class CustomerVoucherListView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = VoucherPublicSerializer

    def get_queryset(self):
        now = timezone.now()
        return Voucher.objects.filter(
            distribution_type=Voucher.DistributionType.PUBLIC,
            is_active=True,
            start_at__lte=now,
            end_at__gte=now,
        ).filter(
            Q(issuance_limit__isnull=True) | Q(issued_count__lt=F('issuance_limit')),
        ).exclude(user_vouchers__user=self.request.user).order_by('end_at', 'id')

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách voucher có thể nhận thành công.',
            'data': self.get_serializer(self.get_queryset(), many=True).data,
        })


@VOUCHER_CUSTOMER_DETAIL_SCHEMA
class CustomerVoucherDetailView(CustomerVoucherListView):
    def get(self, request, *args, **kwargs):
        voucher = get_object_or_404(self.get_queryset(), pk=self.kwargs['pk'])
        return Response({
            'message': 'Lấy chi tiết voucher thành công.',
            'data': self.get_serializer(voucher).data,
        })


@VOUCHER_WALLET_SCHEMA
class CustomerVoucherWalletListView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = UserVoucherSerializer

    def get_queryset(self):
        return UserVoucher.objects.filter(user=self.request.user).select_related('voucher').order_by('-created_at')

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách voucher trong ví thành công.',
            'data': self.get_serializer(self.get_queryset(), many=True).data,
        })


@VOUCHER_CLAIM_SCHEMA
class CustomerCodeVoucherClaimView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = VoucherCodeClaimSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_voucher = claim_voucher_by_code(code=serializer.validated_data['code'], customer=request.user)
        return Response({
            'message': 'Nhận voucher bằng mã thành công.',
            'data': UserVoucherSerializer(user_voucher, context=self.get_serializer_context()).data,
        }, status=status.HTTP_201_CREATED)


@VOUCHER_VALIDATE_SCHEMA
class CustomerVoucherValidateView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = VoucherValidationSerializer

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
                'voucher': VoucherPublicSerializer(result['voucher'], context=self.get_serializer_context()).data,
                'subtotal_amount': result['subtotal_amount'],
                'discount_amount': result['discount_amount'],
                'total_amount': result['total_amount'],
            },
        })


@VOUCHER_ADMIN_LIST_CREATE_SCHEMA
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
        return Response({'message': 'Lấy danh sách voucher thành công.', 'data': self.get_serializer(self.get_queryset(), many=True).data})

    def post(self, request, *args, **kwargs):
        serializer = VoucherAdminWriteSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        voucher = serializer.save()
        return Response({'message': 'Tạo voucher thành công.', 'data': self.get_serializer(voucher).data}, status=status.HTTP_201_CREATED)


@VOUCHER_ADMIN_DETAIL_SCHEMA
class AdminVoucherDetailView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = VoucherAdminSerializer
    queryset = Voucher.objects.all()

    def get(self, request, *args, **kwargs):
        return Response({'message': 'Lấy chi tiết voucher thành công.', 'data': self.get_serializer(self.get_object()).data})

    def patch(self, request, *args, **kwargs):
        serializer = VoucherAdminWriteSerializer(self.get_object(), data=request.data, partial=True, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        voucher = serializer.save()
        return Response({'message': 'Cập nhật voucher thành công.', 'data': self.get_serializer(voucher).data})

    def delete(self, request, *args, **kwargs):
        voucher = self.get_object()
        voucher.is_active = False
        voucher.save(update_fields=['is_active', 'updated_at'])
        return Response({'message': 'Ngừng sử dụng voucher thành công.'})


@VOUCHER_ADMIN_BY_CODE_SCHEMA
class AdminVoucherByCodeDetailView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = VoucherAdminSerializer

    def get(self, request, *args, **kwargs):
        voucher = get_object_or_404(Voucher.objects.all(), code__iexact=self.kwargs['code'].strip())
        return Response({'message': 'Lấy chi tiết voucher theo mã thành công.', 'data': self.get_serializer(voucher).data})
