from django.db import transaction
from rest_framework import serializers

from .models import Area, BookingAssignment, WorkerWorkingArea
from apps.bookings.models import BookingSchedule


class AreaSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Area
        fields = ['id', 'name', 'city']


class WorkerWorkingAreaSerializer(serializers.ModelSerializer):
    """Chỉ dùng để serialize output (GET, và trả về sau khi PUT)."""
    area = AreaSummarySerializer(read_only=True)

    class Meta:
        model = WorkerWorkingArea
        fields = ['id', 'area', 'created_at']
        read_only_fields = fields


class WorkerWorkingAreaBulkUpdateSerializer(serializers.Serializer):
    area_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Area.objects.filter(is_active=True),
        allow_empty=False,
        error_messages={
            'empty': 'Phải chọn ít nhất một khu vực hoạt động.',
            'does_not_exist': 'Khu vực với id={pk_value} không tồn tại hoặc không còn hoạt động.',
        },
    )

    def validate_area_ids(self, value):
        ids = [area.id for area in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError('Danh sách khu vực bị trùng lặp.')
        return value

    def save(self):
        worker = self.context['request'].user
        areas = self.validated_data['area_ids']
        area_ids = [area.id for area in areas]

        with transaction.atomic():
            WorkerWorkingArea.objects.filter(worker=worker).exclude(area_id__in=area_ids).delete()

            existing_ids = set(
                WorkerWorkingArea.objects.filter(worker=worker, area_id__in=area_ids)
                .values_list('area_id', flat=True)
            )
            to_create = [
                WorkerWorkingArea(worker=worker, area_id=aid)
                for aid in area_ids
                if aid not in existing_ids
            ]
            if to_create:
                WorkerWorkingArea.objects.bulk_create(to_create)

        return WorkerWorkingArea.objects.filter(worker=worker).select_related('area').order_by('area__city', 'area__name')


class WorkerScheduleSerializer(serializers.ModelSerializer):
    booking_code = serializers.CharField(source='booking.booking_code', read_only=True)
    service_name = serializers.CharField(source='booking.service.name', read_only=True)
    address_city = serializers.CharField(source='booking.address.city', read_only=True)
    address_ward = serializers.CharField(source='booking.address.ward', read_only=True)
    assignment_id = serializers.SerializerMethodField()

    class Meta:
        model = BookingSchedule
        fields = ['id', 'booking_code', 'service_name', 'sequence_no', 'scheduled_start', 'scheduled_end', 'status', 'address_city', 'address_ward', 'assignment_id']

    def get_assignment_id(self, instance):
        assignment = next((a for a in instance.assignments.all() if a.status == BookingAssignment.Status.ACCEPTED), None)
        return assignment.id if assignment else None


class CancelAssignmentSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class AdminAssignWorkerSerializer(serializers.Serializer):
    worker_id = serializers.IntegerField()
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)