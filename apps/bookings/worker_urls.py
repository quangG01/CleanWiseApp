from django.urls import path
from .worker_views import (
    WorkerAvailableScheduleListView,
    WorkerCancelAssignmentView,
    WorkerClaimScheduleView,
    WorkerMyScheduleListView,
)

from .views import (
    WorkerActiveAreaListView,
    WorkerWorkingAreaDetailView,
    WorkerWorkingAreaListCreateView,
)


urlpatterns = [
    # Worker schedules
    path(
        'schedules/available/',
        WorkerAvailableScheduleListView.as_view(),
        name='worker-schedule-available',
    ),
    path(
        'schedules/my-schedules/',
        WorkerMyScheduleListView.as_view(),
        name='worker-schedule-my',
    ),
    path(
        'schedules/<int:schedule_id>/claim/',
        WorkerClaimScheduleView.as_view(),
        name='worker-schedule-claim',
    ),
    path(
        'assignments/<int:assignment_id>/cancel/',
        WorkerCancelAssignmentView.as_view(),
        name='worker-assignment-cancel',
    ),

    # Worker working areas
    path(
        'areas/',
        WorkerActiveAreaListView.as_view(),
        name='worker-active-area-list',
    ),
    path(
        'working-areas/',
        WorkerWorkingAreaListCreateView.as_view(),
        name='worker-working-area-list-create',
    ),
    path(
        'working-areas/<int:pk>/',
        WorkerWorkingAreaDetailView.as_view(),
        name='worker-working-area-detail',
    ),
]
