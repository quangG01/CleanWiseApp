from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


DEFAULT_ADDRESS_KEY = 'home'
ADDRESS_OPTIONS = {
    'home': {'label': 'Nhà', 'ward_code': '27568'},
    'school': {'label': 'Trường', 'ward_code': '26890'},
}
TEST_CUSTOMER_USERNAME = '0961439551'
TEST_WORKER_USERNAME = '0961439567'
TEST_SERVICE_CODE = 'HOME_CLEANING_HOURLY'
TEST_SEED_PREFIX = 'seed_checkin_demo:v1'
CHECKIN_READY_MINUTES = 5
CHECKOUT_READY_MINUTES = 2
CHECKOUT_IMAGE_PATHS = {
    'BEFORE': 'schedule_photos/HOME_CLEANING/before_01.jpg',
    'AFTER': 'schedule_photos/HOME_CLEANING/after_01.jpg',
}
DEMO_PASSWORD = '123456789Aa@'


def _service_data_and_schedule(service, start_at):
    from apps.bookings.schedule_builder import build_schedules
    from apps.common.management.commands.seed_demo import _build_service_data

    local_start = timezone.localtime(start_at).replace(second=0, microsecond=0)
    service_data, _ = _build_service_data(
        service,
        date_value=timezone.localdate() + timedelta(days=1),
        start_time=local_start.strftime('%H:%M'),
        recurring_weekday='MON',
    )
    service_data['date'] = local_start.date().isoformat()
    service_data['start_time'] = local_start.strftime('%H:%M')
    schedules = build_schedules(service.form_schema or {}, service_data)
    if len(schedules) != 1:
        raise CommandError(
            f'{service.code} phải tạo đúng 1 schedule cho kịch bản kiểm thử.'
        )
    return service_data, schedules[0]


def _get_checkout_image_urls(seed_key):
    from apps.bookings.models import BookingActivity, BookingScheduleImage
    from apps.common.management.commands.seed_demo import demo_booking_ids

    image_urls = {}
    existing_scenario = (
        BookingActivity.objects.filter(
            event_type=BookingActivity.EventType.BOOKING_CREATED,
            metadata__seed_key=seed_key,
        )
        .select_related('booking')
        .first()
    )
    if existing_scenario is not None:
        existing_schedule = existing_scenario.booking.schedules.first()
        if (
            existing_schedule is None
            or existing_schedule.status != 'IN_PROGRESS'
        ):
            return image_urls
        for image in existing_schedule.images.exclude(image=''):
            if image.image.startswith('https://'):
                image_urls.setdefault(image.image_type, image.image)
        if len(image_urls) == len(CHECKOUT_IMAGE_PATHS):
            return image_urls

    demo_ids = demo_booking_ids()
    for image_type in CHECKOUT_IMAGE_PATHS:
        if image_type in image_urls:
            continue
        existing_image = (
            BookingScheduleImage.objects.filter(
                schedule__booking_id__in=demo_ids,
                image_type=image_type,
                image__startswith='https://',
            )
            .exclude(image='')
            .order_by('pk')
            .first()
        )
        if existing_image is not None:
            image_urls[image_type] = existing_image.image

    missing_types = set(CHECKOUT_IMAGE_PATHS) - set(image_urls)
    if missing_types:
        raise CommandError(
            'Thiếu ảnh mẫu BEFORE/AFTER trên các booking demo đã seed. '
            'Chạy seed_demo --commit trước để chuẩn bị ảnh; command này không upload ảnh.'
        )
    return image_urls


def _existing_scenario(seed_key, *, customer, worker, service, address):
    from apps.bookings.models import Booking, BookingActivity, BookingSchedule
    from apps.payments.models import Payment
    from apps.worker.models import BookingAssignment

    activities = list(
        BookingActivity.objects.filter(
            event_type=BookingActivity.EventType.BOOKING_CREATED,
            metadata__seed_key=seed_key,
        ).select_related('booking')
    )
    if not activities:
        return None
    if len(activities) != 1:
        raise CommandError(f'Tìm thấy nhiều booking cho seed_key {seed_key}.')

    booking = activities[0].booking
    if (
        booking.customer_id != customer.pk
        or booking.service_id != service.pk
        or booking.address_id != address.pk
    ):
        raise CommandError(
            f'Booking {booking.booking_code} không khớp customer/service/address của seed.'
        )
    schedules = list(BookingSchedule.objects.filter(booking=booking).order_by('sequence_no'))
    if len(schedules) != 1:
        raise CommandError(f'Booking {booking.booking_code} không có đúng một schedule.')
    schedule = schedules[0]
    if not BookingAssignment.objects.filter(
        schedule=schedule,
        worker=worker,
        status=BookingAssignment.Status.ACCEPTED,
    ).exists():
        raise CommandError(f'Booking {booking.booking_code} không còn assignment accepted hợp lệ.')
    payments = list(Payment.objects.filter(booking=booking))
    if (
        len(payments) != 1
        or payments[0].customer_id != customer.pk
        or payments[0].amount != booking.total_amount
        or payments[0].status != Payment.Status.SUCCESS
        or booking.payment_status != Booking.PaymentStatus.PAID
    ):
        raise CommandError(f'Booking {booking.booking_code} có payment không đồng bộ.')
    return booking, schedule


def _minute_candidates(preferred, earliest, latest):
    minute = timedelta(minutes=1)
    first = earliest.replace(second=0, microsecond=0)
    if first < earliest:
        first += minute
    last = latest.replace(second=0, microsecond=0)
    if first > last:
        return

    center = min(max(preferred.replace(second=0, microsecond=0), first), last)
    max_steps = int((last - first).total_seconds() // 60)
    for offset in range(max_steps + 1):
        earlier = center - offset * minute
        if first <= earlier <= last:
            yield earlier
        later = center + offset * minute
        if offset and first <= later <= last:
            yield later


def _has_worker_schedule_conflict(worker, start, end, reserved_slots):
    from apps.bookings.models import BookingSchedule
    from apps.worker.models import BookingAssignment

    if any(start < reserved_end and end > reserved_start
           for reserved_start, reserved_end in reserved_slots):
        return True
    return BookingAssignment.objects.filter(
        worker=worker,
        status=BookingAssignment.Status.ACCEPTED,
        schedule__status__in=(
            BookingSchedule.Status.PENDING,
            BookingSchedule.Status.IN_PROGRESS,
        ),
        schedule__scheduled_start__lt=end,
        schedule__scheduled_end__gt=start,
    ).exists()


def _find_available_start(
    *,
    worker,
    preferred,
    earliest,
    latest,
    duration,
    reserved_slots,
    scenario,
):
    for start in _minute_candidates(preferred, earliest, latest):
        if not _has_worker_schedule_conflict(
            worker,
            start,
            start + duration,
            reserved_slots,
        ):
            return start
    raise CommandError(
        f'Không tìm thấy khung giờ {scenario} hợp lệ, không trùng lịch của worker '
        f'{worker.username}. Hãy thử lại khi worker có lịch trống.'
    )


def _create_scenario(
    *,
    seed_key,
    scenario,
    start_at,
    customer,
    worker,
    address,
    service,
    admin,
    now,
    checkout_image_urls=None,
):
    from apps.bookings.models import Booking, BookingActivity, BookingSchedule, BookingScheduleImage
    from apps.payments.models import Payment
    from apps.worker.models import BookingAssignment

    existing = _existing_scenario(
        seed_key,
        customer=customer,
        worker=worker,
        service=service,
        address=address,
    )
    if existing is not None:
        booking, schedule = existing
        if scenario == 'checkout-ready' and schedule.status == BookingSchedule.Status.IN_PROGRESS:
            existing_types = set(
                schedule.images.values_list('image_type', flat=True)
            )
            for image_type, image_url in (checkout_image_urls or {}).items():
                if image_type not in existing_types:
                    BookingScheduleImage.objects.create(
                        uploaded_by=worker,
                        schedule=schedule,
                        image_type=image_type,
                        image=image_url,
                        note='Ảnh mẫu của kịch bản kiểm thử; có thể thay bằng ảnh thực tế.',
                    )
        return booking, schedule, False

    from apps.bookings.booking_service import calculate_booking_price, _generate_booking_code
    from apps.common.management.commands.seed_demo import _booking_price

    service_data, schedule_data = _service_data_and_schedule(service, start_at)
    unit_price = calculate_booking_price(service, service_data)
    if unit_price is None or unit_price <= 0:
        raise CommandError(f'Không tính được giá cho dịch vụ {service.code}.')
    subtotal, effective_unit_price, package_discount = _booking_price(
        service,
        service_data,
        unit_price,
        1,
    )
    if subtotal <= 0:
        raise CommandError(f'Giá booking kiểm thử của {service.code} không hợp lệ.')

    checkout_ready = scenario == 'checkout-ready'
    booking_status = Booking.Status.IN_PROGRESS if checkout_ready else Booking.Status.ASSIGNED
    schedule_status = (
        BookingSchedule.Status.IN_PROGRESS if checkout_ready else BookingSchedule.Status.PENDING
    )
    booking_code = _generate_booking_code()
    booking = Booking.objects.create(
        booking_code=booking_code,
        customer=customer,
        service=service,
        service_data=service_data,
        address=address,
        note='Đơn nội bộ phục vụ kiểm thử quy trình check-in/check-out; không gọi cổng thanh toán.',
        status=booking_status,
        payment_status=Booking.PaymentStatus.PAID,
        subtotal_amount=subtotal,
        discount_amount=Decimal('0.00'),
        total_amount=subtotal,
        price_breakdown={
            'unit_price': str(
                effective_unit_price if effective_unit_price is not None else unit_price
            ),
            'base_unit_price': str(unit_price),
            'sessions_count': 1,
            'package_discount_percent': str(package_discount),
            'subtotal_amount': str(subtotal),
            'discount_amount': '0.00',
            'total_amount': str(subtotal),
            'pricing_config_snapshot': service.pricing_config,
            'voucher': None,
        },
    )
    schedule = BookingSchedule.objects.create(
        booking=booking,
        sequence_no=1,
        scheduled_start=schedule_data['scheduled_start'],
        scheduled_end=schedule_data['scheduled_end'],
        actual_start=schedule_data['scheduled_start'] if checkout_ready else None,
        status=schedule_status,
        note='Kịch bản sẵn sàng để thử check-out.'
        if checkout_ready else 'Kịch bản sẵn sàng để thử check-in.',
    )
    assignment = BookingAssignment(
        schedule=schedule,
        worker=worker,
        assigned_by=admin,
        assigned_method=BookingAssignment.AssignedMethod.MANUAL,
        status=BookingAssignment.Status.ACCEPTED,
        response_note='Assignment seed phục vụ kiểm thử trên app.',
        responded_at=now,
    )
    payment = Payment(
        customer=customer,
        booking=booking,
        amount=subtotal,
        method=Payment.Method.BANK_TRANSFER,
        status=Payment.Status.SUCCESS,
        transaction_code=f'CHECKIN-SEED-{booking_code}',
        paid_at=now,
    )
    # Bỏ qua post_save signals để seed không gửi thông báo/push trực tiếp.
    BookingAssignment.objects.bulk_create([assignment])
    Payment.objects.bulk_create([payment])
    if assignment.pk is None:
        assignment = BookingAssignment.objects.get(
            schedule=schedule,
            worker=worker,
            status=BookingAssignment.Status.ACCEPTED,
        )
    BookingActivity.objects.create(
        booking=booking,
        actor=customer,
        event_type=BookingActivity.EventType.BOOKING_CREATED,
        message=f'Khách hàng tạo booking kiểm thử {booking_code}.',
        new_data={'customer_id': customer.pk, 'service_id': service.pk},
        metadata={'seed_key': seed_key},
    )
    BookingActivity.objects.create(
        booking=booking,
        schedule=schedule,
        actor=worker,
        event_type=BookingActivity.EventType.WORKER_CLAIMED,
        message=f'{worker.get_full_name() or worker.username} nhận buổi kiểm thử.',
        new_data={'worker_id': worker.pk, 'assignment_id': assignment.pk},
        metadata={'seed_key': seed_key},
    )

    if checkout_ready:
        if schedule.actual_start is None:
            raise CommandError(f'Không có actual_start cho booking {booking_code}.')
        BookingActivity.objects.create(
            booking=booking,
            schedule=schedule,
            actor=worker,
            event_type=BookingActivity.EventType.CHECKED_IN,
            message='Check-in mẫu để chuẩn bị thử chức năng check-out.',
            new_data={
                'actual_start': schedule.actual_start.isoformat(),
                'latitude': float(address.latitude),
                'longitude': float(address.longitude),
                'accuracy': 5,
                'distance_m': 0,
            },
            metadata={'seed_key': seed_key},
        )
        for image_type, image_url in (checkout_image_urls or {}).items():
            BookingScheduleImage.objects.create(
                uploaded_by=worker,
                schedule=schedule,
                image_type=image_type,
                image=image_url,
                note='Ảnh mẫu của kịch bản kiểm thử; có thể thay bằng ảnh thực tế.',
            )

    return booking, schedule, True


class Command(BaseCommand):
    help = 'Tạo booking kiểm thử check-in/check-out; mặc định dry-run và không gọi dịch vụ ngoài.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--commit', action='store_true', help='Ghi hai kịch bản vào database.')
        mode.add_argument('--dry-run', action='store_true', help='Chạy thử rồi rollback (mặc định).')
        parser.add_argument(
            '--address',
            choices=tuple(ADDRESS_OPTIONS),
            default=None,
            help='Chọn home hoặc school; mặc định lấy DEFAULT_ADDRESS_KEY trong file.',
        )

    def handle(self, *args, **options):
        if args:
            raise CommandError('seed_checkin_demo không nhận tham số vị trí.')

        from django.conf import settings

        from apps.addresses.models import CustomerAddress
        from apps.authentication.models import User, WorkerProfile
        from apps.services.models import Service
        from apps.worker.assignment_service import CHECKOUT_GRACE_MINUTES
        from apps.worker.checkin_service import CHECKIN_EARLY_MINUTES, CHECKIN_LATE_MINUTES
        from apps.worker.models import WorkerWorkingArea
        from apps.wallets.models import Wallet

        commit = options['commit']
        address_key = options['address'] or DEFAULT_ADDRESS_KEY
        address_config = ADDRESS_OPTIONS[address_key]
        if CHECKIN_EARLY_MINUTES < CHECKIN_READY_MINUTES:
            raise CommandError(
                'Cửa sổ check-in sớm ngắn hơn 5 phút; cần điều chỉnh CHECKIN_READY_MINUTES '
                'trong seed_checkin_demo.py.'
            )
        if CHECKOUT_GRACE_MINUTES <= CHECKOUT_READY_MINUTES:
            raise CommandError(
                'CHECKOUT_GRACE_MINUTES phải lớn hơn CHECKOUT_READY_MINUTES để tạo kịch bản checkout.'
            )

        customer = User.objects.filter(
            username=TEST_CUSTOMER_USERNAME,
            role=User.Role.CUSTOMER,
            is_active=True,
        ).first()
        if customer is None:
            raise CommandError(f'Không tìm thấy customer active {TEST_CUSTOMER_USERNAME}.')
        worker = User.objects.filter(
            username=TEST_WORKER_USERNAME,
            role=User.Role.WORKER,
            is_active=True,
        ).first()
        if worker is None:
            raise CommandError(f'Không tìm thấy worker active {TEST_WORKER_USERNAME}.')
        profile = WorkerProfile.objects.select_related('registered_service').filter(
            user=worker,
        ).first()
        if (
            profile is None
            or profile.status != WorkerProfile.Status.ACTIVE
            or profile.registered_service is None
            or profile.registered_service.section_code != 'HOME_CLEANING'
        ):
            raise CommandError(
                f'{TEST_WORKER_USERNAME} chưa có hồ sơ active đăng ký dịch vụ dọn dẹp nhà.'
            )
        service = Service.objects.filter(
            code=TEST_SERVICE_CODE,
            section_code='HOME_CLEANING',
            is_active=True,
        ).first()
        if service is None or (service.form_schema or {}).get('schedule_type', 'ONCE') != 'ONCE':
            raise CommandError(f'Không tìm thấy dịch vụ dọn nhà một buổi active {TEST_SERVICE_CODE}.')
        address = CustomerAddress.objects.filter(
            customer=customer,
            label=address_config['label'],
            ward_code=address_config['ward_code'],
            is_active=True,
        ).order_by('-is_default', 'pk').first()
        if address is None:
            raise CommandError(
                f'Không tìm thấy địa chỉ {address_config["label"]} của {TEST_CUSTOMER_USERNAME}.'
            )
        if address.latitude is None or address.longitude is None:
            raise CommandError(
                f'Địa chỉ {address.label} thiếu GPS; check-in thật cần tọa độ địa chỉ.'
            )
        if not WorkerWorkingArea.objects.filter(
            worker=worker,
            area__ward_code=address.ward_code,
        ).exists():
            raise CommandError(
                f'{worker.username} chưa đăng ký khu vực {address.ward_code}.'
            )
        if not Wallet.objects.filter(user=worker).exists():
            raise CommandError(
                f'{worker.username} chưa có Wallet; hãy chạy seed_demo --commit trước.'
            )

        seed_keys = {
            'checkin-ready': f'{TEST_SEED_PREFIX}:{address_key}:checkin-ready',
            'checkout-ready': f'{TEST_SEED_PREFIX}:{address_key}:checkout-ready',
        }
        existing_checkin = _existing_scenario(
            seed_keys['checkin-ready'],
            customer=customer,
            worker=worker,
            service=service,
            address=address,
        )
        existing_checkout = _existing_scenario(
            seed_keys['checkout-ready'],
            customer=customer,
            worker=worker,
            service=service,
            address=address,
        )

        now = timezone.localtime()
        today = timezone.localdate()
        opening = timezone.make_aware(
            datetime.combine(today, settings.BOOKING_OPEN_TIME),
        )
        last_start = timezone.make_aware(
            datetime.combine(today, settings.BOOKING_LAST_START_TIME),
        )
        _, template_schedule_data = _service_data_and_schedule(
            service,
            opening,
        )
        duration = (
            template_schedule_data['scheduled_end'] - template_schedule_data['scheduled_start']
        )
        reserved_slots = []
        if existing_checkin is not None:
            checkin_start = existing_checkin[1].scheduled_start
        else:
            checkin_start = _find_available_start(
                worker=worker,
                preferred=now + timedelta(minutes=CHECKIN_READY_MINUTES),
                earliest=max(
                    opening,
                    now - timedelta(minutes=CHECKIN_LATE_MINUTES),
                ),
                latest=min(
                    last_start,
                    now + timedelta(minutes=CHECKIN_EARLY_MINUTES),
                ),
                duration=duration,
                reserved_slots=reserved_slots,
                scenario='check-in',
            )
            reserved_slots.append((checkin_start, checkin_start + duration))

        if existing_checkout is not None:
            checkout_start = existing_checkout[1].scheduled_start
        else:
            checkout_start = _find_available_start(
                worker=worker,
                preferred=now - timedelta(minutes=CHECKOUT_READY_MINUTES) - duration,
                earliest=max(
                    opening,
                    now - timedelta(minutes=CHECKOUT_GRACE_MINUTES) - duration,
                ),
                latest=min(last_start, now - duration),
                duration=duration,
                reserved_slots=reserved_slots,
                scenario='check-out',
            )

        checkout_image_urls = _get_checkout_image_urls(seed_keys['checkout-ready'])
        admin = User.objects.filter(role=User.Role.ADMIN, is_active=True).order_by('pk').first()

        self.stdout.write(
            f'Khách: {customer.username}; nhân viên dọn nhà: {worker.username} / {DEMO_PASSWORD}.'
        )
        self.stdout.write(
            f'Địa chỉ: {address.label} ({address.ward_code}), '
            f'GPS {address.latitude}, {address.longitude}; không upload ảnh.'
        )
        with transaction.atomic():
            list(
                User.objects.select_for_update()
                .filter(pk__in=(customer.pk, worker.pk))
                .order_by('pk')
                .values_list('pk', flat=True)
            )
            checkin_booking, checkin_schedule, checkin_created = _create_scenario(
                seed_key=seed_keys['checkin-ready'],
                scenario='checkin-ready',
                start_at=checkin_start,
                customer=customer,
                worker=worker,
                address=address,
                service=service,
                admin=admin,
                now=now,
            )
            checkout_booking, checkout_schedule, checkout_created = _create_scenario(
                seed_key=seed_keys['checkout-ready'],
                scenario='checkout-ready',
                start_at=checkout_start,
                customer=customer,
                worker=worker,
                address=address,
                service=service,
                admin=admin,
                now=now,
                checkout_image_urls=checkout_image_urls,
            )
            self.stdout.write(
                f'Check-in: {checkin_booking.booking_code}, schedule {checkin_schedule.pk}, '
                f'{checkin_schedule.scheduled_start:%d/%m %H:%M} '
                f'({ "mới" if checkin_created else checkin_schedule.status }).'
            )
            self.stdout.write(
                f'Check-out: {checkout_booking.booking_code}, schedule {checkout_schedule.pk}, '
                f'hạn thử đến {checkout_schedule.scheduled_end + timedelta(minutes=CHECKOUT_GRACE_MINUTES):%d/%m %H:%M} '
                f'({ "mới" if checkout_created else checkout_schedule.status }).'
            )
            if not commit:
                transaction.set_rollback(True)

        if commit:
            self.stdout.write(self.style.SUCCESS('Đã ghi hai booking kiểm thử vào database.'))
        else:
            self.stdout.write(
                self.style.WARNING('Dry-run hoàn tất: mọi thay đổi database đã rollback.')
            )
