from django.urls import path

from .worker_earnings import WorkerEarningHistoryView, WorkerEarningSummaryView

urlpatterns = [
    path('summary/', WorkerEarningSummaryView.as_view(), name='worker-earnings-summary'),
    path('history/', WorkerEarningHistoryView.as_view(), name='worker-earnings-history'),
]