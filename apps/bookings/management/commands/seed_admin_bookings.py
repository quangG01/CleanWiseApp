from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.addresses.models import CustomerAddress
from apps.bookings.activity_service import record_booking_activity
from apps.bookings.models import Booking, BookingActivity, BookingSchedule
from apps.payments.models import Payment
from apps.services.models import Service
from apps.worker.models import BookingAssignment


class Command(BaseCommand):
    help = 'Tạo bộ đơn mẫu cho màn hình quản trị đơn dịch vụ.'

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        customer = User.objects.filter(role='CUSTOMER', is_active=True).order_by('id').first()
        admin = User.objects.filter(role='ADMIN', is_active=True).order_by('id').first()
        service = Service.objects.filter(is_active=True).order_by('id').first()

        if not customer or not admin or not service:
            raise CommandError('Cần có ít nhất một customer, admin và dịch vụ đang hoạt động.')

        address = CustomerAddress.objects.filter(customer=customer, is_active=True).order_by('-is_default', 'id').first()
        worker = User.objects.filter(
            role='WORKER',
            is_active=True,
            worker_profile__status='ACTIVE',
            worker_profile__registered_service=service,
        ).order_by('id').first()
        if not address or not worker:
            raise CommandError('Khách hàng cần có địa chỉ và dịch vụ cần có một nhân viên ACTIVE phù hợp.')

        source = Booking.objects.filter(customer=customer, service=service).order_by('id').first()
        service_data = source.service_data if source else {}
        price_breakdown = source.price_breakdown if source and source.price_breakdown else {
            'base_price': 300000,
            'description': 'Dữ liệu mẫu trang quản trị',
        }

        specs = [
            {
                'code': 'CW-ADMIN-DEMO-PENDING',
                'status': Booking.Status.PENDING,
                'payment_status': Booking.PaymentStatus.UNPAID,
                'schedule_statuses': [BookingSchedule.Status.PENDING, BookingSchedule.Status.PENDING],
                'amount': Decimal('450000'),
                'day_offset': 1,
                'cash': True,
                'note': 'Đơn mẫu chờ phân công, gồm hai buổi.',
            },
            {
                'code': 'CW-ADMIN-DEMO-ASSIGNED',
                'status': Booking.Status.ASSIGNED,
                'payment_status': Booking.PaymentStatus.UNPAID,
                'schedule_statuses': [BookingSchedule.Status.PENDING],
                'amount': Decimal('320000'),
                'day_offset': 2,
                'assign': True,
                'cash': True,
                'note': 'Đơn mẫu đã được admin gán nhân viên.',
            },
            {
                'code': 'CW-ADMIN-DEMO-WORKING',
                'status': Booking.Status.IN_PROGRESS,
                'payment_status': Booking.PaymentStatus.PAID,
                'schedule_statuses': [BookingSchedule.Status.IN_PROGRESS],
                'amount': Decimal('520000'),
                'day_offset': 0,
                'assign': True,
                'payment': Payment.Status.SUCCESS,
                'note': 'Đơn mẫu nhân viên đã check-in và đang thực hiện.',
            },
            {
                'code': 'CW-ADMIN-DEMO-DONE',
                'status': Booking.Status.COMPLETED,
                'payment_status': Booking.PaymentStatus.PAID,
                'schedule_statuses': [BookingSchedule.Status.COMPLETED, BookingSchedule.Status.COMPLETED],
                'amount': Decimal('780000'),
                'day_offset': -2,
                'assign': True,
                'payment': Payment.Status.SUCCESS,
                'note': 'Đơn mẫu đã hoàn thành và thanh toán.',
            },
            {
                'code': 'CW-ADMIN-DEMO-CANCELLED',
                'status': Booking.Status.CANCELLED,
                'payment_status': Booking.PaymentStatus.REFUNDED,
                'schedule_statuses': [BookingSchedule.Status.CANCELLED],
                'amount': Decimal('390000'),
                'day_offset': 3,
                'payment': Payment.Status.REFUNDED,
                'note': 'Đơn mẫu đã hủy và hoàn tiền.',
                'cancelled': True,
            },
            {
                'code': 'CW-ADMIN-DEMO-FAILED',
                'status': Booking.Status.FAILED,
                'payment_status': Booking.PaymentStatus.UNPAID,
                'schedule_statuses': [BookingSchedule.Status.MISSED],
                'amount': Decimal('280000'),
                'day_offset': -1,
                'note': 'Đơn mẫu thất bại vì không tìm được nhân viên.',
                'failed': True,
            },
        ]

        created_codes = []
        existing_codes = []
        now = timezone.now()

        for index, spec in enumerate(specs):
            booking, created = Booking.objects.get_or_create(
                booking_code=spec['code'],
                defaults={
                    'customer': customer,
                    'service': service,
                    'service_data': service_data,
                    'address': address,
                    'note': spec['note'],
                    'status': spec['status'],
                    'payment_status': spec['payment_status'],
                    'price_breakdown': price_breakdown,
                    'subtotal_amount': spec['amount'],
                    'discount_amount': Decimal('0'),
                    'total_amount': spec['amount'],
                    'cancelled_by': admin if spec.get('cancelled') else None,
                    'cancelled_at': now if spec.get('cancelled') else None,
                    'cancel_reason': 'Khách thay đổi kế hoạch (dữ liệu mẫu).' if spec.get('cancelled') else None,
                },
            )
            if spec.get('cash'):
                Payment.objects.get_or_create(
                    booking=booking,
                    method=Payment.Method.CASH,
                    defaults={
                        'customer': customer,
                        'amount': spec['amount'],
                        'status': Payment.Status.PENDING,
                    },
                )
            if not created:
                existing_codes.append(spec['code'])
                continue

            Booking.objects.filter(pk=booking.pk).update(created_at=now - timedelta(days=index))
            record_booking_activity(
                booking=booking,
                actor=admin,
                event_type=BookingActivity.EventType.BOOKING_CREATED,
                message='Admin tạo đơn mẫu để kiểm thử màn hình quản trị.',
                metadata={'seed': True},
            )

            for sequence_no, schedule_status in enumerate(spec['schedule_statuses'], start=1):
                start = now + timedelta(days=spec['day_offset'] + sequence_no - 1)
                actual_start = now - timedelta(hours=1) if schedule_status in (BookingSchedule.Status.IN_PROGRESS, BookingSchedule.Status.COMPLETED) else None
                actual_end = now if schedule_status == BookingSchedule.Status.COMPLETED else None
                schedule = BookingSchedule.objects.create(
                    booking=booking,
                    sequence_no=sequence_no,
                    scheduled_start=start.replace(hour=9, minute=0, second=0, microsecond=0),
                    scheduled_end=start.replace(hour=11, minute=0, second=0, microsecond=0),
                    actual_start=actual_start,
                    actual_end=actual_end,
                    status=schedule_status,
                    note=f'Buổi mẫu số {sequence_no}',
                    completion_note='Đã hoàn tất công việc mẫu.' if schedule_status == BookingSchedule.Status.COMPLETED else None,
                    cancelled_by=admin if schedule_status == BookingSchedule.Status.CANCELLED else None,
                    cancelled_at=now if schedule_status == BookingSchedule.Status.CANCELLED else None,
                    cancel_reason='Đơn đã bị hủy.' if schedule_status == BookingSchedule.Status.CANCELLED else None,
                )

                if spec.get('assign'):
                    BookingAssignment.objects.create(
                        schedule=schedule,
                        worker=worker,
                        assigned_by=admin,
                        assigned_method=BookingAssignment.AssignedMethod.MANUAL,
                        status=BookingAssignment.Status.ACCEPTED,
                        responded_at=now,
                        response_note='Phân công mẫu từ admin.',
                    )
                    record_booking_activity(
                        booking=booking,
                        schedule=schedule,
                        actor=admin,
                        event_type=BookingActivity.EventType.WORKER_ASSIGNED,
                        message=f'Admin đã gán {worker.get_full_name() or worker.username} vào buổi {sequence_no}.',
                        metadata={'seed': True, 'worker_id': worker.id},
                    )

                if schedule_status == BookingSchedule.Status.IN_PROGRESS:
                    record_booking_activity(
                        booking=booking,
                        schedule=schedule,
                        actor=worker,
                        event_type=BookingActivity.EventType.CHECKED_IN,
                        message=f'Nhân viên đã check-in buổi {sequence_no}.',
                        metadata={'seed': True},
                    )
                elif schedule_status == BookingSchedule.Status.COMPLETED:
                    record_booking_activity(
                        booking=booking,
                        schedule=schedule,
                        actor=worker,
                        event_type=BookingActivity.EventType.CHECKED_OUT,
                        message=f'Nhân viên đã hoàn thành buổi {sequence_no}.',
                        metadata={'seed': True},
                    )

            if spec.get('payment'):
                payment = Payment.objects.create(
                    customer=customer,
                    booking=booking,
                    amount=spec['amount'],
                    method=Payment.Method.BANK_TRANSFER,
                    status=spec['payment'],
                    transaction_code=f"SEED-{spec['code']}",
                    paid_at=now if spec['payment'] in (Payment.Status.SUCCESS, Payment.Status.REFUNDED) else None,
                )
                event_type = (
                    BookingActivity.EventType.REFUND_COMPLETED
                    if payment.status == Payment.Status.REFUNDED
                    else BookingActivity.EventType.PAYMENT_UPDATED
                )
                record_booking_activity(
                    booking=booking,
                    actor=admin,
                    event_type=event_type,
                    message='Đã hoàn tiền đơn mẫu.' if payment.status == Payment.Status.REFUNDED else 'Thanh toán đơn mẫu thành công.',
                    metadata={'seed': True, 'payment_id': payment.id},
                )

            if spec.get('cancelled'):
                record_booking_activity(
                    booking=booking,
                    actor=admin,
                    event_type=BookingActivity.EventType.BOOKING_CANCELLED,
                    message='Admin đã hủy đơn mẫu.',
                    metadata={'seed': True},
                )
            if spec.get('failed'):
                record_booking_activity(
                    booking=booking,
                    event_type=BookingActivity.EventType.BOOKING_FAILED,
                    message='Đơn mẫu thất bại vì không tìm được nhân viên phù hợp.',
                    metadata={'seed': True},
                )

            created_codes.append(spec['code'])

        self.stdout.write(self.style.SUCCESS(f'Created {len(created_codes)} sample bookings.'))
        for code in created_codes:
            self.stdout.write(f'  + {code}')
        if existing_codes:
            self.stdout.write(f'Skipped {len(existing_codes)} existing bookings: {", ".join(existing_codes)}')
