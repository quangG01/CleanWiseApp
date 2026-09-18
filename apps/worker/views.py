from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsAdminRole, IsWorkerRole
from apps.bookings.models import BookingSchedule

from . import assignment_service
from .models import Area, BookingAssignment, WorkerWorkingArea
from .serializers import (
    AdminAssignWorkerSerializer,
    AreaSummarySerializer,
    CancelAssignmentSerializer,
    WorkerScheduleSerializer,
    WorkerWorkingAreaSerializer,
)

from .schemas import (
    WORKER_ACTIVE_AREA_SCHEMA,
    WORKER_WORKING_AREA_SCHEMA,
    WORKER_WORKING_AREA_DETAIL_SCHEMA,
    WORKER_AVAILABLE_SCHEDULE_SCHEMA,
    WORKER_MY_SCHEDULE_SCHEMA,
    WORKER_CLAIM_SCHEDULE_SCHEMA,
    WORKER_CANCEL_ASSIGNMENT_SCHEMA,
    ADMIN_ASSIGN_WORKER_SCHEMA,
)

def _prefetch_assignments(queryset):
    return queryset.prefetch_related(Prefetch('assignments', queryset=BookingAssignment.objects.filter(status=BookingAssignment.Status.ACCEPTED)))


@WORKER_ACTIVE_AREA_SCHEMA
class WorkerActiveAreaListView(generics.ListAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = AreaSummarySerializer

    def get_queryset(self):
        queryset = Area.objects.filter(is_active=True)
        city = self.request.query_params.get('city')
        search = self.request.query_params.get('search')
        if city:
            queryset = queryset.filter(city__iexact=city.strip())
        if search:
            queryset = queryset.filter(Q(name__icontains=search.strip()) | Q(city__icontains=search.strip()))
        return queryset


@WORKER_WORKING_AREA_SCHEMA
class WorkerWorkingAreaListCreateView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerWorkingAreaSerializer

    def get_queryset(self):
        return WorkerWorkingArea.objects.filter(worker=self.request.user).select_related('area').order_by('area__city', 'area__name')

    def get(self, request, *args, **kwargs):
        return Response({'message': 'Lấy danh sách khu vực làm việc thành công.', 'data': self.get_serializer(self.get_queryset(), many=True).data})

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        working_area = serializer.save()
        return Response({'message': 'Thêm khu vực làm việc thành công.', 'data': self.get_serializer(working_area).data}, status=status.HTTP_201_CREATED)


@WORKER_WORKING_AREA_DETAIL_SCHEMA
class WorkerWorkingAreaDetailView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerWorkingAreaSerializer

    def get_object(self):
        return get_object_or_404(WorkerWorkingArea.objects.select_related('area'), pk=self.kwargs['pk'], worker=self.request.user)

    def get(self, request, *args, **kwargs):
        return Response({'message': 'Lấy chi tiết khu vực làm việc thành công.', 'data': self.get_serializer(self.get_object()).data})

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        working_area = serializer.save()
        return Response({'message': 'Cập nhật khu vực làm việc thành công.', 'data': self.get_serializer(working_area).data})

    def delete(self, request, *args, **kwargs):
        self.get_object().delete()
        return Response({'message': 'Xóa khu vực làm việc thành công.'})


@WORKER_AVAILABLE_SCHEDULE_SCHEMA
class WorkerAvailableScheduleListView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerScheduleSerializer

    def get(self, request, *args, **kwargs):
        queryset = _prefetch_assignments(assignment_service.list_available_schedules_for_worker(request.user))
        return Response({'message': 'Lấy danh sách buổi làm việc khả dụng thành công.', 'data': self.get_serializer(queryset, many=True).data})


@WORKER_MY_SCHEDULE_SCHEMA
class WorkerMyScheduleListView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = WorkerScheduleSerializer

    def get(self, request, *args, **kwargs):
        queryset = _prefetch_assignments(assignment_service.list_my_schedules(request.user, schedule_status=request.query_params.get('status')))
        return Response({'message': 'Lấy danh sách buổi làm việc của tôi thành công.', 'data': self.get_serializer(queryset, many=True).data})


@WORKER_CLAIM_SCHEDULE_SCHEMA
class WorkerClaimScheduleView(APIView):
    permission_classes = [IsWorkerRole]

    def post(self, request, *args, **kwargs):
        assignment = assignment_service.claim_schedule(schedule_id=kwargs['schedule_id'], worker=request.user)
        return Response({'message': 'Nhận việc thành công.', 'data': {'assignment_id': assignment.id, 'schedule_id': assignment.schedule_id}}, status=status.HTTP_201_CREATED)


@WORKER_CANCEL_ASSIGNMENT_SCHEMA
class WorkerCancelAssignmentView(generics.GenericAPIView):
    permission_classes = [IsWorkerRole]
    serializer_class = CancelAssignmentSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment_service.cancel_assignment(assignment_id=kwargs['assignment_id'], worker=request.user, reason=serializer.validated_data['reason'])
        return Response({'message': 'Hủy nhận việc thành công.'})


@ADMIN_ASSIGN_WORKER_SCHEMA
class AdminAssignWorkerView(generics.GenericAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AdminAssignWorkerSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = assignment_service.admin_assign_worker(
            schedule_id=kwargs['schedule_id'],
            worker_id=serializer.validated_data['worker_id'],
            admin_user=request.user,
            note=serializer.validated_data.get('note'),
        )
        return Response({'message': 'Gán nhân viên thành công.', 'data': {'assignment_id': assignment.id}}, status=status.HTTP_201_CREATED)
