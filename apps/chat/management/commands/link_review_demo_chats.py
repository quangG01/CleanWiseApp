"""Repair chat links for accepted assignments created by review demo seeds."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.chat.service import ensure_chat_for_assignment
from apps.worker.models import BookingAssignment


class Command(BaseCommand):
    help = 'Bổ sung chat còn thiếu cho các đơn demo đánh giá (DEBUG only).'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Chỉ chạy lệnh với cấu hình DEBUG.')
        with transaction.atomic():
            assignments = BookingAssignment.objects.filter(
                Q(schedule__booking__booking_code__startswith='REVIEW-FILTER-')
                | Q(schedule__booking__booking_code__startswith='REVIEW-CREATE-DEMO-')
                | Q(schedule__booking__booking_code__startswith='MONTH-REVIEW-'),
                status=BookingAssignment.Status.ACCEPTED,
                chat_link__isnull=True,
            ).order_by('pk')
            linked = 0
            conversations = set()
            for assignment in assignments:
                conversation = ensure_chat_for_assignment(assignment)
                conversations.add(conversation.pk)
                linked += 1
        self.stdout.write(self.style.SUCCESS(
            f'Đã bổ sung {linked} liên kết phân công trong {len(conversations)} cuộc trò chuyện.'
        ))
