from django.urls import path

from .admin_views import (
    AdminUserWalletView,
    AdminWalletTargetListView,
    AdminWalletTransactionListView,
    AdminWithdrawReviewListView,
    AdminWithdrawResolveView,
    AdminWalletTransactionExportView,
)

urlpatterns = [
    path('wallets/transactions/', AdminWalletTransactionListView.as_view(), name='admin-wallet-transactions'),
    path('wallets/targets/', AdminWalletTargetListView.as_view(), name='admin-wallet-targets'),
    path('wallets/users/<int:user_id>/', AdminUserWalletView.as_view(), name='admin-user-wallet'),
    path('withdraws/review/', AdminWithdrawReviewListView.as_view(), name='admin-withdraw-review-list'),
    path('withdraws/<int:pk>/resolve/', AdminWithdrawResolveView.as_view(), name='admin-withdraw-resolve'),
    path('wallets/transactions/export/', AdminWalletTransactionExportView.as_view(), name='admin-wallet-transactions-export'),
]