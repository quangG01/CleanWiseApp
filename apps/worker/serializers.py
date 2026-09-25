from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from rest_framework import serializers

from .models import Area, BookingAssignment, WorkerWorkingArea
from apps.bookings.models import BookingSchedule, BookingScheduleImage

from django.utils import timezone
from . import assignment_service
from .constants import MIN_CANCEL_HOURS
from . import assignment_service

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


class BookingScheduleImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingScheduleImage
        fields = ['id', 'image', 'image_type', 'note', 'created_at']
        read_only_fields = fields


class WorkerScheduleSerializer(serializers.ModelSerializer):
    booking_id = serializers.IntegerField(read_only=True)
    booking_code = serializers.CharField(source='booking.booking_code', read_only=True)
    service_id = serializers.IntegerField(source='booking.service_id', read_only=True)
    service_name = serializers.CharField(source='booking.service.name', read_only=True)
    booking_note = serializers.CharField(source='booking.note', read_only=True, allow_null=True)
    total_sessions = serializers.IntegerField(read_only=True)
    address_city = serializers.CharField(source='booking.address.city', read_only=True)
    address_ward = serializers.CharField(source='booking.address.ward', read_only=True)
    address_latitude = serializers.DecimalField(
        source='booking.address.latitude', read_only=True, allow_null=True,
        max_digits=14, decimal_places=7,
    )
    address_longitude = serializers.DecimalField(
        source='booking.address.longitude', read_only=True, allow_null=True,
        max_digits=14, decimal_places=7,
    )
    customer_avatar = serializers.CharField(source='booking.customer.avatar', read_only=True, allow_null=True)
    customer_name = serializers.SerializerMethodField()
    payment_status = serializers.CharField(source='booking.payment_status', read_only=True)
    price = serializers.SerializerMethodField()
    service_data = serializers.JSONField(source='booking.service_data', read_only=True)
    form_schema = serializers.JSONField(source='booking.service.form_schema', read_only=True)
    assignment_id = serializers.SerializerMethodField()
    available_sessions = serializers.SerializerMethodField()

    def get_available_sessions(self, instance):
        # Chỉ có giá trị khi list được gộp theo booking (group_by=booking); còn lại None.
        return getattr(instance, 'available_sessions', None)

    class Meta:
        model = BookingSchedule
        fields = [
            'id', 'booking_id', 'booking_code', 'service_id', 'service_name', 'booking_note',
            'sequence_no', 'total_sessions', 'scheduled_start', 'scheduled_end', 'status',
            'address_city', 'address_ward', 'address_latitude', 'address_longitude',
            'customer_avatar', 'customer_name', 'payment_status', 'price',
            'service_data', 'form_schema', 'assignment_id',"available_sessions"
        ]
        read_only_fields = fields

    def get_customer_name(self, instance):
        customer = instance.booking.customer
        full_name = f'{customer.first_name} {customer.last_name}'.strip()
        return full_name or customer.username

    def get_assignment_id(self, instance):
        assignment = next(
            (a for a in instance.assignments.all() if a.status == BookingAssignment.Status.ACCEPTED),
            None,
        )
        return assignment.id if assignment else None

    def get_price(self, instance):
        # ĐỔI: ưu tiên đọc unit_price đã chốt sẵn trong price_breakdown lúc
        # tạo booking (giá gốc/buổi, KHÔNG bị trừ theo % giảm gói dài hay
        # voucher của khách -> nhân viên luôn nhận đủ, platform gánh phần
        # giảm giá). Giá trị này không đổi khi khách hủy bớt buổi khác
        # trong cùng booking, khác với cách chia total_amount/sessions cũ
        # (chia lại mỗi khi sessions thay đổi).
        #
        # Fallback: booking cũ tạo trước khi có price_breakdown['unit_price']
        # (hoặc dịch vụ không tính theo buổi, vd dịch vụ 1 lần không phải
        # PER_SESSION) -> chia đều total_amount cho total_sessions như cách
        # cũ, để không vỡ dữ liệu lịch sử.
        breakdown = instance.booking.price_breakdown or {}
        unit_price = breakdown.get('unit_price')
        if unit_price is not None:
            try:
                return str(Decimal(str(unit_price)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            except (TypeError, ValueError, ArithmeticError):
                pass

        total = instance.booking.total_amount
        sessions = getattr(instance, 'total_sessions', None)
        if total is None or not sessions:
            return None
        per_session = (total / sessions).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        return str(per_session)


class WorkerMyScheduleSerializer(WorkerScheduleSerializer):
    """my-schedules: lộ thông tin liên hệ + ảnh vì nhân viên đã nhận việc."""
    address_line = serializers.CharField(source='booking.address.address_line', read_only=True)
    receiver_name = serializers.CharField(source='booking.address.receiver_name', read_only=True)
    receiver_phone = serializers.CharField(source='booking.address.receiver_phone', read_only=True)
    can_cancel = serializers.SerializerMethodField()
    cancel_deadline = serializers.SerializerMethodField()
    images = BookingScheduleImageSerializer(many=True, read_only=True)

    class Meta(WorkerScheduleSerializer.Meta):
        fields = WorkerScheduleSerializer.Meta.fields + [
            'note', 'address_line', 'receiver_name', 'receiver_phone',
            'can_cancel', 'cancel_deadline', 'images',
        ]
        read_only_fields = fields

    def get_can_cancel(self, obj):
        return (
            obj.status == BookingSchedule.Status.PENDING
            and assignment_service.get_cancel_deadline(obj) > timezone.now()
        )

    def get_cancel_deadline(self, obj):
        return assignment_service.get_cancel_deadline(obj)


class WorkerBookingScheduleSerializer(WorkerScheduleSerializer):
    """
    Dùng cho GET /bookings/<id>/schedules/ — toàn bộ buổi của 1 gói.
    claim_state: OPEN (còn trống) / MINE (worker đang gọi API đã nhận) /
    TAKEN (người khác đã nhận — KHÔNG trả tên/id người đó, chỉ trạng thái,
    để bảo mật thông tin nhân viên khác).
    """
    claim_state = serializers.SerializerMethodField()

    class Meta(WorkerScheduleSerializer.Meta):
        fields = WorkerScheduleSerializer.Meta.fields + ['claim_state']
        read_only_fields = fields

    def _accepted_assignment(self, instance):
        return next(
            (a for a in instance.assignments.all() if a.status == BookingAssignment.Status.ACCEPTED),
            None,
        )

    def get_assignment_id(self, instance):
        # Ghi đè: chỉ trả assignment_id nếu buổi đó là CỦA WORKER ĐANG GỌI
        # API (khác với bản gốc chỉ check "có ai ACCEPTED"), để FE không
        # nhầm assignment của người khác thành của mình khi hiện nút hủy.
        request = self.context.get('request')
        worker_id = getattr(getattr(request, 'user', None), 'id', None)
        assignment = self._accepted_assignment(instance)
        if assignment and assignment.worker_id == worker_id:
            return assignment.id
        return None

    def get_claim_state(self, instance):
        request = self.context.get('request')
        worker = getattr(request, 'user', None)
        assignment = self._accepted_assignment(instance)

        if assignment is not None:
            return 'MINE' if assignment.worker_id == getattr(worker, 'id', None) else 'TAKEN'

        # Buổi còn trống nhưng trùng giờ với buổi khác worker đã nhận -> CONFLICT
        if worker is not None and assignment_service._has_time_conflict(worker, instance):
            return 'CONFLICT'

        return 'OPEN'



class CancelAssignmentSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class ClaimBookingPackageSerializer(serializers.Serializer):
    """
    Body cho POST /bookings/<booking_id>/claim/.
    - Không gửi `schedule_ids` (hoặc bỏ trống field khỏi body) -> nhận
      toàn bộ buổi PENDING còn trống của booking.
    - Gửi `schedule_ids` -> chỉ nhận đúng các buổi đó (1 buổi hoặc 1 phần
      trong gói).
    """
    schedule_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False,
        error_messages={'empty': 'Danh sách buổi không được để trống.'},
    )

    def validate_schedule_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError('Danh sách buổi bị trùng lặp.')
        return value


class AdminAssignWorkerSerializer(serializers.Serializer):
    worker_id = serializers.IntegerField()
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class ScheduleImageUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()
    image_type = serializers.ChoiceField(choices=BookingScheduleImage.ImageType.choices)
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)