import re
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .address_service import set_default_address
from .models import Area, CustomerAddress, UserVoucher, Voucher


class AreaSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Area
        fields = ['id', 'name', 'city']


class CustomerAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAddress
        fields = [
            'id', 'label', 'receiver_name', 'receiver_phone',
            'address_line', 'ward', 'city', 'latitude', 'longitude',
            'is_default', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'is_active', 'created_at', 'updated_at']
        extra_kwargs = {'is_default': {'required': False}}

    def validate_receiver_phone(self, value):
        value = value.strip()
        if not re.fullmatch(r'(?:\+84|0)\d{9}', value):
            raise serializers.ValidationError('Số điện thoại Việt Nam không hợp lệ.')
        return value

    def validate(self, attrs):
        if self.instance and self.instance.is_default and attrs.get('is_default') is False:
            raise serializers.ValidationError({
                'is_default': 'Hãy đặt một địa điểm khác làm mặc định thay vì bỏ mặc định trực tiếp.',
            })
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        customer = self.context['request'].user
        requested_default = validated_data.pop('is_default', False)
        is_first = not CustomerAddress.objects.select_for_update().filter(
            customer=customer,
            is_active=True,
        ).exists()
        address = CustomerAddress.objects.create(
            customer=customer,
            is_default=False,
            **validated_data,
        )
        if requested_default or is_first:
            set_default_address(address)
        return address

    @transaction.atomic
    def update(self, instance, validated_data):
        requested_default = validated_data.pop('is_default', None)
        for field, value in validated_data.items():
            setattr(instance, field, value.strip() if isinstance(value, str) else value)
        instance.save()
        if requested_default is True:
            set_default_address(instance)
        return instance


class VoucherAdminValidationMixin:
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

    def validate_issuance_limit(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Số voucher phát hành phải lớn hơn 0.')
        return value

    def validate(self, attrs):
        discount_type = attrs.get('discount_type', getattr(self.instance, 'discount_type', None))
        discount_value = attrs.get('discount_value', getattr(self.instance, 'discount_value', None))
        max_discount = attrs.get('max_discount_amount', getattr(self.instance, 'max_discount_amount', None))
        start_at = attrs.get('start_at', getattr(self.instance, 'start_at', None))
        end_at = attrs.get('end_at', getattr(self.instance, 'end_at', None))
        issuance_limit = attrs.get('issuance_limit', getattr(self.instance, 'issuance_limit', None))
        issued_count = self.instance.issued_count if self.instance else 0
        if discount_value is not None and discount_value <= 0:
            raise serializers.ValidationError({'discount_value': 'Giá trị giảm phải lớn hơn 0.'})
        if discount_type == Voucher.DiscountType.PERCENT and discount_value > 100:
            raise serializers.ValidationError({'discount_value': 'Mức giảm phần trăm không được vượt quá 100.'})
        if max_discount is not None and max_discount <= 0:
            raise serializers.ValidationError({'max_discount_amount': 'Mức giảm tối đa phải lớn hơn 0.'})
        if discount_type == Voucher.DiscountType.FIXED and max_discount is not None:
            raise serializers.ValidationError({
                'max_discount_amount': 'Chỉ voucher giảm theo phần trăm mới dùng mức giảm tối đa.'
            })
        if start_at and end_at and start_at >= end_at:
            raise serializers.ValidationError({'end_at': 'Thời gian kết thúc phải sau thời gian bắt đầu.'})
        if issuance_limit is not None and issuance_limit < issued_count:
            raise serializers.ValidationError({
                'issuance_limit': 'Giới hạn phát hành không được nhỏ hơn số voucher đã phát.'
            })
        return attrs


class VoucherAdminWriteSerializer(VoucherAdminValidationMixin, serializers.ModelSerializer):
    code = serializers.CharField(
        max_length=50,
        help_text='Mã duy nhất của voucher. Backend tự xóa khoảng trắng hai đầu và chuyển thành chữ in hoa.',
    )
    name = serializers.CharField(max_length=150, help_text='Tên voucher hiển thị cho người dùng.')
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text='Mô tả điều kiện hoặc nội dung chương trình.',
    )
    distribution_type = serializers.ChoiceField(
        choices=Voucher.DistributionType.choices,
        default=Voucher.DistributionType.CODE_ONLY,
        help_text='PUBLIC: người dùng tự nhận; CODE_ONLY: nhận bằng mã; ASSIGNED: admin cấp riêng.',
    )
    discount_type = serializers.ChoiceField(
        choices=Voucher.DiscountType.choices,
        help_text='PERCENT: giảm theo phần trăm; FIXED: giảm số tiền cố định.',
    )
    discount_value = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01'),
        help_text='Phần trăm giảm (1-100) hoặc số tiền giảm, tùy discount_type.',
    )
    max_discount_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal('0.01'),
        help_text='Mức giảm tiền tối đa; chỉ dùng với discount_type=PERCENT. Null nghĩa là không giới hạn.',
    )
    min_order_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        default=0,
        min_value=0,
        help_text='Giá trị đơn tối thiểu để áp dụng voucher.',
    )
    issuance_limit = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text='Tổng số voucher có thể phát hành. Null nghĩa là không giới hạn.',
    )
    start_at = serializers.DateTimeField(help_text='Thời điểm bắt đầu hiệu lực, theo định dạng ISO 8601.')
    end_at = serializers.DateTimeField(help_text='Thời điểm hết hiệu lực, phải sau start_at.')
    is_active = serializers.BooleanField(
        required=False,
        default=True,
        help_text='Cho phép voucher hoạt động. Mặc định là true.',
    )

    class Meta:
        model = Voucher
        fields = [
            'code', 'name', 'description', 'distribution_type',
            'discount_type', 'discount_value', 'max_discount_amount',
            'min_order_amount', 'issuance_limit', 'start_at', 'end_at',
            'is_active',
        ]


class VoucherAdminSerializer(serializers.ModelSerializer):
    lifecycle_status = serializers.SerializerMethodField()
    remaining_issuance = serializers.SerializerMethodField()

    class Meta:
        model = Voucher
        fields = [
            'id', 'code', 'name', 'description', 'distribution_type',
            'discount_type', 'discount_value', 'max_discount_amount',
            'min_order_amount', 'issuance_limit', 'issued_count',
            'remaining_issuance', 'start_at', 'end_at', 'is_active',
            'lifecycle_status', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'issued_count', 'remaining_issuance', 'lifecycle_status',
            'created_at', 'updated_at',
        ]

    def get_lifecycle_status(self, instance) -> str:
        now = timezone.now()
        if not instance.is_active:
            return 'DISABLED'
        if now < instance.start_at:
            return 'UPCOMING'
        if now > instance.end_at:
            return 'EXPIRED'
        if instance.issuance_limit is not None and instance.issued_count >= instance.issuance_limit:
            return 'EXHAUSTED'
        return 'ACTIVE'

    def get_remaining_issuance(self, instance) -> int | None:
        if instance.issuance_limit is None:
            return None
        return max(instance.issuance_limit - instance.issued_count, 0)

class VoucherPublicSerializer(serializers.ModelSerializer):
    lifecycle_status = serializers.SerializerMethodField()
    remaining_issuance = serializers.SerializerMethodField()

    class Meta:
        model = Voucher
        fields = [
            'id', 'code', 'name', 'description', 'distribution_type',
            'discount_type', 'discount_value', 'max_discount_amount',
            'min_order_amount', 'remaining_issuance', 'start_at', 'end_at',
            'lifecycle_status',
        ]
        read_only_fields = fields

    def get_lifecycle_status(self, instance) -> str:
        return VoucherAdminSerializer().get_lifecycle_status(instance)

    def get_remaining_issuance(self, instance) -> int | None:
        return VoucherAdminSerializer().get_remaining_issuance(instance)


class VoucherCodeClaimSerializer(serializers.Serializer):
    code = serializers.CharField(
        max_length=50,
        trim_whitespace=True,
        help_text='Mã của voucher PUBLIC hoặc CODE_ONLY cần nhận.',
    )

    def validate_code(self, value):
        return value.upper()


class UserVoucherSerializer(serializers.ModelSerializer):
    voucher = VoucherPublicSerializer(read_only=True)
    is_usable = serializers.SerializerMethodField(
        help_text='True khi voucher đang ở trạng thái AVAILABLE và còn trong thời gian hiệu lực.',
    )

    class Meta:
        model = UserVoucher
        fields = ['id', 'voucher', 'source', 'status', 'is_usable', 'created_at']
        read_only_fields = fields

    def get_is_usable(self, instance) -> bool:
        now = timezone.now()
        voucher = instance.voucher
        return bool(
            instance.status == UserVoucher.Status.AVAILABLE
            and voucher.is_active
            and voucher.start_at <= now <= voucher.end_at
        )


class VoucherValidationSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=50, trim_whitespace=True)
    subtotal_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
    )

    def validate_code(self, value):
        return value.upper()
