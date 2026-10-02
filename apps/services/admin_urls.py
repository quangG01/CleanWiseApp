# apps/services/admin_urls.py
from django.urls import path

from .views import AdminServiceDetailView, AdminServiceListCreateView, AdminServiceOptionImageUploadView

urlpatterns = [
    path('', AdminServiceListCreateView.as_view(), name='admin-service-list-create'),
    path('option-images/', AdminServiceOptionImageUploadView.as_view(), name='admin-service-option-image-upload'),
    path('<int:pk>/', AdminServiceDetailView.as_view(), name='admin-service-detail'),
]
