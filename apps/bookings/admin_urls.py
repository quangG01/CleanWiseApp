from django.urls import path

from .admin_views import (
    AdminAvailableWorkerListView,
    AdminBookingCancelView,
    AdminBookingDetailView,
    AdminBookingListCreateView,
    AdminBookingSummaryView,
    AdminBookingTimelineView,
    AdminBulkAssignView,
    AdminCustomerSearchView,
    AdminScheduleAssignView,
    AdminScheduleCompleteView,
    AdminScheduleUnassignView,
    AdminScheduleUpdateView,
)

urlpatterns = [
    path('bookings/', AdminBookingListCreateView.as_view(), name='admin-booking-list-create'),
    path('bookings/summary/', AdminBookingSummaryView.as_view(), name='admin-booking-summary'),
    path('bookings/<int:pk>/', AdminBookingDetailView.as_view(), name='admin-booking-detail'),
    path('bookings/<int:pk>/cancel/', AdminBookingCancelView.as_view(), name='admin-booking-cancel'),
    path('bookings/<int:pk>/timeline/', AdminBookingTimelineView.as_view(), name='admin-booking-timeline'),
    path('schedules/bulk-assign/', AdminBulkAssignView.as_view(), name='admin-schedule-bulk-assign'),
    path('schedules/<int:pk>/', AdminScheduleUpdateView.as_view(), name='admin-schedule-update'),
    path('schedules/<int:pk>/available-workers/', AdminAvailableWorkerListView.as_view(), name='admin-schedule-workers'),
    path('schedules/<int:pk>/assign/', AdminScheduleAssignView.as_view(), name='admin-booking-schedule-assign'),
    path('schedules/<int:pk>/unassign/', AdminScheduleUnassignView.as_view(), name='admin-schedule-unassign'),
    path('schedules/<int:pk>/complete/', AdminScheduleCompleteView.as_view(), name='admin-schedule-complete'),
    path('customers/search/', AdminCustomerSearchView.as_view(), name='admin-customer-search'),
]
