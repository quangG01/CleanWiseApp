from django.urls import path

from .views import (
    WorkerActiveAreaListView,
    WorkerAvailableScheduleListView,
    WorkerCancelAssignmentView,
    WorkerClaimScheduleView,
    WorkerMyScheduleListView,
    WorkerWorkingAreaView,
    WorkerCheckInView,
    WorkerCheckOutView,
    WorkerScheduleImageUploadView
)


urlpatterns = [
    path('schedules/available/', WorkerAvailableScheduleListView.as_view(), name='worker-schedule-available'),
    path('schedules/my-schedules/', WorkerMyScheduleListView.as_view(), name='worker-schedule-my'),
    path('schedules/<int:schedule_id>/claim/', WorkerClaimScheduleView.as_view(), name='worker-schedule-claim'),
    path('assignments/<int:assignment_id>/cancel/', WorkerCancelAssignmentView.as_view(), name='worker-assignment-cancel'),
    path('areas/', WorkerActiveAreaListView.as_view(), name='worker-active-area-list'),
    path('working-areas/', WorkerWorkingAreaView.as_view(), name='worker-working-area'),
    path('schedules/<int:schedule_id>/check-in/', WorkerCheckInView.as_view(), name='worker-schedule-check-in'),
    path('schedules/<int:schedule_id>/check-out/', WorkerCheckOutView.as_view(), name='worker-schedule-check-out'),
    path('schedules/<int:schedule_id>/images/', WorkerScheduleImageUploadView.as_view(), name='worker-schedule-image-upload'),
]