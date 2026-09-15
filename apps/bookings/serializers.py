import re

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .address_service import set_default_address
from .models import Area, CustomerAddress, Voucher


class AreaSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Area
        fields = ['id', 'name', 'district', 'city']


class CustomerAddressSerializer(serializers.ModelSerializer):
    area = AreaSummarySerializer(read_only=True)
    area_id = serializers.PrimaryKeyRelatedField(
        source='area',
        queryset=Area.objects.filter(is_active=True),
        write_only=True,
    )

    class Meta:
        model = CustomerAddress
        fields = [
            'id', 'area', 'area_id', 'label', 'receiver_name', 'receiver_phone',
            'address_line', 'ward', 'district', 'city', 'latitude', 'longitude',
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
        area = attrs.get('area', self.instance.area if self.instance else None)
        district = attrs.get('district', self.instance.district if self.instance else None)
        city = attrs.get('city', self.instance.city if self.instance else None)
        if area and (area.district != district or area.city != city):
            raise serializers.ValidationError({
                'area_id': 'Khu vực phải thuộc đúng quận/huyện và tỉnh/thành phố của địa chỉ.',
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


class VoucherAdminSerializer(serializers.ModelSerializer):
    lifecycle_status = serializers.SerializerMethodField()
    remaining_usage = serializers.SerializerMethodField()

    class Meta:
        model = Voucher
        fields = [
            'id', 'code', 'name', 'description', 'discount_type', 'discount_value',
            'max_discount_amount', 'min_order_amount', 'usage_limit', 'used_count',
            'remaining_usage', 'per_user_limit', 'start_at', 'end_at', 'is_active',
            'lifecycle_status', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'used_count', 'remaining_usage', 'lifecycle_status',
            'created_at', 'updated_at',
        ]

    def get_lifecycle_status(self, instance):
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

    def get_remaining_usage(self, instance):
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

    def validate(self, attrs):
        discount_type = attrs.get('discount_type', getattr(self.instance, 'discount_type', None))
        discount_value = attrs.get('discount_value', getattr(self.instance, 'discount_value', None))
        max_discount = attrs.get('max_discount_amount', getattr(self.instance, 'max_discount_amount', None))
        start_at = attrs.get('start_at', getattr(self.instance, 'start_at', None))
        end_at = attrs.get('end_at', getattr(self.instance, 'end_at', None))
        usage_limit = attrs.get('usage_limit', getattr(self.instance, 'usage_limit', None))
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
            raise serializers.ValidationError({'usage_limit': 'Giới hạn sử dụng không được nhỏ hơn số lượt đã dùng.'})
        return attrs


class VoucherPublicSerializer(VoucherAdminSerializer):
    class Meta(VoucherAdminSerializer.Meta):
        read_only_fields = VoucherAdminSerializer.Meta.fields
