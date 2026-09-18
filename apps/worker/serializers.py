from rest_framework import serializers

from .models import Area, BookingAssignment, WorkerWorkingArea
from apps.bookings.models import BookingSchedule


class AreaSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Area
        fields = ['id', 'name', 'city']


class WorkerWorkingAreaSerializer(serializers.ModelSerializer):
    area = AreaSummarySerializer(read_only=True)
    area_id = serializers.PrimaryKeyRelatedField(source='area', queryset=Area.objects.filter(is_active=True), write_only=True)

    class Meta:
        model = WorkerWorkingArea
        fields = ['id', 'area', 'area_id', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        worker = self.context['request'].user
        area = attrs.get('area', getattr(self.instance, 'area', None))
        queryset = WorkerWorkingArea.objects.filter(worker=worker, area=area)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError({'area_id': 'Bạn đã chọn khu vực làm việc này.'})
        return attrs

    def create(self, validated_data):
        return WorkerWorkingArea.objects.create(worker=self.context['request'].user, **validated_data)


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
