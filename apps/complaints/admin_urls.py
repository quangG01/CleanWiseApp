# apps/complaints/admin_urls.py

from django.urls import path

from .views import (
    ComplaintDetailView,
    ComplaintListCreateView,
    ComplaintPreviewView,
    ComplaintResolveView,
)


urlpatterns = [
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