import re
from decimal import Decimal, InvalidOperation
from django.db import transaction
from rest_framework import serializers

from .address_service import set_default_address
from .models import CustomerAddress


class CustomerAddressSerializer(serializers.ModelSerializer):
    # Khai báo ép thành CharField để DRF không chặn lỗi max_digits từ đầu
    latitude = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    longitude = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = CustomerAddress
        fields = ['id', 'label', 'receiver_name', 'receiver_phone', 'address_line', 'ward', 'city',
          'province_code', 'ward_code', 'latitude', 'longitude',
          'is_default', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_active', 'created_at', 'updated_at']
        extra_kwargs = {'is_default': {'required': False}}

    def validate_receiver_phone(self, value):
        value = value.strip()
        if not re.fullmatch(r'(?:\+84|0)\d{9}', value):
            raise serializers.ValidationError('Số điện thoại Việt Nam không hợp lệ.')
        return value

    def validate_latitude(self, value):
        if value is None or value == '':
            return None
        try:
            # Ép về Decimal và làm tròn chuẩn 7 chữ số thập phân
            return Decimal(str(value)).quantize(Decimal('0.0000001'))
        except (InvalidOperation, ValueError):
            raise serializers.ValidationError('Vĩ độ (latitude) không hợp lệ.')

    def validate_longitude(self, value):
        if value is None or value == '':
            return None
        try:
            return Decimal(str(value)).quantize(Decimal('0.0000001'))
        except (InvalidOperation, ValueError):
            raise serializers.ValidationError('Kinh độ (longitude) không hợp lệ.')

    def validate(self, attrs):
        if self.instance and self.instance.is_default and attrs.get('is_default') is False:
            raise serializers.ValidationError({'is_default': 'Hãy đặt một địa điểm khác làm mặc định thay vì bỏ mặc định trực tiếp.'})

        ward_code = (attrs.get('ward_code') or '').strip()
        if not self.instance and not ward_code:
            raise serializers.ValidationError({'ward_code': 'Vui lòng chọn phường/xã.'})
        if ward_code:
            from apps.worker.models import Area
            area = Area.objects.filter(ward_code=ward_code, is_active=True).first()
            if area is None:
                raise serializers.ValidationError({'ward_code': 'Phường/xã không hợp lệ.'})
            attrs['ward_code'] = area.ward_code
            attrs['province_code'] = area.province_code
            attrs['ward'] = area.name
            attrs['city'] = area.city
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        customer = self.context['request'].user
        requested_default = validated_data.pop('is_default', False)
        is_first = not CustomerAddress.objects.select_for_update().filter(customer=customer, is_active=True).exists()
        address = CustomerAddress.objects.create(customer=customer, is_default=False, **validated_data)
        if requested_default or is_first:
            set_default_address(address)
        return address

    LOCATION_FIELDS = ('ward_code', 'address_line', 'latitude', 'longitude')

    @transaction.atomic
    def update(self, instance, validated_data):
        requested_default = validated_data.pop('is_default', None)

        changed = [
            f for f in self.LOCATION_FIELDS
            if f in validated_data and validated_data[f] != getattr(instance, f)
        ]
        if changed:
            from django.db.models import Q
            from apps.bookings.models import Booking
            in_use = Booking.objects.filter(
                Q(address=instance) | Q(delivery_address=instance),
                status__in=(Booking.Status.PENDING, Booking.Status.ASSIGNED, Booking.Status.IN_PROGRESS),
            ).exists()
            if in_use:
                raise serializers.ValidationError(
                    'Địa chỉ đang được dùng cho đơn chưa hoàn tất, không thể đổi vị trí. '
                    'Hãy tạo địa chỉ mới.'
                )

        for field, value in validated_data.items():
            setattr(instance, field, value.strip() if isinstance(value, str) else value)
        instance.save()
        if requested_default is True:
            set_default_address(instance)
        return instance