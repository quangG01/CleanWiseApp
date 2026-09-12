from django.urls import path

from .views import (
    AdminUserVoucherDetailView,
    AdminUserVoucherListCreateView,
    AdminVoucherDetailView,
    AdminVoucherListCreateView,
)


urlpatterns = [
    path('vouchers/', AdminVoucherListCreateView.as_view(), name='admin-voucher-list-create'),
    path('vouchers/<int:pk>/', AdminVoucherDetailView.as_view(), name='admin-voucher-detail'),
    path(
        'user-vouchers/',
        AdminUserVoucherListCreateView.as_view(),
        name='admin-user-voucher-list-create',
    ),
    path(
        'user-vouchers/<int:pk>/',
        AdminUserVoucherDetailView.as_view(),
        name='admin-user-voucher-detail',
    ),
]
