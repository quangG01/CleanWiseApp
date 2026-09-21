from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from .models import UserVoucher, Voucher


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
            raise serializers.ValidationError({'max_discount_amount': 'Chỉ voucher giảm theo phần trăm mới dùng mức giảm tối đa.'})
        if start_at and end_at and start_at >= end_at:
            raise serializers.ValidationError({'end_at': 'Thời gian kết thúc phải sau thời gian bắt đầu.'})
        if issuance_limit is not None and issuance_limit < issued_count:
            raise serializers.ValidationError({'issuance_limit': 'Giới hạn phát hành không được nhỏ hơn số voucher đã phát.'})
        return attrs


class VoucherAdminWriteSerializer(VoucherAdminValidationMixin, serializers.ModelSerializer):
    code = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    distribution_type = serializers.ChoiceField(choices=Voucher.DistributionType.choices, default=Voucher.DistributionType.CODE_ONLY)
    discount_type = serializers.ChoiceField(choices=Voucher.DiscountType.choices)
    discount_value = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    max_discount_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True, min_value=Decimal('0.01'))
    min_order_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0, min_value=0)
    issuance_limit = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    start_at = serializers.DateTimeField()
    end_at = serializers.DateTimeField()
    is_active = serializers.BooleanField(required=False, default=True)

    class Meta:
        model = Voucher
        fields = ['code', 'name', 'description', 'distribution_type', 'discount_type', 'discount_value', 'max_discount_amount', 'min_order_amount', 'issuance_limit', 'start_at', 'end_at', 'is_active']


class VoucherAdminAssignSerializer(serializers.Serializer):
    voucher_id = serializers.IntegerField(min_value=1)
    customer_id = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=1000)


class VoucherAdminSerializer(serializers.ModelSerializer):
    lifecycle_status = serializers.SerializerMethodField()
    remaining_issuance = serializers.SerializerMethodField()

    class Meta:
        model = Voucher
        fields = ['id', 'code', 'name', 'description', 'distribution_type', 'discount_type', 'discount_value', 'max_discount_amount', 'min_order_amount', 'issuance_limit', 'issued_count', 'remaining_issuance', 'start_at', 'end_at', 'is_active', 'lifecycle_status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'issued_count', 'remaining_issuance', 'lifecycle_status', 'created_at', 'updated_at']

    def get_lifecycle_status(self, instance):
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

    def get_remaining_issuance(self, instance):
        if instance.issuance_limit is None:
            return None
        return max(instance.issuance_limit - instance.issued_count, 0)


class VoucherPublicSerializer(serializers.ModelSerializer):
    lifecycle_status = serializers.SerializerMethodField()
    remaining_issuance = serializers.SerializerMethodField()

    class Meta:
        model = Voucher
        fields = ['id', 'code', 'name', 'description', 'distribution_type', 'discount_type', 'discount_value', 'max_discount_amount', 'min_order_amount', 'remaining_issuance', 'start_at', 'end_at', 'lifecycle_status']
        read_only_fields = fields

    def get_lifecycle_status(self, instance):
        return VoucherAdminSerializer().get_lifecycle_status(instance)

    def get_remaining_issuance(self, instance):
        return VoucherAdminSerializer().get_remaining_issuance(instance)


class VoucherCodeClaimSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=50, trim_whitespace=True)

    def validate_code(self, value):
        return value.upper()


class UserVoucherSerializer(serializers.ModelSerializer):
    voucher = VoucherPublicSerializer(read_only=True)
    is_usable = serializers.SerializerMethodField()

    class Meta:
        model = UserVoucher
        fields = ['id', 'voucher', 'source', 'status', 'is_usable', 'created_at']
        read_only_fields = fields

    def get_is_usable(self, instance):
        now = timezone.now()
        voucher = instance.voucher
        return bool(instance.status == UserVoucher.Status.AVAILABLE and voucher.is_active and voucher.start_at <= now <= voucher.end_at)


class AdminAssignedUserVoucherSerializer(serializers.ModelSerializer):
    voucher_id = serializers.IntegerField(read_only=True)
    customer_id = serializers.IntegerField(source='user_id', read_only=True)
    assigned_by = serializers.IntegerField(source='assigned_by_id', read_only=True, allow_null=True)

    class Meta:
        model = UserVoucher
        fields = [
            'id',
            'voucher_id',
            'customer_id',
            'source',
            'status',
            'assigned_by',
            'note',
            'created_at',
        ]
        read_only_fields = fields


class VoucherValidationSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=50, trim_whitespace=True)
    subtotal_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)

    def validate_code(self, value):
        return value.upper()
