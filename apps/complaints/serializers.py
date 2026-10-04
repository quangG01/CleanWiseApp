# apps/complaints/serializers.py

from django.utils import timezone
from rest_framework import serializers

from apps.bookings.activity_service import record_booking_activity
from apps.bookings.models import BookingActivity
from apps.common.permissions import get_user_role
from apps.worker.models import BookingAssignment

from .models import (
    Complaint,
    ComplaintAttachment,
    ComplaintIssueType,
)

from django.db import transaction


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
            'applies_to',
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
        role = get_user_role(request.user)

        if role == 'CUSTOMER':
            if booking.customer_id != request.user.id:
                raise serializers.ValidationError('Booking không thuộc về bạn.')
        elif role == 'WORKER':
            has_assignment = BookingAssignment.objects.filter(
                schedule__booking=booking,
                worker=request.user,
                status=BookingAssignment.Status.ACCEPTED,
            ).exists()
            if not has_assignment:
                raise serializers.ValidationError(
                    'Bạn chưa từng nhận buổi làm nào thuộc đơn này.'
                )
        else:
            raise serializers.ValidationError('Vai trò của bạn không được phép tạo khiếu nại.')

        if booking.status in [booking.Status.CANCELLED, booking.Status.FAILED]:
            raise serializers.ValidationError(
                'Không thể tạo khiếu nại cho booking đã bị hủy hoặc thất bại.'
            )
        return booking

    def validate_issue_type(self, issue_type):
        if not issue_type.is_active:
            raise serializers.ValidationError('Loại sự cố này hiện không còn được sử dụng.')

        role = get_user_role(self.context['request'].user)
        if issue_type.applies_to not in (role, ComplaintIssueType.AppliesTo.ANY):
            raise serializers.ValidationError(
                'Loại sự cố này không áp dụng cho vai trò của bạn.'
            )
        return issue_type

    def validate(self, attrs):
        request = self.context['request']
        booking = attrs['booking']
        schedule = attrs.get('schedule')
        issue_type = attrs['issue_type']

        if schedule and schedule.booking_id != booking.id:
            raise serializers.ValidationError({'schedule': 'Buổi làm việc không khớp với booking.'})

        # Nhân viên bắt buộc gắn đúng buổi mình đã nhận, để suy ra `worker`
        # chính xác và tránh khiếu nại chung chung không rõ buổi nào.
        role = get_user_role(request.user)
        if role == 'WORKER':
            if not schedule:
                raise serializers.ValidationError({'schedule': 'Vui lòng chọn buổi làm việc cụ thể.'})
            owns_schedule = BookingAssignment.objects.filter(
                schedule=schedule, worker=request.user,
                status=BookingAssignment.Status.ACCEPTED,
            ).exists()
            if not owns_schedule:
                raise serializers.ValidationError({'schedule': 'Buổi làm việc này không thuộc về bạn.'})

        stage = self._get_booking_stage(booking)

        if issue_type.stage != ComplaintIssueType.Stage.ANY and issue_type.stage != stage:
            raise serializers.ValidationError({
                'issue_type': 'Loại sự cố này không phù hợp với trạng thái hiện tại của booking.'
            })

        # ĐỔI: khóa schedule trước khi check tồn tại complaint, để 2
        # request tạo complaint cùng lúc cho cùng 1 schedule bị serialize
        # (request sau phải chờ request trước commit/rollback xong mới
        # được đọc), tránh cả 2 cùng pass check rồi cùng tạo trùng.
        # select_for_update() bắt buộc phải chạy trong transaction, nên
        # bọc luôn create() (được ComplaintListCreateView gọi ngay sau
        # is_valid()) vào atomic ở view.
        if schedule:
            from apps.bookings.models import BookingSchedule
            BookingSchedule.objects.select_for_update(of=('self',)).get(pk=schedule.pk)

            # Khoá theo (schedule, reporter): khách và nhân viên của cùng
            # 1 buổi có thể cùng khiếu nại (2 góc nhìn khác nhau), chỉ
            # chặn trùng khi CHÍNH người này đã khiếu nại buổi đó rồi.
            existing = Complaint.objects.filter(
                schedule=schedule, reporter=request.user,
            ).exclude(status=Complaint.Status.CANCELLED).exists()
            if existing:
                raise serializers.ValidationError({
                    'schedule': 'Bạn đã tạo khiếu nại cho buổi làm việc này rồi.'
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

    def _infer_worker(self, *, role, user, schedule):
        if role == 'WORKER':
            return user
        if schedule:
            assignment = BookingAssignment.objects.filter(
                schedule=schedule, status=BookingAssignment.Status.ACCEPTED,
            ).select_related('worker').first()
            if assignment:
                return assignment.worker
        return None

    def create(self, validated_data):
        request = self.context['request']
        role = get_user_role(request.user)
        booking = validated_data['booking']
        schedule = validated_data.get('schedule')
        stage = self._get_booking_stage(booking)
        worker = self._infer_worker(role=role, user=request.user, schedule=schedule)

        complaint = Complaint.objects.create(
            reporter=request.user,
            reporter_role=role,
            worker=worker,
            stage=stage,
            **validated_data,
        )
        record_booking_activity(
            booking=booking,
            schedule=complaint.schedule,
            actor=request.user,
            event_type=BookingActivity.EventType.COMPLAINT_CREATED,
            message=f'{"Nhân viên" if role == "WORKER" else "Khách hàng"} tạo khiếu nại #{complaint.id}.',
            new_data={'complaint_id': complaint.id, 'stage': complaint.stage},
        )
        return complaint


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
    
    reporter_name = serializers.CharField(
        source='reporter.get_full_name', read_only=True,
    )
    worker_name = serializers.CharField(
        source='worker.get_full_name', read_only=True, default=None,
    )

    class Meta:
        model = Complaint
        fields = [
            'id',
            'booking',
            'reporter_role',
            'issue_type',
            'issue_type_code',
            'issue_type_name',
            'stage',
            'stage_label',
            'status',
            'reporter_name', 'worker', 'worker_name',
            'status_label',
            'created_at',
        ]


class ComplaintDetailSerializer(serializers.ModelSerializer):
    attachments = ComplaintAttachmentSerializer(
        many=True,
        read_only=True,
    )

    reporter_name = serializers.CharField(
        source='reporter.get_full_name',
        read_only=True,
    )

    worker_name = serializers.CharField(
        source='worker.get_full_name',
        read_only=True,
        default=None,
    )

    resolved_by_name = serializers.CharField(
        source='resolved_by.get_full_name',
        read_only=True,
        default=None,
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
            'reporter',
            'reporter_role',
            'reporter_name',
            'worker',
            'worker_name',
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
            'refund_amount',
            'created_at',
            'attachments',
        ]

        read_only_fields = fields


class ComplaintResolveSerializer(serializers.ModelSerializer):
    refund_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=1, required=False,
    )

    class Meta:
        model = Complaint
        fields = ['status', 'resolution_note', 'refund_amount']

    def validate_status(self, value):
        allowed = {Complaint.Status.IN_REVIEW, Complaint.Status.RESOLVED, Complaint.Status.REJECTED}
        if value not in allowed:
            raise serializers.ValidationError('Trạng thái không hợp lệ cho hành động xử lý.')
        return value

    def validate(self, attrs):
        if self.instance.status in (
            Complaint.Status.RESOLVED, Complaint.Status.REJECTED, Complaint.Status.CANCELLED,
        ):
            raise serializers.ValidationError('Khiếu nại đã đóng, không thể xử lý lại.')
        if attrs.get('refund_amount') and attrs['status'] != Complaint.Status.RESOLVED:
            raise serializers.ValidationError({'refund_amount': 'Chỉ hoàn tiền khi trạng thái là RESOLVED.'})
        # Hoàn tiền chỉ có ý nghĩa khi người khiếu nại là khách (tiền của
        # khách); khiếu nại do nhân viên gửi không có đối tượng để hoàn.
        if attrs.get('refund_amount') and self.instance.reporter_role != Complaint.ReporterRole.CUSTOMER:
            raise serializers.ValidationError({'refund_amount': 'Chỉ hoàn tiền cho khiếu nại của khách hàng.'})
        return attrs

    def update(self, instance, validated_data):
        request = self.context['request']
        instance.status = validated_data['status']
        instance.resolution_note = validated_data.get('resolution_note', instance.resolution_note)

        if instance.status in (Complaint.Status.RESOLVED, Complaint.Status.REJECTED):
            instance.resolved_by = request.user
            instance.resolved_at = timezone.now()
        else:
            instance.resolved_by = None
            instance.resolved_at = None

        amount = validated_data.get('refund_amount')
        if instance.status == Complaint.Status.RESOLVED and amount:
            from apps.wallets import refund_service
            _, refunded = refund_service.admin_refund_booking(
                booking_id=instance.booking_id,
                admin_user=request.user,
                reason=f'Khiếu nại #{instance.id}',
                amount=amount,
                key=f'refund:complaint:{instance.id}',
            )
            instance.refund_amount = refunded

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