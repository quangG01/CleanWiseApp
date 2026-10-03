"""Create repeatable, isolated reviews for exercising customer filters."""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.addresses.models import CustomerAddress
from apps.authentication.models import User, WorkerProfile
from apps.bookings.models import Booking, BookingSchedule
from apps.chat.service import ensure_chat_for_assignment
from apps.reviews.models import Review
from apps.reviews.review_service import create_review
from apps.services.models import Service
from apps.worker.models import BookingAssignment


class Command(BaseCommand):
    help = 'Thêm 15 review đa dạng cho mỗi khách được chỉ định (chỉ DEBUG).'

    def add_arguments(self, parser):
        parser.add_argument('--customer-phone', action='append', required=True)

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Lệnh chỉ được chạy trong cấu hình DEBUG.')
        results = []
        with transaction.atomic():
            customers = []
            for phone in dict.fromkeys(options['customer_phone']):
                customer = User.objects.filter(phone_number=phone, role=User.Role.CUSTOMER).first()
                if not customer:
                    raise CommandError(f'Không tìm thấy khách hàng {phone}.')
                customers.append(customer)
            services = []
            for code in ('HOME_CLEANING_HOURLY', 'HOME_MOVING', 'UPHOLSTERY_CLEANING'):
                service = Service.objects.filter(code=code, is_active=True).first()
                if not service:
                    raise CommandError(f'Không tìm thấy dịch vụ đang hoạt động {code}.')
                services.append(service)
            workers = []
            for index, (first_name, last_name) in enumerate((
                ('Minh', 'Nguyễn'), ('Ngọc', 'Trần'), ('Bảo', 'Lê'),
            ), start=1):
                username = f'review_filter_demo_worker_{index}'
                phone = f'039999994{index}'
                worker, created = User.objects.get_or_create(username=username, defaults={
                    'phone_number': phone, 'role': User.Role.WORKER,
                    'email': f'{username}@example.invalid',
                    'first_name': first_name, 'last_name': last_name,
                })
                if worker.role != User.Role.WORKER or worker.phone_number != phone:
                    raise CommandError(f'Tài khoản {username} không khớp bộ demo.')
                if created:
                    worker.set_unusable_password()
                    worker.save(update_fields=['password'])
                WorkerProfile.objects.get_or_create(user=worker, defaults={
                    'status': WorkerProfile.Status.ACTIVE,
                    'registered_service': services[index - 1],
                    'bio': 'Nhân viên demo bộ lọc đánh giá.', 'experience_years': 2,
                })
                workers.append(worker)
            now = timezone.now()
            rating_comments = {
                1: 'Chưa hài lòng, cần cải thiện chất lượng và thời gian phục vụ.',
                2: 'Còn nhiều điểm chưa đạt, mong nhân viên chú ý hơn.',
                3: 'Dịch vụ ở mức ổn, có thể cải thiện thêm.',
                4: 'Làm việc cẩn thận, thái độ tốt và đúng giờ.',
                5: 'Rất hài lòng, chuyên nghiệp, đúng giờ và hỗ trợ nhiệt tình.',
            }
            for customer in customers:
                address = CustomerAddress.objects.filter(customer=customer).first()
                if address is None:
                    raise CommandError(f'Khách {customer.phone_number} cần có địa chỉ trước khi seed.')
                added = 0
                for index in range(15):
                    service = services[index % 3]
                    worker = workers[(index // 3) % 3]
                    rating = index % 5 + 1
                    age = (1, 7, 20, 35, 100)[(index + index // 5) % 5]
                    review_time = now - timedelta(days=age, minutes=index)
                    end = review_time - timedelta(hours=1)
                    start = end - timedelta(hours=2)
                    code = f'REVIEW-FILTER-{customer.id}-{index + 1:02d}'
                    booking, booking_created = Booking.objects.get_or_create(booking_code=code, defaults={
                        'customer': customer, 'service': service, 'address': address,
                        'service_data': {}, 'status': Booking.Status.COMPLETED,
                        'payment_status': Booking.PaymentStatus.PAID,
                        'subtotal_amount': 300000, 'total_amount': 300000,
                        'note': 'Dữ liệu demo kiểm thử bộ lọc đánh giá.',
                    })
                    if booking.customer_id != customer.id or booking.service_id != service.id:
                        raise CommandError(f'Đơn {code} không khớp bộ demo.')
                    if booking_created:
                        Booking.objects.filter(pk=booking.pk).update(created_at=start - timedelta(days=1))
                    schedule, _ = BookingSchedule.objects.get_or_create(booking=booking, sequence_no=1, defaults={
                        'scheduled_start': start, 'scheduled_end': end,
                        'actual_start': start, 'actual_end': end,
                        'status': BookingSchedule.Status.COMPLETED,
                        'completion_note': 'Hoàn thành buổi demo bộ lọc review.',
                    })
                    assignment, assignment_created = BookingAssignment.objects.get_or_create(schedule=schedule, worker=worker, defaults={
                        'status': BookingAssignment.Status.ACCEPTED,
                        'responded_at': start - timedelta(hours=1),
                    })
                    if assignment_created:
                        BookingAssignment.objects.filter(pk=assignment.pk).update(assigned_at=start - timedelta(hours=2))
                    ensure_chat_for_assignment(assignment)
                    if not Review.objects.filter(assignment=assignment).exists():
                        review = create_review(
                            customer=customer, assignment_id=assignment.id, rating=rating,
                            comment=f'[Demo bộ lọc] {service.name}. {rating_comments[rating]}',
                        )
                        Review.objects.filter(pk=review.pk).update(created_at=review_time, updated_at=review_time)
                        added += 1
                results.append((customer.phone_number, added))
        for phone, added in results:
            self.stdout.write(self.style.SUCCESS(f'{phone}: thêm {added} review; bộ demo có 15 review.'))
        self.stdout.write('Nhân viên: Nguyễn Minh, Trần Ngọc, Lê Bảo. Đủ 1–5 sao, mốc 1/7/20/35/100 ngày trước.')
        self.stdout.write('Dịch vụ: ' + ', '.join(service.name for service in services))
