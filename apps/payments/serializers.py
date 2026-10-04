import re

from django.db import transaction
from rest_framework import serializers

from apps.common.encryption import decrypt_value, encrypt_value

from .bank_catalog import get_bank_catalog
from .models import UserPaymentMethod
from .payment_method_service import set_default_payment_method

MAX_BANK_ACCOUNTS_PER_USAGE = 5


class UserPaymentMethodSerializer(serializers.ModelSerializer):
    account_number_masked = serializers.CharField(read_only=True)
    method_type_display = serializers.CharField(source='get_method_type_display', read_only=True)
    verification_status_display = serializers.CharField(
        source='get_verification_status_display',
        read_only=True,
    )

    class Meta:
        model = UserPaymentMethod
        fields = [
            'id', 'method_type', 'method_type_display', 'usage_type', 'display_name',
            'bank_bin', 'bank_code', 'bank_name', 'account_holder_name',
            'account_number_masked', 'verification_status',
            'verification_status_display', 'is_default', 'created_at', 'updated_at',
        ]


class BankPaymentMethodCreateSerializer(serializers.Serializer):
    bank_bin = serializers.CharField(max_length=10)
    # bank_code / bank_name do client gửi chỉ để tương thích, server luôn ghi đè bằng dữ liệu catalog.
    bank_code = serializers.CharField(max_length=30, required=False, allow_blank=True)
    bank_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    account_number = serializers.CharField(write_only=True, min_length=6, max_length=19)
    account_holder_name = serializers.CharField(max_length=150)
    display_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    is_default = serializers.BooleanField(required=False, default=False)

    def validate_bank_bin(self, value):
        value = value.strip()
        if not re.fullmatch(r'\d{6,10}', value):
            raise serializers.ValidationError('Mã BIN ngân hàng không hợp lệ.')
        return value

    def validate_account_number(self, value):
        value = re.sub(r'\s+', '', value)
        if not re.fullmatch(r'\d{6,19}', value):
            raise serializers.ValidationError('Số tài khoản chỉ được gồm từ 6 đến 19 chữ số.')
        return value

    def validate_account_holder_name(self, value):
        value = ' '.join(value.split())
        if len(value) < 2:
            raise serializers.ValidationError('Tên chủ tài khoản không hợp lệ.')
        return value

    def validate(self, attrs):
        user = self.context['request'].user
        usage_type = self.context.get(
            'usage_type',
            UserPaymentMethod.UsageType.PAYMENT,
        )

        # BIN phải nằm trong catalog VietQR và hỗ trợ chuyển khoản; tên/mã ngân hàng lấy từ catalog,
        # không tin dữ liệu client (tiền đi theo BIN, tên hiển thị không được phép lệch).
        bank = next((b for b in get_bank_catalog() if b['bin'] == attrs['bank_bin']), None)
        if not bank or not bank['transfer_supported']:
            raise serializers.ValidationError({'bank_bin': 'Ngân hàng không được hỗ trợ.'})
        attrs['bank_code'] = bank['code']
        attrs['bank_name'] = bank['short_name'] or bank['name']

        active = UserPaymentMethod.objects.filter(user=user, usage_type=usage_type, is_active=True)
        if active.count() >= MAX_BANK_ACCOUNTS_PER_USAGE:
            raise serializers.ValidationError({
                'detail': f'Chỉ được lưu tối đa {MAX_BANK_ACCOUNTS_PER_USAGE} tài khoản ngân hàng.',
            })

        account_number = attrs['account_number']
        existing_methods = active.filter(
            method_type=UserPaymentMethod.MethodType.BANK_ACCOUNT,
            bank_bin=attrs['bank_bin'],
        )
        for method in existing_methods:
            try:
                if decrypt_value(method.account_number_encrypted) == account_number:
                    raise serializers.ValidationError(
                        {'account_number': 'Tài khoản ngân hàng này đã được lưu.'}
                    )
            except serializers.ValidationError:
                raise
            except Exception:
                # Dữ liệu cũ không giải mã được không được phép làm gián đoạn việc thêm mới.
                continue
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        user = self.context['request'].user
        usage_type = self.context.get(
            'usage_type',
            UserPaymentMethod.UsageType.PAYMENT,
        )
        account_number = validated_data.pop('account_number')
        requested_default = validated_data.pop('is_default', False)
        is_first = not UserPaymentMethod.objects.select_for_update().filter(
            user=user,
            usage_type=usage_type,
            is_active=True,
        ).exists()

        method = UserPaymentMethod.objects.create(
            user=user,
            method_type=UserPaymentMethod.MethodType.BANK_ACCOUNT,
            usage_type=usage_type,
            account_number_encrypted=encrypt_value(account_number),
            account_number_last4=account_number[-4:],
            verification_status=UserPaymentMethod.VerificationStatus.UNVERIFIED,
            is_default=False,
            **validated_data,
        )
        if requested_default or is_first:
            set_default_payment_method(method)
        return method


class UserPaymentMethodUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPaymentMethod
        fields = ['display_name', 'account_holder_name']

    def validate_account_holder_name(self, value):
        value = ' '.join(value.split())
        if len(value) < 2:
            raise serializers.ValidationError('Tên chủ tài khoản không hợp lệ.')
        return value