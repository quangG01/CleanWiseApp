from django.urls import path

from .views import AdminReviewListView, AdminReviewReplyView, AdminReviewVisibilityView


urlpatterns = [
    path('reviews/', AdminReviewListView.as_view(), name='admin-review-list'),
    path('reviews/<int:pk>/visibility/', AdminReviewVisibilityView.as_view(), name='admin-review-visibility'),
    path('reviews/<int:pk>/reply/', AdminReviewReplyView.as_view(), name='admin-review-reply'),
]
