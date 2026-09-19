from django.urls import path

from .views import AdminVoucherAssignView, AdminVoucherByCodeDetailView, AdminVoucherDetailView, AdminVoucherListCreateView


urlpatterns = [
    path('vouchers/', AdminVoucherListCreateView.as_view(), name='admin-voucher-list-create'),
    path('vouchers/assign/', AdminVoucherAssignView.as_view(), name='admin-voucher-assign'),
    path('vouchers/by-code/<str:code>/', AdminVoucherByCodeDetailView.as_view(), name='admin-voucher-detail-by-code'),
    path('vouchers/<int:pk>/', AdminVoucherDetailView.as_view(), name='admin-voucher-detail'),
]
