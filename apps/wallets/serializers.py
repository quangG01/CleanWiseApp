from rest_framework import serializers

from .models import Wallet, WalletTransaction


class WalletTransactionSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    booking_code = serializers.CharField(source='booking.booking_code', read_only=True, allow_null=True)

    class Meta:
        model = WalletTransaction
        fields = [
            'id', 'type', 'type_display', 'amount', 'balance_after',
            'status', 'status_display', 'booking_code', 'note', 'created_at',
        ]


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ['id', 'balance', 'updated_at']


class WithdrawRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1000)