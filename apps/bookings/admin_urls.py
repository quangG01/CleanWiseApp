from django.urls import path

from .views import AdminVoucherByCodeDetailView, AdminVoucherDetailView, AdminVoucherListCreateView, AdminAssignWorkerView


urlpatterns = [
    path('vouchers/', AdminVoucherListCreateView.as_view(), name='admin-voucher-list-create'),
    path('vouchers/by-code/<str:code>/', AdminVoucherByCodeDetailView.as_view(), name='admin-voucher-detail-by-code'),
    path('vouchers/<int:pk>/', AdminVoucherDetailView.as_view(), name='admin-voucher-detail'),
    path('schedules/<int:schedule_id>/assign/', AdminAssignWorkerView.as_view(), name='admin-schedule-assign'),
]
