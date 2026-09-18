import re

from django.db import transaction
from rest_framework import serializers

from .address_service import set_default_address
from .models import CustomerAddress


class CustomerAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAddress
        fields = ['id', 'label', 'receiver_name', 'receiver_phone', 'address_line', 'ward', 'city', 'latitude', 'longitude', 'is_default', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_active', 'created_at', 'updated_at']
        extra_kwargs = {'is_default': {'required': False}}

    def validate_receiver_phone(self, value):
        value = value.strip()
        if not re.fullmatch(r'(?:\+84|0)\d{9}', value):
            raise serializers.ValidationError('Số điện thoại Việt Nam không hợp lệ.')
        return value

    def validate(self, attrs):
        if self.instance and self.instance.is_default and attrs.get('is_default') is False:
            raise serializers.ValidationError({'is_default': 'Hãy đặt một địa điểm khác làm mặc định thay vì bỏ mặc định trực tiếp.'})
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

    @transaction.atomic
    def update(self, instance, validated_data):
        requested_default = validated_data.pop('is_default', None)
        for field, value in validated_data.items():
            setattr(instance, field, value.strip() if isinstance(value, str) else value)
        instance.save()
        if requested_default is True:
            set_default_address(instance)
        return instance
