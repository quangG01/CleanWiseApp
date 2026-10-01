from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db.models import Case, IntegerField, OuterRef, Subquery, Value, When
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsAdminRole
from apps.worker.models import BookingAssignment, WorkerAvailability
from .admin_serializers import AdminAddressSerializer, AdminUserSummarySerializer, AdminScheduleImageSerializer

VIETNAM = ZoneInfo('Asia/Ho_Chi_Minh')


class ScheduleRangeSerializer(serializers.Serializer):
    # Monday = 0, Sunday = 6 for availability; dates use Vietnam time.
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)

    def validate(self, attrs):
        today = timezone.localdate(timezone=VIETNAM)
        start = attrs.get('start', today - timedelta(days=today.weekday()))
        end = attrs.get('end', start + timedelta(days=7))
        if not 0 < (end - start).days <= 31:
            raise serializers.ValidationError('Khoảng ngày phải từ 1 đến 31 ngày; ngày kết thúc không bao gồm trong lịch.')
        return {'start': start, 'end': end}


class AdminWorkerScheduleView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request, worker_id):
        worker = get_object_or_404(get_user_model(), pk=worker_id, role='WORKER')
        params = ScheduleRangeSerializer(data={
            key: request.query_params[key]
            for key in ('start', 'end') if key in request.query_params
        })
        params.is_valid(raise_exception=True)
        start, end = params.validated_data['start'], params.validated_data['end']
        start_at = datetime.combine(start, time.min, tzinfo=VIETNAM)
        end_at = datetime.combine(end, time.min, tzinfo=VIETNAM)
        # One effective assignment per schedule: accepted first, then newest pending.
        effective = BookingAssignment.objects.filter(
            schedule_id=OuterRef('schedule_id'), status__in=['PENDING', 'ACCEPTED'],
        ).order_by(
            Case(When(status='ACCEPTED', then=Value(0)), default=Value(1), output_field=IntegerField()),
            '-assigned_at', '-id',
        )
        assignments = BookingAssignment.objects.filter(
            worker=worker, pk=Subquery(effective.values('pk')[:1]),
            schedule__scheduled_start__lt=end_at, schedule__scheduled_end__gt=start_at,
        ).select_related(
            'schedule__booking__customer', 'schedule__booking__service', 'schedule__booking__address',
        ).prefetch_related('schedule__images').order_by('schedule__scheduled_start', 'id')
        items = []
        for assignment in assignments:
            schedule, booking = assignment.schedule, assignment.schedule.booking
            items.append({
                'id': assignment.id, 'schedule_id': schedule.id, 'booking_id': booking.id,
                'booking_code': booking.booking_code, 'sequence_no': schedule.sequence_no,
                'service_name': booking.service.name,
                'customer': AdminUserSummarySerializer(booking.customer).data,
                'address': AdminAddressSerializer(booking.address).data,
                'scheduled_start': schedule.scheduled_start, 'scheduled_end': schedule.scheduled_end,
                'actual_start': schedule.actual_start, 'actual_end': schedule.actual_end,
                'assignment_status': assignment.status, 'assignment_status_label': assignment.get_status_display(),
                'status': schedule.status, 'status_label': schedule.get_status_display(),
                'note': schedule.note, 'completion_note': schedule.completion_note,
                'cancel_reason': schedule.cancel_reason,
                'images': AdminScheduleImageSerializer(schedule.images.all(), many=True).data,
            })
        availability = list(WorkerAvailability.objects.filter(worker=worker, is_active=True).values(
            'id', 'weekday', 'start_time', 'end_time',
        ))
        return Response({'data': {
            'worker_id': worker.id, 'start': start, 'end': end,
            'timezone': 'Asia/Ho_Chi_Minh', 'availability': availability, 'assignments': items,
        }})
