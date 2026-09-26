# apps/complaints/views.py

from apps.common.permissions import (
    IsAdminOrCustomerRole,
    IsAdminRole,
    IsCustomerRole,
)

from rest_framework import generics, status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Complaint, ComplaintIssueType
from .permissions import IsComplaintOwnerOrAdmin
from .schemas import (
    COMPLAINT_CANCEL_SCHEMA,
    COMPLAINT_CUSTOMER_SCHEMA,
    COMPLAINT_DETAIL_CUSTOMER_SCHEMA,
    COMPLAINT_ISSUE_TYPE_SCHEMA,
    COMPLAINT_RESOLVE_SCHEMA,
)
from .serializers import (
    ComplaintCancelSerializer,
    ComplaintCreateSerializer,
    ComplaintDetailSerializer,
    ComplaintIssueTypeSerializer,
    ComplaintListSerializer,
    ComplaintResolveSerializer,
    ComplaintAttachmentSerializer
)

from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from .models import Complaint, ComplaintAttachment, ComplaintIssueType

ALLOWED_IMAGE_TYPES = ('image/jpeg', 'image/png', 'image/webp')
MAX_IMAGE_SIZE = 5 * 1024 * 1024

@COMPLAINT_ISSUE_TYPE_SCHEMA
class ComplaintIssueTypeListView(generics.ListAPIView):
    """
    Customer lấy danh sách loại sự cố để lựa chọn.
    """

    permission_classes = [
        IsCustomerRole,
    ]

    serializer_class = ComplaintIssueTypeSerializer

    def get_queryset(self):
        queryset = ComplaintIssueType.objects.filter(
            is_active=True,
        )

        stage = self.request.query_params.get('stage')

        if stage:
            queryset = queryset.filter(
                stage__in=[
                    stage,
                    ComplaintIssueType.Stage.ANY,
                ]
            )

        return queryset


@COMPLAINT_CUSTOMER_SCHEMA
class ComplaintListCreateView(generics.ListCreateAPIView):
    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsCustomerRole()]
        return [IsAdminOrCustomerRole()]

    def get_queryset(self):
        queryset = Complaint.objects.select_related(
            'customer', 'booking', 'issue_type', 'resolved_by', 'schedule',
        ).prefetch_related('attachments')

        schedule_filter = self.request.query_params.get('schedule')

        if self.request.user.role == 'ADMIN' or self.request.user.is_superuser:
            status_filter = self.request.query_params.get('status')
            stage_filter = self.request.query_params.get('stage')
            issue_type_filter = self.request.query_params.get('issue_type')

            if status_filter:
                queryset = queryset.filter(status=status_filter)
            if stage_filter:
                queryset = queryset.filter(stage=stage_filter)
            if issue_type_filter:
                queryset = queryset.filter(issue_type_id=issue_type_filter)
            if schedule_filter:
                queryset = queryset.filter(schedule_id=schedule_filter)
            return queryset

        queryset = queryset.filter(customer=self.request.user)
        if schedule_filter:
            queryset = queryset.filter(schedule_id=schedule_filter)
        return queryset

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ComplaintCreateSerializer
        return ComplaintListSerializer

    def create(self, request, *args, **kwargs):
        files = request.FILES.getlist('attachments')

        for f in files:
            if f.content_type not in ALLOWED_IMAGE_TYPES:
                return Response({'attachments': [f'File {f.name} không đúng định dạng ảnh.']}, status=400)
            if f.size > MAX_IMAGE_SIZE:
                return Response({'attachments': [f'File {f.name} vượt quá 5MB.']}, status=400)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            complaint = serializer.save()
            for f in files:
                ComplaintAttachment.objects.create(
                    complaint=complaint, file=f, file_type=f.content_type or '',
                )

        return Response(
            ComplaintDetailSerializer(complaint).data,
            status=status.HTTP_201_CREATED,
        )


@COMPLAINT_DETAIL_CUSTOMER_SCHEMA
class ComplaintDetailView(generics.RetrieveAPIView):
    serializer_class = ComplaintDetailSerializer

    permission_classes = [
        IsAdminOrCustomerRole,
        IsComplaintOwnerOrAdmin,
    ]

    def get_queryset(self):
        return Complaint.objects.select_related(
            'customer',
            'booking',
            'issue_type',
            'resolved_by',
        ).prefetch_related(
            'attachments',
        )


@COMPLAINT_CANCEL_SCHEMA
class ComplaintCancelView(APIView):
    permission_classes = [
        IsCustomerRole,
    ]

    def post(self, request, pk):
        complaint = get_object_or_404(
            Complaint,
            pk=pk,
        )

        if complaint.customer_id != request.user.id:
            return Response(
                {
                    'detail': 'Không có quyền.'
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if complaint.status != Complaint.Status.PENDING:
            return Response(
                {
                    'detail': (
                        'Chỉ hủy được khi khiếu nại '
                        'đang ở trạng thái chờ xử lý.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ComplaintCancelSerializer(
            data={},
            context={
                'complaint': complaint,
                'request': request,
            },
        )

        serializer.is_valid(
            raise_exception=True,
        )

        serializer.save()

        return Response(
            ComplaintDetailSerializer(
                complaint,
            ).data
        )


@COMPLAINT_RESOLVE_SCHEMA
class ComplaintResolveView(APIView):
    permission_classes = [
        IsAdminRole,
    ]

    def post(self, request, pk):
        complaint = get_object_or_404(
            Complaint,
            pk=pk,
        )

        serializer = ComplaintResolveSerializer(
            complaint,
            data=request.data,
            context={
                'request': request,
            },
        )

        serializer.is_valid(
            raise_exception=True,
        )

        serializer.save()

        return Response(
            ComplaintDetailSerializer(
                complaint,
            ).data
        )
        

class ComplaintAttachmentUploadView(generics.CreateAPIView):
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = ComplaintAttachmentSerializer
    permission_classes = [IsCustomerRole]

    def perform_create(self, serializer):
        complaint = get_object_or_404(Complaint, pk=self.kwargs['pk'], customer=self.request.user)
        serializer.save(complaint=complaint)