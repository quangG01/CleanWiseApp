from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsWorkerRole
from apps.notifications.realtime import push_complaint_changed
from apps.notifications.services import create_notification_with_push

from .attachments import MAX_COMPLAINT_ATTACHMENTS, uploaded_complaint_images, validate_complaint_image
from .models import Complaint, ComplaintWorkerStatement, WorkerStatementAttachment


class WorkerStatementAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkerStatementAttachment
        fields = ['id', 'file']


class WorkerStatementSerializer(serializers.ModelSerializer):
    complaint_code = serializers.CharField(source='complaint.code')
    booking_code = serializers.CharField(source='complaint.booking.booking_code')
    sequence = serializers.IntegerField(source='complaint.schedule.sequence_no', default=None)
    status = serializers.CharField()
    attachments = WorkerStatementAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = ComplaintWorkerStatement
        fields = ['id', 'complaint_code', 'booking_code', 'sequence', 'status',
                  'request_message', 'due_at', 'response', 'submitted_at', 'attachments']
        read_only_fields = fields


def request_statement(complaint, message, due_at):
    worker = complaint.worker
    if not complaint.schedule_id or not worker or not worker.is_active or worker.role != worker.Role.WORKER:
        raise serializers.ValidationError('Cần có nhân viên đang hoạt động và buổi làm gốc.')
    if due_at <= timezone.now():
        raise serializers.ValidationError({'worker_due_at': 'Hạn phản hồi phải ở trong tương lai.'})
    _, created = ComplaintWorkerStatement.objects.get_or_create(
        complaint=complaint, defaults={'worker': worker, 'request_message': message, 'due_at': due_at},
    )
    if not created:
        raise serializers.ValidationError('Hồ sơ đã có yêu cầu giải trình.')
    from apps.notifications.models import Notification

    create_notification_with_push(
        worker, 'Yêu cầu giải trình khiếu nại',
        f'Đơn {complaint.booking.booking_code}, buổi {complaint.schedule.sequence_no}. '
        f'Hạn phản hồi {timezone.localtime(due_at):%H:%M %d/%m/%Y}.',
        type=Notification.Type.COMPLAINT, related_booking=complaint.booking,
        related_schedule=complaint.schedule, target='worker_statement',
    )


class WorkerStatementListView(generics.ListAPIView):
    serializer_class = WorkerStatementSerializer
    permission_classes = [IsWorkerRole]

    def get_queryset(self):
        return ComplaintWorkerStatement.objects.filter(worker=self.request.user).select_related(
            'complaint__booking', 'complaint__schedule',
        ).prefetch_related('attachments').order_by('-pk')


class StatementReplySerializer(serializers.Serializer):
    response = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    attachments = serializers.ListField(
        child=serializers.FileField(validators=[validate_complaint_image]),
        max_length=MAX_COMPLAINT_ATTACHMENTS, required=False,
    )

    def validate(self, data):
        if not data.get('response') and not data.get('attachments'):
            raise serializers.ValidationError({'response': 'Vui lòng nhập giải trình hoặc thêm ảnh minh chứng.'})
        return data


class WorkerStatementReplyView(APIView):
    permission_classes = [IsWorkerRole]

    @transaction.atomic
    def post(self, request, pk):
        statement = get_object_or_404(ComplaintWorkerStatement, pk=pk, worker=request.user)
        complaint = Complaint.objects.select_for_update().get(pk=statement.complaint_id)
        statement.complaint = complaint
        statement.refresh_from_db(fields=['response', 'submitted_at'])
        if statement.status != 'OPEN':
            raise serializers.ValidationError('Yêu cầu đã hết hạn, đã gửi hoặc đã đóng.')
        body = StatementReplySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with uploaded_complaint_images(body.validated_data.get('attachments', []), public_id_prefix='worker_statement') as uploads:
            WorkerStatementAttachment.objects.bulk_create([
                WorkerStatementAttachment(statement=statement, **upload) for upload in uploads
            ])
            statement.response = body.validated_data.get('response', '')
            statement.submitted_at = timezone.now()
            statement.save(update_fields=['response', 'submitted_at'])
        push_complaint_changed(complaint.pk)
        return Response(WorkerStatementSerializer(statement).data)
