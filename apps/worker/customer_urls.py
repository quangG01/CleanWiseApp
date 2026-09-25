from django.urls import path

from .views import (
    CustomerFavoriteWorkerDetailView,
    CustomerFavoriteWorkerListView,
    CustomerWorkerProfileView,
)


urlpatterns = [
    path(
        'workers/<int:worker_id>/',
        CustomerWorkerProfileView.as_view(),
        name='customer-worker-profile',
    ),
    path(
        'favorite-workers/',
        CustomerFavoriteWorkerListView.as_view(),
        name='customer-favorite-worker-list',
    ),
    path(
        'favorite-workers/<int:worker_id>/',
        CustomerFavoriteWorkerDetailView.as_view(),
        name='customer-favorite-worker-detail',
    ),
]
