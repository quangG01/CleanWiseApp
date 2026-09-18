from django.urls import path

from .views import (
    WorkerActiveAreaListView,
    WorkerAvailableScheduleListView,
    WorkerCancelAssignmentView,
    WorkerClaimScheduleView,
    WorkerMyScheduleListView,
    WorkerWorkingAreaDetailView,
    WorkerWorkingAreaListCreateView,
)


urlpatterns = [
    path('schedules/available/', WorkerAvailableScheduleListView.as_view(), name='worker-schedule-available'),
    path('schedules/my-schedules/', WorkerMyScheduleListView.as_view(), name='worker-schedule-my'),
    path('schedules/<int:schedule_id>/claim/', WorkerClaimScheduleView.as_view(), name='worker-schedule-claim'),
    path('assignments/<int:assignment_id>/cancel/', WorkerCancelAssignmentView.as_view(), name='worker-assignment-cancel'),
    path('areas/', WorkerActiveAreaListView.as_view(), name='worker-active-area-list'),
    path('working-areas/', WorkerWorkingAreaListCreateView.as_view(), name='worker-working-area-list-create'),
    path('working-areas/<int:pk>/', WorkerWorkingAreaDetailView.as_view(), name='worker-working-area-detail'),
]
