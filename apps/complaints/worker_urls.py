# apps/complaints/worker_urls.py

from django.urls import path

from .views import (
    ComplaintCancelView,
    ComplaintDetailView,
    ComplaintIssueTypeListView,
    ComplaintListCreateView,
    ComplaintAttachmentUploadView,
)


urlpatterns = [
    path(
        'complaint-issue-types/',
        ComplaintIssueTypeListView.as_view(),
        name='worker-complaint-issue-types',
    ),

    path(
        'complaints/',
        ComplaintListCreateView.as_view(),
        name='worker-complaint-list-create',
    ),

    path(
        'complaints/<int:pk>/',
        ComplaintDetailView.as_view(),
        name='worker-complaint-detail',
    ),

    path(
        'complaints/<int:pk>/cancel/',
        ComplaintCancelView.as_view(),
        name='worker-complaint-cancel',
    ),
    path(
        'complaints/<int:pk>/attachments/',
        ComplaintAttachmentUploadView.as_view(),
        name='worker-complaint-attachment-upload',
    ),
]