from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response

from apps.common.permissions import IsAdminRole, IsCustomerRole
from .address_service import set_default_address, soft_delete_address
from .models import CustomerAddress, Voucher
from .serializers import CustomerAddressSerializer, VoucherAdminSerializer, VoucherPublicSerializer


class CustomerAddressListCreateView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = CustomerAddressSerializer

    def get_queryset(self):
        return CustomerAddress.objects.filter(
            customer=self.request.user,
            is_active=True,
        ).select_related('area').order_by('-is_default', '-created_at')

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách địa điểm thành công.',
            'data': self.get_serializer(self.get_queryset(), many=True).data,
        })

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
            CustomerAddress.objects.select_related('area'),
            pk=self.kwargs['pk'],
            customer=self.request.user,
            is_active=True,
        )

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy chi tiết địa điểm thành công.',
            'data': self.get_serializer(self.get_object()).data,
        })

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        address = serializer.save()
        return Response({
            'message': 'Cập nhật địa điểm thành công.',
            'data': self.get_serializer(address).data,
        })

    def delete(self, request, *args, **kwargs):
        soft_delete_address(self.get_object())
        return Response({'message': 'Xóa địa điểm thành công.'})


class CustomerAddressSetDefaultView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    serializer_class = CustomerAddressSerializer

    def get_object(self):
        return get_object_or_404(
            CustomerAddress.objects.select_related('area'),
            pk=self.kwargs['pk'],
            customer=self.request.user,
            is_active=True,
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
        return Voucher.objects.filter(
            is_active=True,
            start_at__lte=now,
            end_at__gte=now,
        ).filter(Q(usage_limit__isnull=True) | Q(used_count__lt=F('usage_limit')))

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách voucher khả dụng thành công.',
            'data': self.get_serializer(self.get_queryset(), many=True).data,
        })


class CustomerVoucherDetailView(CustomerVoucherListView):
    def get(self, request, *args, **kwargs):
        voucher = get_object_or_404(self.get_queryset(), pk=self.kwargs['pk'])
        return Response({
            'message': 'Lấy chi tiết voucher thành công.',
            'data': self.get_serializer(voucher).data,
        })


class AdminVoucherListCreateView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = VoucherAdminSerializer

    def get_queryset(self):
        queryset = Voucher.objects.all().order_by('-created_at')
        is_active = self.request.query_params.get('is_active')
        discount_type = self.request.query_params.get('discount_type')
        search = self.request.query_params.get('search')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        if discount_type:
            queryset = queryset.filter(discount_type=discount_type.upper())
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))
        return queryset

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách voucher thành công.',
            'data': self.get_serializer(self.get_queryset(), many=True).data,
        })

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        voucher = serializer.save()
        return Response({
            'message': 'Tạo voucher thành công.',
            'data': self.get_serializer(voucher).data,
        }, status=status.HTTP_201_CREATED)


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
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
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
