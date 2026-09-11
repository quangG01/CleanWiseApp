from django.urls import path

from .views import (
    CustomerAddressDetailView,
    CustomerAddressListCreateView,
    CustomerAddressSetDefaultView,
    CustomerAvailableVoucherListView,
    CustomerVoucherClaimCodeView,
    CustomerVoucherClaimView,
    CustomerVoucherDetailView,
    CustomerVoucherListView,
)


urlpatterns = [
    path('addresses/', CustomerAddressListCreateView.as_view(), name='customer-address-list-create'),
    path('addresses/<int:pk>/', CustomerAddressDetailView.as_view(), name='customer-address-detail'),
    path(
        'addresses/<int:pk>/default/',
        CustomerAddressSetDefaultView.as_view(),
        name='customer-address-set-default',
    ),
    path('vouchers/', CustomerVoucherListView.as_view(), name='customer-voucher-list'),
    path(
        'vouchers/available/',
        CustomerAvailableVoucherListView.as_view(),
        name='customer-voucher-available',
    ),
    path(
        'vouchers/available/<int:pk>/claim/',
        CustomerVoucherClaimView.as_view(),
        name='customer-voucher-claim',
    ),
    path(
        'vouchers/claim-code/',
        CustomerVoucherClaimCodeView.as_view(),
        name='customer-voucher-claim-code',
    ),
    path(
        'vouchers/<int:pk>/',
        CustomerVoucherDetailView.as_view(),
        name='customer-voucher-detail',
    ),
]
