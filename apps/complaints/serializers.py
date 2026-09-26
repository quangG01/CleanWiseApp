# apps/complaints/serializers.py

from django.utils import timezone
from rest_framework import serializers

from .models import (
    Complaint,
    ComplaintAttachment,
    ComplaintIssueType,
)


class ComplaintIssueTypeSerializer(serializers.ModelSerializer):
    stage_label = serializers.CharField(
        source='get_stage_display',
        read_only=True,
    )

    class Meta:
        model = ComplaintIssueType
        fields = [
            'id',
            'code',
            'name',
            'description',
            'stage',
            'stage_label',
            'is_active',
        ]
        read_only_fields = [
            'id',
            'stage_label',
        ]


class ComplaintAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplaintAttachment
        fields = ['id', 'file', 'file_type', 'created_at']
        read_only_fields = ['id', 'file_type', 'created_at']

    def validate_file(self, value):
        allowed = ('image/jpeg', 'image/png', 'image/webp')
        if value.content_type not in allowed:
            raise serializers.ValidationError('Chỉ chấp nhận file ảnh (jpeg/png/webp).')
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError('Ảnh tối đa 5MB.')
        return value


class ComplaintCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Complaint
        fields = ['id', 'booking', 'schedule', 'issue_type', 'content']
        read_only_fields = ['id']

    def validate_booking(self, booking):
        request = self.context['request']
        if booking.customer_id != request.user.id:
            raise serializers.ValidationError('Booking không thuộc về bạn.')
        if booking.status in [booking.Status.CANCELLED, booking.Status.FAILED]:
            raise serializers.ValidationError(
                'Không thể tạo khiếu nại cho booking đã bị hủy hoặc thất bại.'
            )
        return booking

    def validate_issue_type(self, issue_type):
        if not issue_type.is_active:
            raise serializers.ValidationError('Loại sự cố này hiện không còn được sử dụng.')
        return issue_type

    def validate(self, attrs):
        booking = attrs['booking']
        schedule = attrs.get('schedule')
        issue_type = attrs['issue_type']

        if schedule and schedule.booking_id != booking.id:
            raise serializers.ValidationError({'schedule': 'Buổi làm việc không khớp với booking.'})

        stage = self._get_booking_stage(booking)

        if issue_type.stage != ComplaintIssueType.Stage.ANY and issue_type.stage != stage:
            raise serializers.ValidationError({
                'issue_type': 'Loại sự cố này không phù hợp với trạng thái hiện tại của booking.'
            })

        # Chỉ 1 khiếu nại / buổi schedule (khiếu nại đã hủy thì cho gửi lại)
        if schedule:
            existing = Complaint.objects.filter(schedule=schedule).exclude(
                status=Complaint.Status.CANCELLED,
            ).exists()
            if existing:
                raise serializers.ValidationError({
                    'schedule': 'Buổi làm việc này đã có khiếu nại.'
                })

        return attrs

    @staticmethod
    def _get_booking_stage(booking):
        if booking.status in [booking.Status.PENDING, booking.Status.ASSIGNED]:
            return Complaint.Stage.BEFORE_SERVICE
        if booking.status == booking.Status.IN_PROGRESS:
            return Complaint.Stage.IN_SERVICE
        if booking.status == booking.Status.COMPLETED:
            return Complaint.Stage.AFTER_SERVICE
        raise serializers.ValidationError('Booking hiện tại không cho phép tạo khiếu nại.')

    def create(self, validated_data):
        request = self.context['request']
        booking = validated_data['booking']
        stage = self._get_booking_stage(booking)
        return Complaint.objects.create(customer=request.user, stage=stage, **validated_data)


class ComplaintListSerializer(serializers.ModelSerializer):
    issue_type_name = serializers.CharField(
        source='issue_type.name',
        read_only=True,
    )

    issue_type_code = serializers.CharField(
        source='issue_type.code',
        read_only=True,
    )

    stage_label = serializers.CharField(
        source='get_stage_display',
        read_only=True,
    )

    status_label = serializers.CharField(
        source='get_status_display',
        read_only=True,
    )

    class Meta:
        model = Complaint
        fields = [
            'id',
            'booking',
            'issue_type',
            'issue_type_code',
            'issue_type_name',
            'stage',
            'stage_label',
            'status',
            'status_label',
            'created_at',
        ]


class ComplaintDetailSerializer(serializers.ModelSerializer):
    attachments = ComplaintAttachmentSerializer(
        many=True,
        read_only=True,
    )

    customer_name = serializers.CharField(
        source='customer.get_full_name',
        read_only=True,
    )

    resolved_by_name = serializers.CharField(
        source='resolved_by.get_full_name',
        read_only=True,
    )

    issue_type_name = serializers.CharField(
        source='issue_type.name',
        read_only=True,
    )

    issue_type_code = serializers.CharField(
        source='issue_type.code',
        read_only=True,
    )

    stage_label = serializers.CharField(
        source='get_stage_display',
        read_only=True,
    )

    status_label = serializers.CharField(
        source='get_status_display',
        read_only=True,
    )

    class Meta:
        model = Complaint
        fields = [
            'id',
            'customer',
            'customer_name',
            'booking',

            'issue_type',
            'issue_type_code',
            'issue_type_name',

            'stage',
            'stage_label',

            'content',

            'status',
            'status_label',

            'resolved_by',
            'resolved_by_name',
            'resolution_note',
            'resolved_at',

            'created_at',
            'attachments',
        ]

        read_only_fields = fields


class ComplaintResolveSerializer(serializers.ModelSerializer):
    class Meta:
        model = Complaint
        fields = [
            'status',
            'resolution_note',
        ]

    def validate_status(self, value):
        allowed = {
            Complaint.Status.IN_REVIEW,
            Complaint.Status.RESOLVED,
            Complaint.Status.REJECTED,
        }

        if value not in allowed:
            raise serializers.ValidationError(
                'Trạng thái không hợp lệ cho hành động xử lý.'
            )

        return value

    def update(self, instance, validated_data):
        instance.status = validated_data['status']

        instance.resolution_note = validated_data.get(
            'resolution_note',
            instance.resolution_note,
        )

        if instance.status in [
            Complaint.Status.RESOLVED,
            Complaint.Status.REJECTED,
        ]:
            instance.resolved_by = self.context['request'].user
            instance.resolved_at = timezone.now()

        elif instance.status == Complaint.Status.IN_REVIEW:
            instance.resolved_by = None
            instance.resolved_at = None

        instance.save()

        return instance


class ComplaintCancelSerializer(serializers.Serializer):
    def save(self):
        complaint = self.context['complaint']

        complaint.status = Complaint.Status.CANCELLED

        complaint.save(
            update_fields=['status'],
        )

        return complaint