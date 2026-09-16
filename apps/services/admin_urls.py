# apps/services/admin_urls.py
from django.urls import path

from .views import AdminServiceDetailView, AdminServiceListCreateView

urlpatterns = [
    path('', AdminServiceListCreateView.as_view(), name='admin-service-list-create'),
    path('<int:pk>/', AdminServiceDetailView.as_view(), name='admin-service-detail'),
]