from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response

from apps.common.permissions import IsCustomerRole, IsWorkerRole

from .bank_catalog import get_bank_catalog
from .models import UserPaymentMethod
from .payment_method_service import set_default_payment_method, soft_delete_payment_method
from .serializers import (
    BankPaymentMethodCreateSerializer,
    UserPaymentMethodSerializer,
    UserPaymentMethodUpdateSerializer,
)

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import webhook_service


class CustomerPaymentMethodListCreateView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    usage_type = UserPaymentMethod.UsageType.PAYMENT

    def get_queryset(self):
        return UserPaymentMethod.objects.filter(
            user=self.request.user,
            usage_type=self.usage_type,
            is_active=True,
        ).order_by('-is_default', '-created_at')

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return BankPaymentMethodCreateSerializer
        return UserPaymentMethodSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['usage_type'] = self.usage_type
        return context

    def get(self, request, *args, **kwargs):
        data = UserPaymentMethodSerializer(self.get_queryset(), many=True).data
        return Response({'message': 'Lấy danh sách phương thức thanh toán thành công.', 'data': data})

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        method = serializer.save()
        data = UserPaymentMethodSerializer(method).data
        return Response(
            {'message': 'Thêm tài khoản ngân hàng thành công.', 'data': data},
            status=status.HTTP_201_CREATED,
        )


class CustomerPaymentMethodDetailView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    usage_type = UserPaymentMethod.UsageType.PAYMENT

    def get_object(self):
        return get_object_or_404(
            UserPaymentMethod.objects,
            pk=self.kwargs['pk'],
            user=self.request.user,
            usage_type=self.usage_type,
            is_active=True,
        )

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy phương thức thanh toán thành công.',
            'data': UserPaymentMethodSerializer(self.get_object()).data,
        })

    def patch(self, request, *args, **kwargs):
        method = self.get_object()
        serializer = UserPaymentMethodUpdateSerializer(method, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            'message': 'Cập nhật phương thức thanh toán thành công.',
            'data': UserPaymentMethodSerializer(method).data,
        })

    def delete(self, request, *args, **kwargs):
        soft_delete_payment_method(self.get_object())
        return Response({'message': 'Xóa phương thức thanh toán thành công.'})


class CustomerPaymentMethodSetDefaultView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]
    usage_type = UserPaymentMethod.UsageType.PAYMENT

    def patch(self, request, *args, **kwargs):
        method = get_object_or_404(
            UserPaymentMethod.objects,
            pk=self.kwargs['pk'],
            user=request.user,
            usage_type=self.usage_type,
            is_active=True,
        )
        set_default_payment_method(method)
        return Response({
            'message': 'Đặt phương thức mặc định thành công.',
            'data': UserPaymentMethodSerializer(method).data,
        })


class CustomerPaymentMethodOptionsView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]

    def get(self, request, *args, **kwargs):
        options = [
            {'code': 'MOMO', 'name': 'Ví MoMo', 'status': 'COMING_SOON'},
            {'code': 'VNPAY', 'name': 'VNPAY', 'status': 'COMING_SOON'},
            {'code': 'BANK_ACCOUNT', 'name': 'Tài khoản ngân hàng', 'status': 'AVAILABLE'},
        ]
        return Response({'message': 'Lấy danh sách lựa chọn thành công.', 'data': options})


class CustomerBankCatalogView(generics.GenericAPIView):
    permission_classes = [IsCustomerRole]

    def get(self, request, *args, **kwargs):
        return Response({
            'message': 'Lấy danh sách ngân hàng thành công.',
            'data': get_bank_catalog(),
        })


class WorkerPaymentMethodListCreateView(CustomerPaymentMethodListCreateView):
    permission_classes = [IsWorkerRole]
    usage_type = UserPaymentMethod.UsageType.PAYOUT


class WorkerPaymentMethodDetailView(CustomerPaymentMethodDetailView):
    permission_classes = [IsWorkerRole]
    usage_type = UserPaymentMethod.UsageType.PAYOUT


class WorkerPaymentMethodSetDefaultView(CustomerPaymentMethodSetDefaultView):
    permission_classes = [IsWorkerRole]
    usage_type = UserPaymentMethod.UsageType.PAYOUT


class WorkerPaymentMethodOptionsView(CustomerPaymentMethodOptionsView):
    permission_classes = [IsWorkerRole]


class WorkerBankCatalogView(CustomerBankCatalogView):
    permission_classes = [IsWorkerRole]


from payos import WebhookError


class PayOSWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        try:
            webhook_data = webhook_service.verify_and_parse_payos_webhook(request.body)
        except WebhookError:
            return Response({'success': False, 'message': 'Chữ ký không hợp lệ.'}, status=status.HTTP_400_BAD_REQUEST)

        payment = webhook_service.handle_payos_webhook(webhook_data)
        return Response({'success': True, 'payment_status': payment.status if payment else None})
