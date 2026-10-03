"""Seed monthly bookings with per-session review scenarios, without overwriting data."""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.addresses.models import CustomerAddress
from apps.authentication.models import User
from apps.bookings.models import Booking, BookingSchedule
from apps.chat.service import ensure_chat_for_assignment
from apps.reviews.models import Review
from apps.reviews.review_service import create_review
from apps.services.models import Service
from apps.worker.models import BookingAssignment


class Command(BaseCommand):
    help = 'Tạo hai gói tháng 8 buổi để test review cho mỗi khách (DEBUG only).'

    def add_arguments(self, parser):
        parser.add_argument('--customer-phone', action='append', required=True)

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Chỉ chạy lệnh với cấu hình DEBUG.')
        results = []
        with transaction.atomic():
            service = Service.objects.filter(code='HOME_CLEANING_MONTHLY', is_active=True).first()
            if not service:
                raise CommandError('Cần dịch vụ HOME_CLEANING_MONTHLY đang hoạt động.')
            workers = list(User.objects.filter(
                username__in=[f'review_filter_demo_worker_{i}' for i in range(1, 4)],
                role=User.Role.WORKER,
            ).order_by('username'))
            if len(workers) != 3:
                raise CommandError('Cần ba nhân viên từ seed_review_filters_demo trước.')
            today = timezone.localtime().replace(hour=8, minute=0, second=0, microsecond=0)
            for phone in dict.fromkeys(options['customer_phone']):
                customer = User.objects.filter(phone_number=phone, role=User.Role.CUSTOMER).first()
                address = CustomerAddress.objects.filter(customer=customer).first() if customer else None
                if not customer or not address:
                    raise CommandError(f'Cần khách hàng {phone} và địa chỉ của khách.')
                for scenario, age, booking_status in (
                    ('ACTIVE', 14, Booking.Status.IN_PROGRESS),
                    ('DONE', 60, Booking.Status.COMPLETED),
                ):
                    first = today - timedelta(days=age)
                    first -= timedelta(days=first.weekday())
                    code = f'MONTH-REVIEW-{customer.id}-{scenario}'
                    booking, created = Booking.objects.get_or_create(booking_code=code, defaults={
                        'customer': customer, 'service': service, 'address': address,
                        'service_data': {'weekdays': ['MON', 'THU'], 'start_time': '08:00',
                                         'duration': '2_HOURS', 'package_duration': '1_MONTH',
                                         'additional_services': [], 'note': 'Gói demo kiểm thử đánh giá từng buổi.'},
                        'status': booking_status, 'payment_status': Booking.PaymentStatus.PAID,
                        'subtotal_amount': 2400000, 'total_amount': 2400000,
                        'price_breakdown': {'subtotal_amount': '2400000', 'discount_amount': '0', 'total_amount': '2400000'},
                        'note': 'Demo gói tháng: 8 buổi, thứ 2 và thứ 5 hàng tuần, nhiều nhân viên.',
                    })
                    if booking.customer_id != customer.id or booking.service_id != service.id:
                        raise CommandError(f'Đơn {code} không khớp với bộ demo.')
                    if created:
                        Booking.objects.filter(pk=booking.pk).update(created_at=first - timedelta(days=2))
                    added_reviews = 0
                    for index in range(8):
                        start = first + timedelta(days=(index // 2) * 7 + (index % 2) * 3)
                        end = start + timedelta(hours=2)
                        completed = scenario == 'DONE' or index < 4
                        schedule, _ = BookingSchedule.objects.get_or_create(booking=booking, sequence_no=index + 1, defaults={
                            'scheduled_start': start, 'scheduled_end': end,
                            'actual_start': start if completed else None,
                            'actual_end': end if completed else None,
                            'status': BookingSchedule.Status.COMPLETED if completed else BookingSchedule.Status.PENDING,
                        })
                        assignment, assignment_created = BookingAssignment.objects.get_or_create(
                            schedule=schedule, worker=workers[index % 3], defaults={
                                'status': BookingAssignment.Status.ACCEPTED,
                                'responded_at': start - timedelta(days=1),
                            },
                        )
                        if assignment_created:
                            BookingAssignment.objects.filter(pk=assignment.pk).update(assigned_at=start - timedelta(days=2))
                        ensure_chat_for_assignment(assignment)
                        if index in (0, 2) and completed and not Review.objects.filter(assignment=assignment).exists():
                            review = create_review(customer=customer, assignment_id=assignment.pk,
                                                   rating=5 if index == 0 else 4,
                                                   comment=f'[Demo gói tháng] Buổi {index + 1}: nhân viên làm việc cẩn thận, đúng giờ.')
                            review_time = end + timedelta(hours=1)
                            Review.objects.filter(pk=review.pk).update(created_at=review_time, updated_at=review_time)
                            added_reviews += 1
                    results.append((phone, code, booking.pk, created, added_reviews))
        for phone, code, booking_id, created, reviews in results:
            self.stdout.write(f'{phone}: {code}, booking_id={booking_id}, mới={created}, thêm review={reviews}, 8 buổi.')
