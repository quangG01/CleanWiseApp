# Booking serializers.
from rest_framework import serializers

from apps.addresses.models import CustomerAddress
from apps.payments.models import Payment
from apps.worker.models import BookingAssignment

from .booking_service import create_booking
from .models import Booking, BookingSchedule


# ĐỔI: xoá BookingScheduleInputSerializer — không còn nhận `schedules` từ
# client nữa, BE tự sinh lịch từ service_data qua schedule_builder.py.


class BookingAddressSerializer(serializers.ModelSerializer):
    """Địa chỉ thực hiện dịch vụ, hiển thị cho customer ở trang chi tiết đơn."""

    class Meta:
        model = CustomerAddress
        fields = [
            'id',
            'label',
            'address_line',
            'ward',
            'city',
            'receiver_name',
            'receiver_phone',
            'latitude',
            'longitude',
        ]


class BookingWorkerSerializer(serializers.ModelSerializer):
    """
    Thông tin worker được phép hiển thị cho customer.

    Không expose các thông tin nhạy cảm của worker:
    - identity_number
    - verification documents
    - approved_by
    - approved_at
    - rejection_reason
    - rejected_fields
    - email
    - phone_number
    """

    worker_id = serializers.IntegerField(
        source='worker.id',
        read_only=True,
    )

    first_name = serializers.CharField(
        source='worker.first_name',
        read_only=True,
    )

    last_name = serializers.CharField(
        source='worker.last_name',
        read_only=True,
    )

    avatar = serializers.SerializerMethodField()

    bio = serializers.CharField(
        source='worker.worker_profile.bio',
        read_only=True,
        allow_null=True,
    )

    experience_years = serializers.IntegerField(
        source='worker.worker_profile.experience_years',
        read_only=True,
    )

    average_rating = serializers.DecimalField(
        source='worker.worker_profile.average_rating',
        max_digits=3,
        decimal_places=2,
        read_only=True,
    )

    total_completed_jobs = serializers.IntegerField(
        source='worker.worker_profile.total_completed_jobs',
        read_only=True,
    )

    class Meta:
        model = BookingAssignment
        fields = [
            'worker_id',
            'first_name',
            'last_name',
            'avatar',
            'bio',
            'experience_years',
            'average_rating',
            'total_completed_jobs',
        ]

    def get_avatar(self, obj):
        worker = obj.worker

        worker_profile = getattr(
            worker,
            'worker_profile',
            None,
        )

        # Ưu tiên avatar của WorkerProfile
        if worker_profile and worker_profile.avatar:
            return worker_profile.avatar

        # Fallback avatar của User
        return worker.avatar


class BookingScheduleSerializer(serializers.ModelSerializer):
    worker = serializers.SerializerMethodField()
    assignment_id = serializers.SerializerMethodField()
    conversation_id = serializers.SerializerMethodField()

    class Meta:
        model = BookingSchedule
        fields = [
            'id',
            'sequence_no',
            'scheduled_start',
            'scheduled_end',
            'actual_start',
            'actual_end',
            'status',
            'note',
            'worker',
            'assignment_id',
            'conversation_id',
        ]

    def _accepted_assignment(self, obj):
        # ĐỔI: cache theo obj.pk trong vòng đời serializer instance,
        # tránh gọi obj.assignments.all() nhiều lần (worker,
        # assignment_id, conversation_id mỗi cái gọi 1 lần) cho cùng
        # 1 schedule -- kể cả khi đã prefetch, gọi lặp vẫn có overhead.
        if not hasattr(self, '_assignment_cache'):
            self._assignment_cache = {}
        if obj.pk not in self._assignment_cache:
            self._assignment_cache[obj.pk] = next(iter(obj.assignments.all()), None)
        return self._assignment_cache[obj.pk]

    def get_assignment_id(self, obj):
        assignment = self._accepted_assignment(obj)
        return assignment.id if assignment else None

    def get_conversation_id(self, obj):
        assignment = self._accepted_assignment(obj)
        if assignment is None:
            return None
        link = getattr(assignment, 'chat_link', None)
        return link.conversation_id if link else None

    def get_worker(self, obj):
        """
        Chỉ trả worker nếu có assignment ACCEPTED.

        BookingDetailView sẽ prefetch assignments với
        status=ACCEPTED nên:
            - chưa có worker -> None
            - đã có worker -> thông tin worker
        """

        assignment = self._accepted_assignment(obj)

        if not assignment:
            return None

        return BookingWorkerSerializer(
            assignment,
            context=self.context,
        ).data


class BookingPaymentSerializer(serializers.ModelSerializer):
    method_display = serializers.CharField(
        source='get_method_display',
        read_only=True,
    )

    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True,
    )

    class Meta:
        model = Payment
        fields = [
            'id',
            'amount',
            'method',
            'method_display',
            'status',
            'status_display',
            'transaction_code',
            'paid_at',
            'failure_reason',
            'created_at',
            'updated_at',
        ]


class BookingListSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(
        source='service.name',
        read_only=True,
    )

    class Meta:
        model = Booking
        fields = [
            'id',
            'booking_code',
            'service_name',
            'status',
            'payment_status',
            'subtotal_amount',
            'discount_amount',
            'total_amount',
            'created_at',
        ]


class BookingDetailSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(
        source='service.name',
        read_only=True,
    )

    form_schema = serializers.JSONField(
        source='service.form_schema',
        read_only=True,
    )

    pricing_config = serializers.JSONField(
        source='service.pricing_config',
        read_only=True,
    )

    schedules = BookingScheduleSerializer(
        many=True,
        read_only=True,
    )

    payment = serializers.SerializerMethodField()

    address = BookingAddressSerializer(read_only=True)

    # ĐỔI: thêm delivery_address — null với dịch vụ 1 địa chỉ,
    # có giá trị với dịch vụ cần 2 địa chỉ (vd chuyển nhà).
    delivery_address = BookingAddressSerializer(
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = Booking
        fields = [
            'id',
            'booking_code',
            'service_name',
            'form_schema',
            'pricing_config',
            'service_data',
            'address',
            'delivery_address',  # ĐỔI: thêm vào fields
            'note',
            'status',
            'payment_status',
            'payment',
            'price_breakdown',
            'subtotal_amount',
            'discount_amount',
            'total_amount',
            'schedules',
            'created_at',
            'updated_at',
        ]

    def get_payment(self, obj):
        """
        Lấy payment mới nhất của booking.
        """

        payment = (
            obj.payments
            .order_by('-created_at')
            .first()
        )

        if not payment:
            return None

        return BookingPaymentSerializer(
            payment,
            context=self.context,
        ).data


class BookingCreateSerializer(serializers.Serializer):
    service_id = serializers.IntegerField()
    address_id = serializers.IntegerField()

    # ĐỔI: thêm delivery_address_id — chỉ bắt buộc khi
    # service.form_schema.address_count >= 2, được validate trong
    # create_booking() ở booking_service.py.
    delivery_address_id = serializers.IntegerField(
        required=False,
        allow_null=True,
    )

    service_data = serializers.JSONField()

    # ĐỔI: bỏ hẳn field `schedules` — BE tự sinh danh sách buổi làm việc
    # từ service_data + service.form_schema.schedule_type (ONCE /
    # RECURRING_WEEKLY...) qua schedule_builder.build_schedules(), thay vì
    # nhận trực tiếp từ client. Lý do: mỗi loại dịch vụ có cấu trúc lịch
    # khác nhau, để FE tự tính dễ lệch logic giữa các nơi dùng lại.

    note = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    voucher_code = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    payment_method = serializers.ChoiceField(
        choices=[
            (
                Payment.Method.CASH,
                Payment.Method.CASH.label,
            ),
            (
                Payment.Method.BANK_TRANSFER,
                Payment.Method.BANK_TRANSFER.label,
            ),
        ],
    )

    def create(self, validated_data):
        return create_booking(
            customer=self.context['request'].user,
            service_id=validated_data['service_id'],
            address_id=validated_data['address_id'],
            delivery_address_id=validated_data.get('delivery_address_id'),  # ĐỔI
            service_data=validated_data['service_data'],
            note=validated_data.get('note') or None,
            voucher_code=(
                validated_data.get('voucher_code') or ''
            ).strip() or None,
            payment_method=validated_data['payment_method'],
        )


class BookingCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=True)