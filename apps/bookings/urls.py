from django.urls import path

from .views import BookingDetailView, BookingListCreateView


urlpatterns = [
    path('bookings/', BookingListCreateView.as_view(), name='customer-booking-list-create'),
    path('bookings/<int:pk>/', BookingDetailView.as_view(), name='customer-booking-detail'),
]
