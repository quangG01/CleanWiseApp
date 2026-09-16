# apps/services/urls.py
from django.urls import path

from .views import ServiceDetailView, ServiceListView

urlpatterns = [
    path('', ServiceListView.as_view(), name='service-list'),
    path('<int:pk>/', ServiceDetailView.as_view(), name='service-detail'),
]