from django.urls import path
from .views import (
    ReportOverviewView, ReportWorkersView, ReportServicesView,
    ReportRevenueView, ReportBookingsView, ReportExportView,
)

urlpatterns = [
    path('reports/', ReportOverviewView.as_view(), name='admin-report-overview'),
    path('reports/workers/', ReportWorkersView.as_view(), name='admin-report-workers'),
    path('reports/services/', ReportServicesView.as_view(), name='admin-report-services'),
    path('reports/revenue/', ReportRevenueView.as_view(), name='admin-report-revenue'),
    path('reports/bookings/', ReportBookingsView.as_view(), name='admin-report-bookings'),
    path('reports/export/', ReportExportView.as_view(), name='admin-report-export'),
]
