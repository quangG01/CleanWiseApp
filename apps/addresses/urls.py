from django.urls import path

from .views import CustomerAddressDetailView, CustomerAddressListCreateView, CustomerAddressSetDefaultView


urlpatterns = [
    path('addresses/', CustomerAddressListCreateView.as_view(), name='customer-address-list-create'),
    path('addresses/<int:pk>/', CustomerAddressDetailView.as_view(), name='customer-address-detail'),
    path('addresses/<int:pk>/default/', CustomerAddressSetDefaultView.as_view(), name='customer-address-set-default'),
]
