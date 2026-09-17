from django.urls import path

from .views import (
    WorkerActiveAreaListView,
    WorkerWorkingAreaDetailView,
    WorkerWorkingAreaListCreateView,
)


urlpatterns = [
    path('areas/', WorkerActiveAreaListView.as_view(), name='worker-active-area-list'),
    path('working-areas/', WorkerWorkingAreaListCreateView.as_view(), name='worker-working-area-list-create'),
    path( 'working-areas/<int:pk>/', WorkerWorkingAreaDetailView.as_view(),name='worker-working-area-detail'),
]
