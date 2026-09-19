from django.urls import path

from .views import (
    CustomerEligibleReviewListView,
    CustomerReviewDetailView,
    CustomerReviewListCreateView,
)


urlpatterns = [
    path('reviews/eligible/', CustomerEligibleReviewListView.as_view(), name='customer-review-eligible'),
    path('reviews/', CustomerReviewListCreateView.as_view(), name='customer-review-list-create'),
    path('reviews/<int:pk>/', CustomerReviewDetailView.as_view(), name='customer-review-detail'),
]
