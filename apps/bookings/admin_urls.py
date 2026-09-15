from django.urls import path

from .views import AdminVoucherDetailView, AdminVoucherListCreateView


urlpatterns = [
    path('vouchers/', AdminVoucherListCreateView.as_view(), name='admin-voucher-list-create'),
    path('vouchers/<int:pk>/', AdminVoucherDetailView.as_view(), name='admin-voucher-detail'),
]
