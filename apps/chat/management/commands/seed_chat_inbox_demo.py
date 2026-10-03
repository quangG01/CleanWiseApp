"""Seed isolated inbox scenarios without automatic assignment chat messages."""
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.addresses.models import CustomerAddress
from apps.authentication.models import User, WorkerProfile
from apps.bookings.models import Booking, BookingSchedule
from apps.chat.models import ChatMessage
from apps.chat.service import ensure_chat_for_assignment
from apps.notifications.models import Notification
from apps.services.models import Service
from apps.worker.models import Area, BookingAssignment, WorkerWorkingArea


class Command(BaseCommand):
    help = 'Tạo một khách, hai nhân viên demo: chat có tin nhắn và chat trống (DEBUG only).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset-demo-passwords', action='store_true',
            help='Cấp lại mật khẩu cho ba tài khoản thuộc bộ demo này.',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Lệnh này chỉ chạy với cấu hình DEBUG.')
        passwords = {}
        scenarios = []
        with transaction.atomic():
            service = Service.objects.filter(is_active=True).first()
            area = Area.objects.filter(is_active=True).first()
            if service is None or area is None:
                raise CommandError('Cần có ít nhất một dịch vụ và một Area đang hoạt động.')
            users = []
            for username, phone, role, first_name in (
                ('chat_inbox_demo_customer', '0399999921', User.Role.CUSTOMER, 'Khách Chat'),
                ('chat_inbox_demo_worker', '0399999922', User.Role.WORKER, 'Nhân viên có tin nhắn'),
                ('chat_inbox_demo_empty_worker', '0399999923', User.Role.WORKER, 'Nhân viên chat trống'),
            ):
                user, created = User.objects.get_or_create(username=username, defaults={
                    'email': f'{username}@example.invalid', 'phone_number': phone,
                    'role': role, 'first_name': first_name, 'last_name': 'Demo',
                })
                if user.role != role or user.phone_number != phone:
                    raise CommandError(f'Tài khoản {username} không khớp với bộ demo.')
                if created or options['reset_demo_passwords']:
                    password = secrets.token_urlsafe(12)
                    user.set_password(password)
                    user.save(update_fields=['password'])
                    passwords[phone] = password
                users.append(user)
            customer, worker, empty_worker = users
            for person in (worker, empty_worker):
                WorkerProfile.objects.get_or_create(user=person, defaults={
                    'status': WorkerProfile.Status.ACTIVE, 'registered_service': service,
                    'bio': 'Tài khoản demo để kiểm thử chat.', 'experience_years': 2,
                })
                WorkerWorkingArea.objects.get_or_create(worker=person, area=area)
            address, _ = CustomerAddress.objects.get_or_create(
                customer=customer, label='Demo chat inbox', defaults={
                    'receiver_name': customer.get_full_name(), 'receiver_phone': customer.phone_number,
                    'address_line': 'Địa chỉ demo kiểm thử chat', 'city': area.city,
                    'province_code': area.province_code, 'ward_code': area.ward_code,
                },
            )
            start = (timezone.localtime() + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
            for person, code, count in (
                (worker, 'CHAT-INBOX-DEMO-001', 2),
                (empty_worker, 'CHAT-INBOX-DEMO-002', 1),
            ):
                booking, _ = Booking.objects.get_or_create(booking_code=code, defaults={
                    'customer': customer, 'service': service, 'address': address,
                    'service_data': {}, 'status': Booking.Status.ASSIGNED,
                    'payment_status': Booking.PaymentStatus.PAID,
                    'subtotal_amount': 300000, 'total_amount': 300000,
                    'note': 'Dữ liệu demo kiểm thử chat không có tin thông báo tự động.',
                })
                if booking.customer_id != customer.id:
                    raise CommandError(f'Booking {code} không thuộc khách demo.')
                schedule_ids = []
                for sequence in range(1, count + 1):
                    scheduled_start = start + timedelta(days=sequence - 1)
                    schedule, _ = BookingSchedule.objects.get_or_create(
                        booking=booking, sequence_no=sequence, defaults={
                            'scheduled_start': scheduled_start,
                            'scheduled_end': scheduled_start + timedelta(hours=2),
                            'status': BookingSchedule.Status.PENDING,
                        },
                    )
                    assignment, _ = BookingAssignment.objects.get_or_create(
                        schedule=schedule, worker=person, defaults={
                            'status': BookingAssignment.Status.ACCEPTED,
                            'responded_at': timezone.now(),
                        },
                    )
                    conversation = ensure_chat_for_assignment(assignment)
                    schedule_ids.append(schedule.id)
                for user, message in (
                    (customer, f'{person.get_full_name()} đã nhận lịch {code}. Bạn có thể liên hệ trong mục Tin nhắn.'),
                    (person, f'Bạn đã nhận lịch {code} của khách {customer.get_full_name()}.'),
                ):
                    Notification.objects.get_or_create(
                        user=user, related_booking=booking, title='Lịch demo đã được nhận',
                        defaults={'type': Notification.Type.ASSIGNMENT, 'message': message},
                    )
                if person == worker:
                    for sender, text in (
                        (worker, 'Chào bạn, ngày mai mình sẽ đến đúng giờ hẹn nhé.'),
                        (customer, 'Cảm ơn bạn, mình sẽ chuẩn bị trước giờ hẹn.'),
                        (worker, 'Bạn cho mình biết vị trí đỗ xe khi đến nhé.'),
                    ):
                        ChatMessage.objects.get_or_create(
                            conversation=conversation, sender=sender, message=text,
                            message_type=ChatMessage.MessageType.TEXT,
                        )
                scenarios.append((code, conversation.id, schedule_ids, conversation.messages.count()))
        self.stdout.write(self.style.SUCCESS('Đã tạo dữ liệu demo chat inbox.'))
        for code, conversation_id, schedule_ids, message_count in scenarios:
            self.stdout.write(f'{code}: conversation_id={conversation_id}, schedule_ids={schedule_ids}, messages={message_count}')
        for user in users:
            password = passwords.get(user.phone_number, '(đã có tài khoản, giữ mật khẩu cũ)')
            self.stdout.write(f'{user.get_full_name()}: {user.phone_number} / {password}')
