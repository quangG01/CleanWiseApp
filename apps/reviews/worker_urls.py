from django.urls import path

from .views import WorkerReviewListView, WorkerReviewSummaryView


urlpatterns = [
    path('reviews/', WorkerReviewListView.as_view(), name='worker-review-list'),
    path('reviews/summary/', WorkerReviewSummaryView.as_view(), name='worker-review-summary'),
]
