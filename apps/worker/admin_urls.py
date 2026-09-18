from django.urls import path

from .views import AdminAssignWorkerView


urlpatterns = [
    path('schedules/<int:schedule_id>/assign/', AdminAssignWorkerView.as_view(), name='admin-schedule-assign'),
]
