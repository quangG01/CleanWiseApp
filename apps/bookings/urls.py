from django.urls import path

from .views import BookingDetailView, BookingListCreateView, BookingCancelView, BookingPaymentLinkView


urlpatterns = [
    path('bookings/', BookingListCreateView.as_view(), name='customer-booking-list-create'),
    path('bookings/<int:pk>/', BookingDetailView.as_view(), name='customer-booking-detail'),
    path('bookings/<int:pk>/cancel/', BookingCancelView.as_view(), name='customer-booking-cancel'),
    path('bookings/<int:pk>/payment-link/', BookingPaymentLinkView.as_view(), name='booking-payment-link'),
]
