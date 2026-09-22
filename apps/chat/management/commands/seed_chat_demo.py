"""Create isolated, repeatable chat data for manual development testing."""
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
from apps.services.models import Service
from apps.worker.models import BookingAssignment


class Command(BaseCommand):
    help = "Seed two demo accounts, two accepted schedules and chat messages in DEBUG only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-demo-passwords", action="store_true",
            help="Generate new passwords for the isolated demo users.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_chat_demo chỉ được chạy với cấu hình DEBUG.")

        passwords = {}
        with transaction.atomic():
            customer, created = User.objects.get_or_create(
                username="chat_demo_customer",
                defaults={
                    "email": "chat_demo_customer@example.invalid",
                    "first_name": "Khách",
                    "last_name": "Demo Chat",
                    "role": User.Role.CUSTOMER,
                    "phone_number": "0399999911",
                },
            )
            if created or options["reset_demo_passwords"]:
                passwords["customer"] = secrets.token_urlsafe(12)
                customer.set_password(passwords["customer"])
                customer.save(update_fields=["password"])
            if not customer.phone_number:
                customer.phone_number = "0399999911"
                customer.save(update_fields=["phone_number"])

            worker, created = User.objects.get_or_create(
                username="chat_demo_worker",
                defaults={
                    "email": "chat_demo_worker@example.invalid",
                    "first_name": "Nhân viên",
                    "last_name": "Demo Chat",
                    "role": User.Role.WORKER,
                    "phone_number": "0399999912",
                },
            )
            if created or options["reset_demo_passwords"]:
                passwords["worker"] = secrets.token_urlsafe(12)
                worker.set_password(passwords["worker"])
                worker.save(update_fields=["password"])
            if not worker.phone_number:
                worker.phone_number = "0399999912"
                worker.save(update_fields=["phone_number"])

            service, _ = Service.objects.get_or_create(
                code="CHAT_DEMO_SERVICE",
                defaults={
                    "section_code": "CHAT_DEMO",
                    "name": "Dọn dẹp nhà (demo chat)",
                    "description": "Dữ liệu thử nghiệm giao diện chat",
                    "form_schema": {"fields": []},
                    "pricing_config": {},
                },
            )
            WorkerProfile.objects.get_or_create(
                user=worker,
                defaults={
                    "status": WorkerProfile.Status.ACTIVE,
                    "registered_service": service,
                    "experience_years": 2,
                    "bio": "Nhân viên mẫu để thử nghiệm trò chuyện.",
                },
            )
            address, _ = CustomerAddress.objects.get_or_create(
                customer=customer,
                label="Chat demo",
                defaults={
                    "receiver_name": customer.get_full_name(),
                    "receiver_phone": "0900000000",
                    "address_line": "Địa chỉ mẫu cho thử nghiệm chat",
                    "city": "Hồ Chí Minh",
                },
            )
            booking, _ = Booking.objects.get_or_create(
                booking_code="CHAT-DEMO-001",
                defaults={
                    "customer": customer,
                    "service": service,
                    "address": address,
                    "service_data": {},
                    "status": Booking.Status.ASSIGNED,
                    "note": "Dữ liệu mẫu để thử nhắn tin",
                },
            )

            start = timezone.now() + timedelta(days=1)
            start = start.replace(hour=8, minute=0, second=0, microsecond=0)
            assignments = []
            for sequence in (1, 2):
                schedule, _ = BookingSchedule.objects.get_or_create(
                    booking=booking,
                    sequence_no=sequence,
                    defaults={
                        "scheduled_start": start + timedelta(days=sequence - 1),
                        "scheduled_end": start + timedelta(days=sequence - 1, hours=2),
                        "status": BookingSchedule.Status.PENDING,
                    },
                )
                assignment, _ = BookingAssignment.objects.get_or_create(
                    schedule=schedule,
                    worker=worker,
                    defaults={
                        "status": BookingAssignment.Status.ACCEPTED,
                        "responded_at": timezone.now(),
                    },
                )
                if assignment.status != BookingAssignment.Status.ACCEPTED:
                    raise CommandError(f"Assignment {assignment.id} không ở trạng thái ACCEPTED.")
                assignments.append(assignment)
                conversation = ensure_chat_for_assignment(assignment)

            for sender, message in (
                (worker, "Chào bạn, mình đã nhận lịch làm. Mình sẽ liên hệ trước khi đến."),
                (customer, "Cảm ơn bạn. Mình sẽ chuẩn bị trước giờ hẹn."),
                (worker, "Lịch tiếp theo chúng ta tiếp tục trao đổi trong cuộc trò chuyện này nhé."),
            ):
                ChatMessage.objects.get_or_create(
                    conversation=conversation,
                    sender=sender,
                    message=message,
                    message_type=ChatMessage.MessageType.TEXT,
                )

        self.stdout.write(self.style.SUCCESS(
            f"Chat demo: customer_id={customer.id}, worker_id={worker.id}, "
            f"booking_id={booking.id}, assignment_ids={[a.id for a in assignments]}, "
            f"conversation_id={conversation.id}"
        ))
        for role, password in passwords.items():
            phone = "0399999911" if role == "customer" else "0399999912"
            self.stdout.write(f"Demo {role}: {phone} / {password}")
        if not passwords:
            self.stdout.write("Demo accounts already exist; passwords unchanged.")
