from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.response import Response

from apps.bookings.models import Booking
from apps.common.distributed_lock import distributed_lock
from apps.common.idempotency import idempotent
from apps.common.permissions import IsAdminRole

from . import refund_service, wallet_service
from .models import WalletTransaction
from .serializers import WalletTransactionSerializer

User = get_user_model()


class AdminRefundSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1, required=False)
    reason = serializers.CharField(max_length=500)


class AdminAdjustSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    direction = serializers.ChoiceField(choices=['CREDIT', 'DEBIT'])
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    reason = serializers.CharField(max_length=500)
    booking_id = serializers.IntegerField(required=False, allow_null=True)


class AdminBookingRefundView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminRefundSerializer

    @idempotent
    def post(self, request, pk):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with distributed_lock(f'booking:{pk}'):
            booking, refunded = refund_service.admin_refund_booking(
                booking_id=pk, admin_user=request.user,
                reason=s.validated_data['reason'], amount=s.validated_data.get('amount'),
            )
        return Response({
            'message': 'Hoàn tiền vào ví khách hàng thành công.',
            'data': {
                'booking_id': booking.id,
                'refunded': str(refunded),
                'refunded_amount': str(booking.refunded_amount),
                'payment_status': booking.payment_status,
            },
        })


class AdminWalletAdjustView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminAdjustSerializer

    @idempotent
    def post(self, request):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        user = get_object_or_404(User, pk=d['user_id'], is_active=True)
        if user.role not in ('CUSTOMER', 'WORKER'):
            raise serializers.ValidationError({'user_id': 'Chỉ điều chỉnh ví khách hàng hoặc nhân viên.'})
        booking = get_object_or_404(Booking, pk=d['booking_id']) if d.get('booking_id') else None

        tx = wallet_service.admin_adjust_wallet(
            user=user, amount=d['amount'], direction=d['direction'],
            reason=d['reason'], admin_user=request.user, booking=booking,
        )
        return Response(
            {'message': 'Điều chỉnh số dư ví thành công.', 'data': WalletTransactionSerializer(tx).data},
            status=status.HTTP_201_CREATED,
        )


class AdminUserWalletView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = WalletTransactionSerializer

    def get(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        wallet, _ = wallet_service.get_or_create_wallet(user)
        txs = (
            WalletTransaction.objects.filter(wallet=wallet)
            .select_related('booking').order_by('-created_at')[:50]
        )
        return Response({
            'message': 'Lấy thông tin ví thành công.',
            'data': {
                'user_id': user.id,
                'role': user.role,
                'balance': str(wallet.balance),
                'transactions': WalletTransactionSerializer(txs, many=True).data,
            },
        })