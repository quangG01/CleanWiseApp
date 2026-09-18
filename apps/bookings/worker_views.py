from django.db.models import Prefetch
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsWorkerRole

from . import assignment_service
from .models import BookingAssignment
from .schemas import BOOKING_WORKER_SCHEMA, BOOKING_WORKER_ASSIGNMENT_SCHEMA
from .worker_serializers import CancelAssignmentSerializer, WorkerScheduleSerializer


def _prefetch_assignments(qs):
    return qs.prefetch_related(
        Prefetch(
            'assignments',
            queryset=BookingAssignment.objects.filter(status=BookingAssignment.Status.ACCEPTED),
        ),
    )


@BOOKING_WORKER_SCHEMA
class WorkerAvailableScheduleListView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerScheduleSerializer

    def get(self, request, *args, **kwargs):
        qs = _prefetch_assignments(assignment_service.list_available_schedules_for_worker(request.user))
        return Response({
            'message': 'Lấy danh sách buổi làm việc khả dụng thành công.',
            'data': self.get_serializer(qs, many=True).data,
        })


class WorkerMyScheduleListView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerScheduleSerializer

    def get(self, request, *args, **kwargs):
        schedule_status = request.query_params.get('status')
        qs = _prefetch_assignments(
            assignment_service.list_my_schedules(request.user, schedule_status=schedule_status)
        )
        return Response({
            'message': 'Lấy danh sách buổi làm việc của tôi thành công.',
            'data': self.get_serializer(qs, many=True).data,
        })


@BOOKING_WORKER_SCHEMA
class WorkerClaimScheduleView(APIView):
    permission_classes = [IsWorkerRole]

    def post(self, request, *args, **kwargs):
        assignment = assignment_service.claim_schedule(
            schedule_id=kwargs['schedule_id'], worker=request.user,
        )
        return Response({
            'message': 'Nhận việc thành công.',
            'data': {'assignment_id': assignment.id, 'schedule_id': assignment.schedule_id},
        }, status=status.HTTP_201_CREATED)


@BOOKING_WORKER_ASSIGNMENT_SCHEMA
class WorkerCancelAssignmentView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = CancelAssignmentSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment_service.cancel_assignment(
            assignment_id=kwargs['assignment_id'],
            worker=request.user,
            reason=serializer.validated_data['reason'],
        )
        return Response({'message': 'Hủy nhận việc thành công.'})