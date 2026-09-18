# Booking serializers.
from rest_framework import serializers

from .booking_service import create_booking
from .models import Booking, BookingSchedule


class BookingScheduleInputSerializer(serializers.Serializer):
    scheduled_start = serializers.DateTimeField()
    scheduled_end = serializers.DateTimeField()


class BookingScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingSchedule
        fields = [
            'id', 'sequence_no', 'scheduled_start', 'scheduled_end',
            'actual_start', 'actual_end', 'status', 'note',
        ]


class BookingListSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_code', 'service_name', 'status',
            'payment_status', 'subtotal_amount', 'discount_amount', 'total_amount',
            'created_at',
        ]


class BookingDetailSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    form_schema = serializers.JSONField(source='service.form_schema', read_only=True)
    pricing_config = serializers.JSONField(source='service.pricing_config', read_only=True)
    schedules = BookingScheduleSerializer(many=True, read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_code', 'service_name', 'form_schema', 'pricing_config',
            'service_data', 'address', 'note', 'status',
            'payment_status', 'price_breakdown', 'subtotal_amount', 'discount_amount',
            'total_amount', 'schedules', 'created_at', 'updated_at',
        ]


class BookingCreateSerializer(serializers.Serializer):
    service_id = serializers.IntegerField()
    address_id = serializers.IntegerField()
    service_data = serializers.JSONField()
    schedules = BookingScheduleInputSerializer(many=True)
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    voucher_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def create(self, validated_data):
        return create_booking(
            customer=self.context['request'].user,
            service_id=validated_data['service_id'],
            address_id=validated_data['address_id'],
            service_data=validated_data['service_data'],
            schedules=validated_data['schedules'],
            note=validated_data.get('note') or None,
            voucher_code=(validated_data.get('voucher_code') or '').strip() or None,
        )