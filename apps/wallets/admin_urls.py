from django.urls import path

from .admin_views import AdminBookingRefundView, AdminUserWalletView, AdminWalletAdjustView

urlpatterns = [
    path('bookings/<int:pk>/refund/', AdminBookingRefundView.as_view(), name='admin-booking-refund'),
    path('wallets/adjust/', AdminWalletAdjustView.as_view(), name='admin-wallet-adjust'),
    path('wallets/users/<int:user_id>/', AdminUserWalletView.as_view(), name='admin-user-wallet'),
]