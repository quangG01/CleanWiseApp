from django.urls import path

from .admin_views import (
    AdminBookingRefundView,
    AdminUserWalletView,
    AdminWalletAdjustView,
    AdminWalletTargetListView,
    AdminWalletTransactionListView,
)

urlpatterns = [
    path('bookings/<int:pk>/refund/', AdminBookingRefundView.as_view(), name='admin-booking-refund'),
    path('wallets/adjust/', AdminWalletAdjustView.as_view(), name='admin-wallet-adjust'),
    path('wallets/transactions/', AdminWalletTransactionListView.as_view(), name='admin-wallet-transactions'),
    path('wallets/targets/', AdminWalletTargetListView.as_view(), name='admin-wallet-targets'),
    path('wallets/users/<int:user_id>/', AdminUserWalletView.as_view(), name='admin-user-wallet'),
]