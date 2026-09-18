from django.urls import path

from .worker_views import (
    WorkerAvailableScheduleListView,
    WorkerCancelAssignmentView,
    WorkerClaimScheduleView,
    WorkerMyScheduleListView,
)

urlpatterns = [
    path('schedules/available/', WorkerAvailableScheduleListView.as_view(), name='worker-schedule-available'),
    path('schedules/my-schedules/', WorkerMyScheduleListView.as_view(), name='worker-schedule-my'),
    path('schedules/<int:schedule_id>/claim/', WorkerClaimScheduleView.as_view(), name='worker-schedule-claim'),
    path('assignments/<int:assignment_id>/cancel/', WorkerCancelAssignmentView.as_view(), name='worker-assignment-cancel'),
]