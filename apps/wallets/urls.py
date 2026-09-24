from django.urls import path

from .views import (
    WalletDetailView,
    WalletTransactionListView,
    WalletWithdrawRequestView,
)

urlpatterns = [
    path('wallet/', WalletDetailView.as_view(), name='customer-wallet-detail'),
    path('wallet/transactions/', WalletTransactionListView.as_view(), name='customer-wallet-transactions'),
    path('wallet/withdraw/', WalletWithdrawRequestView.as_view(), name='customer-wallet-withdraw'),
]