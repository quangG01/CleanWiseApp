from django.urls import path

from .views import (
    WorkerWalletDetailView,
    WorkerWalletTransactionListView,
    WorkerWalletWithdrawRequestView,
)
from .worker_earnings import WorkerEarningHistoryView, WorkerEarningSummaryView

urlpatterns = [
    path('earnings/summary/', WorkerEarningSummaryView.as_view(), name='worker-earnings-summary'),
    path('earnings/history/', WorkerEarningHistoryView.as_view(), name='worker-earnings-history'),

    path('wallet/', WorkerWalletDetailView.as_view(), name='worker-wallet-detail'),
    path('wallet/transactions/', WorkerWalletTransactionListView.as_view(), name='worker-wallet-transactions'),
    path('wallet/withdraw/', WorkerWalletWithdrawRequestView.as_view(), name='worker-wallet-withdraw'),
]