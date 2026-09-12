import re

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .address_service import set_default_address
from .models import Area, CustomerAddress, UserVoucher, Voucher
from .user_voucher_service import (
    assign_voucher_to_user,
    get_user_voucher_availability,
    restore_user_voucher,
    revoke_user_voucher,
)


User = get_user_model()


class AreaSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Area
        fields = ['id', 'name', 'city']


class CustomerAddressSerializer(serializers.ModelSerializer):
    label = serializers.CharField(
        required=False,
        max_length=100,
        help_text='Tên gợi nhớ cho địa điểm, ví dụ Nhà, Công ty.',
    )
    receiver_name = serializers.CharField(
        max_length=150,
        help_text='Họ tên người nhận dịch vụ tại địa điểm.',
    )
    receiver_phone = serializers.CharField(
        max_length=15,
        help_text='Số điện thoại Việt Nam của người nhận dịch vụ.',
    )
    city = serializers.CharField(
        max_length=100,
        help_text='Tỉnh hoặc thành phố theo mô hình hành chính hai cấp.',
    )
    ward = serializers.CharField(
        max_length=100,
        help_text='Xã, phường hoặc đặc khu.',
    )
    address_line = serializers.CharField(
        help_text='Số nhà, tên đường và thông tin địa chỉ chi tiết.',
    )
    latitude = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=10,
        decimal_places=7,
        min_value=-90,
        max_value=90,
        help_text='Vĩ độ, không bắt buộc; giá trị từ -90 đến 90.',
    )
    longitude = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=10,
        decimal_places=7,
        min_value=-180,
        max_value=180,
        help_text='Kinh độ, không bắt buộc; giá trị từ -180 đến 180.',
    )

    class Meta:
        model = CustomerAddress
        fields = [
            'id',
            'label',
            'receiver_name',
            'receiver_phone',
            'address_line',
            'ward',
            'city',
            'latitude',
            'longitude',
            'is_default',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'is_active', 'created_at', 'updated_at']
        extra_kwargs = {
            'is_default': {
                'required': False,
                'help_text': 'Đặt địa điểm làm mặc định. Mỗi khách hàng chỉ có một địa điểm mặc định.',
            },
        }

    def validate_receiver_phone(self, value):
        value = value.strip()
        if not re.fullmatch(r'(?:\+84|0)\d{9}', value):
            raise serializers.ValidationError('Số điện thoại Việt Nam không hợp lệ.')
        return value

    def validate(self, attrs):
        if (
            self.instance
            and self.instance.is_default
            and attrs.get('is_default') is False
        ):
            raise serializers.ValidationError({
                'is_default': 'Hãy đặt một địa điểm khác làm mặc định thay vì bỏ mặc định trực tiếp.'
            })
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        customer = self.context['request'].user
        requested_default = validated_data.pop('is_default', False)
        is_first_address = not CustomerAddress.objects.select_for_update().filter(
            customer=customer,
            is_active=True,
        ).exists()
        address = CustomerAddress.objects.create(
            customer=customer,
            is_default=False,
            **validated_data,
        )
        if requested_default or is_first_address:
            set_default_address(address)
        return address

    @transaction.atomic
    def update(self, instance, validated_data):
        requested_default = validated_data.pop('is_default', None)
        for field_name, value in validated_data.items():
            if isinstance(value, str):
                value = value.strip()
            setattr(instance, field_name, value)
        instance.save()
        if requested_default is True:
            set_default_address(instance)
        return instance


class VoucherAdminSerializer(serializers.ModelSerializer):
    lifecycle_status = serializers.SerializerMethodField(
        help_text='Trạng thái suy ra: UPCOMING, ACTIVE, EXPIRED, EXHAUSTED hoặc DISABLED.'
    )
    remaining_usage = serializers.SerializerMethodField(
        help_text='Số lượt còn lại; null nghĩa là không giới hạn.'
    )

    LOCKED_AFTER_USAGE_FIELDS = {
        'code',
        'discount_type',
        'discount_value',
        'max_discount_amount',
        'min_order_amount',
        'start_at',
        'per_user_limit',
    }

    class Meta:
        model = Voucher
        fields = [
            'id',
            'code',
            'name',
            'description',
            'discount_type',
            'distribution_type',
            'discount_value',
            'max_discount_amount',
            'min_order_amount',
            'usage_limit',
            'used_count',
            'remaining_usage',
            'per_user_limit',
            'start_at',
            'end_at',
            'is_active',
            'lifecycle_status',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'used_count',
            'remaining_usage',
            'lifecycle_status',
            'created_at',
            'updated_at',
        ]
        extra_kwargs = {
            'code': {'help_text': 'Mã voucher; backend chuẩn hóa thành chữ hoa và không cho trùng.'},
            'discount_type': {'help_text': 'PERCENT hoặc FIXED.'},
            'distribution_type': {
                'help_text': (
                    'PUBLIC: hiển thị để khách hàng tự nhận; CODE_ONLY: chỉ nhận bằng mã; '
                    'ASSIGNED: chỉ admin hoặc hệ thống được cấp.'
                ),
            },
            'discount_value': {'help_text': 'Phần trăm hoặc số tiền giảm, phải lớn hơn 0.'},
            'max_discount_amount': {'help_text': 'Mức giảm tối đa cho voucher PERCENT; có thể để null.'},
            'min_order_amount': {'help_text': 'Giá trị đơn tối thiểu để sử dụng voucher.'},
            'usage_limit': {'help_text': 'Tổng lượt sử dụng; null nghĩa là không giới hạn.'},
            'per_user_limit': {'help_text': 'Số lượt tối đa cho mỗi khách hàng.'},
        }

    def get_lifecycle_status(self, instance) -> str:
        now = timezone.now()
        if not instance.is_active:
            return 'DISABLED'
        if now < instance.start_at:
            return 'UPCOMING'
        if now > instance.end_at:
            return 'EXPIRED'
        if instance.usage_limit is not None and instance.used_count >= instance.usage_limit:
            return 'EXHAUSTED'
        return 'ACTIVE'

    def get_remaining_usage(self, instance) -> int | None:
        if instance.usage_limit is None:
            return None
        return max(instance.usage_limit - instance.used_count, 0)

    def validate_code(self, value):
        value = value.strip().upper()
        queryset = Voucher.objects.filter(code__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError('Mã voucher đã tồn tại.')
        return value

    def validate_min_order_amount(self, value):
        if value < 0:
            raise serializers.ValidationError('Giá trị đơn tối thiểu không được âm.')
        return value

    def validate_usage_limit(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Tổng lượt sử dụng phải lớn hơn 0.')
        return value

    def validate_per_user_limit(self, value):
        if value <= 0:
            raise serializers.ValidationError('Giới hạn mỗi khách hàng phải lớn hơn 0.')
        return value

    def validate(self, attrs):
        discount_type = attrs.get(
            'discount_type',
            self.instance.discount_type if self.instance else None,
        )
        discount_value = attrs.get(
            'discount_value',
            self.instance.discount_value if self.instance else None,
        )
        max_discount = attrs.get(
            'max_discount_amount',
            self.instance.max_discount_amount if self.instance else None,
        )
        start_at = attrs.get('start_at', self.instance.start_at if self.instance else None)
        end_at = attrs.get('end_at', self.instance.end_at if self.instance else None)
        usage_limit = attrs.get(
            'usage_limit',
            self.instance.usage_limit if self.instance else None,
        )
        used_count = self.instance.used_count if self.instance else 0

        if discount_value is not None and discount_value <= 0:
            raise serializers.ValidationError({'discount_value': 'Giá trị giảm phải lớn hơn 0.'})
        if discount_type == Voucher.DiscountType.PERCENT and discount_value > 100:
            raise serializers.ValidationError({'discount_value': 'Mức giảm phần trăm không được vượt quá 100.'})
        if max_discount is not None and max_discount <= 0:
            raise serializers.ValidationError({'max_discount_amount': 'Mức giảm tối đa phải lớn hơn 0.'})
        if start_at and end_at and start_at >= end_at:
            raise serializers.ValidationError({'end_at': 'Thời gian kết thúc phải sau thời gian bắt đầu.'})
        if usage_limit is not None and usage_limit < used_count:
            raise serializers.ValidationError({
                'usage_limit': 'Giới hạn sử dụng không được nhỏ hơn số lượt đã dùng.'
            })

        if self.instance and (
            self.instance.used_count > 0 or self.instance.booking_vouchers.exists()
        ):
            changed_locked_fields = sorted(
                field_name
                for field_name in self.LOCKED_AFTER_USAGE_FIELDS.intersection(attrs)
                if attrs[field_name] != getattr(self.instance, field_name)
            )
            if changed_locked_fields:
                raise serializers.ValidationError({
                    'locked_fields': (
                        'Không thể sửa các field tài chính sau khi voucher đã phát sinh lượt dùng: '
                        + ', '.join(changed_locked_fields)
                        + '.'
                    )
                })
        if (
            self.instance
            and 'distribution_type' in attrs
            and attrs['distribution_type'] != self.instance.distribution_type
            and self.instance.user_vouchers.exists()
        ):
            raise serializers.ValidationError({
                'distribution_type': 'Không thể đổi loại phát hành sau khi đã có người nhận voucher.'
            })
        return attrs


class VoucherPublicSerializer(serializers.ModelSerializer):
    lifecycle_status = serializers.SerializerMethodField()
    remaining_usage = serializers.SerializerMethodField()

    class Meta:
        model = Voucher
        fields = [
            'id',
            'code',
            'name',
            'description',
            'discount_type',
            'distribution_type',
            'discount_value',
            'max_discount_amount',
            'min_order_amount',
            'remaining_usage',
            'per_user_limit',
            'start_at',
            'end_at',
            'lifecycle_status',
        ]
        read_only_fields = fields

    def get_lifecycle_status(self, instance) -> str:
        now = timezone.now()
        if not instance.is_active:
            return 'DISABLED'
        if now < instance.start_at:
            return 'UPCOMING'
        if now > instance.end_at:
            return 'EXPIRED'
        if instance.usage_limit is not None and instance.used_count >= instance.usage_limit:
            return 'EXHAUSTED'
        return 'ACTIVE'

    def get_remaining_usage(self, instance) -> int | None:
        if instance.usage_limit is None:
            return None
        return max(instance.usage_limit - instance.used_count, 0)


class UserVoucherCustomerSerializer(serializers.ModelSerializer):
    voucher = VoucherPublicSerializer(read_only=True)
    availability_status = serializers.SerializerMethodField(
        help_text='AVAILABLE, UPCOMING, EXPIRED, EXHAUSTED, DISABLED hoặc REVOKED.'
    )
    used_or_reserved_count = serializers.SerializerMethodField(
        help_text='Số lượt của khách hàng đang được giữ hoặc đã dùng.'
    )
    remaining_user_uses = serializers.SerializerMethodField(
        help_text='Số lượt khách hàng còn có thể sử dụng theo per_user_limit.'
    )

    class Meta:
        model = UserVoucher
        fields = [
            'id',
            'voucher',
            'source',
            'status',
            'availability_status',
            'used_or_reserved_count',
            'remaining_user_uses',
            'is_visible',
            'received_at',
            'revoked_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'voucher',
            'source',
            'status',
            'availability_status',
            'used_or_reserved_count',
            'remaining_user_uses',
            'received_at',
            'revoked_at',
            'created_at',
            'updated_at',
        ]
        extra_kwargs = {
            'is_visible': {
                'help_text': 'Cho phép khách hàng ẩn hoặc hiển thị lại voucher trong ví.'
            },
        }

    def _usage_count(self, instance):
        annotated_count = getattr(instance, 'customer_usage_count', None)
        if annotated_count is not None:
            return annotated_count
        from .models import BookingVoucher
        return BookingVoucher.objects.filter(
            voucher=instance.voucher,
            booking__customer=instance.user,
            status__in=[BookingVoucher.Status.RESERVED, BookingVoucher.Status.USED],
        ).count()

    def get_availability_status(self, instance) -> str:
        return get_user_voucher_availability(instance, self._usage_count(instance))

    def get_used_or_reserved_count(self, instance) -> int:
        return self._usage_count(instance)

    def get_remaining_user_uses(self, instance) -> int:
        return max(instance.voucher.per_user_limit - self._usage_count(instance), 0)

    def validate_is_visible(self, value):
        if self.instance and self.instance.status == UserVoucher.Status.REVOKED and value:
            raise serializers.ValidationError('Voucher đã bị thu hồi và không thể hiển thị lại.')
        return value

    def validate(self, attrs):
        if self.instance:
            unsupported_fields = sorted(set(self.initial_data) - {'is_visible'})
            if unsupported_fields:
                raise serializers.ValidationError({
                    'fields': 'Khách hàng chỉ được cập nhật field is_visible.'
                })
        return attrs


class VoucherClaimCodeSerializer(serializers.Serializer):
    code = serializers.CharField(
        max_length=50,
        trim_whitespace=True,
        help_text='Mã voucher PUBLIC hoặc CODE_ONLY mà khách hàng muốn nhận.',
    )


class UserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'phone_number', 'role']
        read_only_fields = fields


class UserVoucherAdminSerializer(serializers.ModelSerializer):
    user_id = serializers.PrimaryKeyRelatedField(
        source='user',
        queryset=User.objects.filter(role='CUSTOMER'),
        help_text='ID tài khoản khách hàng được cấp voucher.',
    )
    voucher_id = serializers.PrimaryKeyRelatedField(
        source='voucher',
        queryset=Voucher.objects.all(),
        help_text='ID voucher được cấp.',
    )
    user = UserSummarySerializer(read_only=True)
    voucher = VoucherPublicSerializer(read_only=True)
    availability_status = serializers.SerializerMethodField()

    class Meta:
        model = UserVoucher
        fields = [
            'id',
            'user_id',
            'user',
            'voucher_id',
            'voucher',
            'source',
            'status',
            'availability_status',
            'is_visible',
            'received_at',
            'revoked_at',
            'created_by_id',
            'admin_note',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'user',
            'voucher',
            'source',
            'availability_status',
            'is_visible',
            'received_at',
            'revoked_at',
            'created_by_id',
            'created_at',
            'updated_at',
        ]
        extra_kwargs = {
            'status': {
                'required': False,
                'help_text': 'Admin có thể chuyển AVAILABLE hoặc REVOKED.',
            },
            'admin_note': {
                'required': False,
                'allow_blank': True,
                'allow_null': True,
                'help_text': 'Ghi chú nội bộ của admin.',
            },
        }
        validators = []

    def get_fields(self):
        fields = super().get_fields()
        if self.instance:
            fields['user_id'].read_only = True
            fields['voucher_id'].read_only = True
        return fields

    def get_availability_status(self, instance) -> str:
        return get_user_voucher_availability(instance)

    def validate_status(self, value):
        if not self.instance and value == UserVoucher.Status.REVOKED:
            raise serializers.ValidationError('Không thể tạo mới voucher ở trạng thái đã thu hồi.')
        return value

    def validate(self, attrs):
        if self.instance:
            immutable_fields = sorted(
                field_name
                for field_name in {'user_id', 'voucher_id'}
                if field_name in self.initial_data
            )
            if immutable_fields:
                raise serializers.ValidationError({
                    'immutable_fields': (
                        'Không thể thay đổi sau khi cấp: ' + ', '.join(immutable_fields) + '.'
                    )
                })
        return attrs

    def create(self, validated_data):
        user = validated_data.pop('user')
        voucher = validated_data.pop('voucher')
        validated_data.pop('status', None)
        admin_note = validated_data.pop('admin_note', None)
        user_voucher, created = assign_voucher_to_user(
            user=user,
            voucher=voucher,
            admin=self.context['request'].user,
            admin_note=admin_note,
        )
        self.was_created = created
        return user_voucher

    def update(self, instance, validated_data):
        status_value = validated_data.pop('status', instance.status)
        if 'admin_note' in validated_data:
            instance.admin_note = validated_data['admin_note']
            instance.save(update_fields=['admin_note', 'updated_at'])
        if status_value == UserVoucher.Status.REVOKED:
            return revoke_user_voucher(instance)
        if instance.status == UserVoucher.Status.REVOKED:
            return restore_user_voucher(instance)
        return instance
