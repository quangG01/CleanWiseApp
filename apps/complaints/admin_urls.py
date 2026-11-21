# apps/complaints/admin_urls.py

from django.urls import path
from apps.worker.discipline_views import AdminDisciplineDetailView, AdminDisciplineView
from .workflow_views import AdminComplaintWorkflowView

from .views import (
    ComplaintDetailView,
    ComplaintListCreateView,
    ComplaintPreviewView,
    ComplaintResolveView,
)


urlpatterns = [
    path('complaints/<int:pk>/workflow/', AdminComplaintWorkflowView.as_view(), name='admin-complaint-workflow'),
    path('worker-discipline/', AdminDisciplineView.as_view(), name='admin-discipline-list'),
    path('worker-discipline/<int:pk>/', AdminDisciplineDetailView.as_view(), name='admin-discipline-detail'),
    path(
        'complaints/',
        ComplaintListCreateView.as_view(),
        name='admin-complaint-list',
    ),

    path(
        'complaints/<int:pk>/',
        ComplaintDetailView.as_view(),
        name='admin-complaint-detail',
    ),

    path(
        'complaints/<int:pk>/resolve/',
        ComplaintResolveView.as_view(),
        name='admin-complaint-resolve',
    ),
        path(
        'complaints/<int:pk>/preview/',
        ComplaintPreviewView.as_view(),
        name='admin-complaint-preview',
    ),
]
