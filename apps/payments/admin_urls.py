from django.urls import path
from .admin_views import AdminPaymentListView

urlpatterns = [
    path('', AdminPaymentListView.as_view()),
]