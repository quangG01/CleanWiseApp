from rest_framework import serializers

from .models import BookingAssignment, BookingSchedule


class WorkerScheduleSerializer(serializers.ModelSerializer):
    booking_code = serializers.CharField(source='booking.booking_code', read_only=True)
    service_name = serializers.CharField(source='booking.service.name', read_only=True)
    address_city = serializers.CharField(source='booking.address.city', read_only=True)
    address_ward = serializers.CharField(source='booking.address.ward', read_only=True)
    assignment_id = serializers.SerializerMethodField()

    class Meta:
        model = BookingSchedule
        fields = [
            'id', 'booking_code', 'service_name', 'sequence_no',
            'scheduled_start', 'scheduled_end', 'status',
            'address_city', 'address_ward', 'assignment_id',
        ]

    def get_assignment_id(self, instance):
        assignment = next(
            (a for a in instance.assignments.all() if a.status == BookingAssignment.Status.ACCEPTED),
            None,
        )
        return assignment.id if assignment else None


class CancelAssignmentSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class AdminAssignWorkerSerializer(serializers.Serializer):
    worker_id = serializers.IntegerField()
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)