from django.urls import path

from .views import (
    CustomerAddressDetailView,
    CustomerAddressListCreateView,
    CustomerAddressSetDefaultView,
    CustomerCodeVoucherClaimView,
    CustomerVoucherDetailView,
    CustomerVoucherListView,
    CustomerVoucherWalletListView,
    CustomerVoucherValidateView,
)


urlpatterns = [
    path('addresses/', CustomerAddressListCreateView.as_view(), name='customer-address-list-create'),
    path('addresses/<int:pk>/', CustomerAddressDetailView.as_view(), name='customer-address-detail'),
    path('addresses/<int:pk>/default/', CustomerAddressSetDefaultView.as_view(), name='customer-address-set-default'),
    path('vouchers/', CustomerVoucherListView.as_view(), name='customer-voucher-list'),
    path('vouchers/my-vouchers/', CustomerVoucherWalletListView.as_view(), name='customer-voucher-wallet-list'),
    path('vouchers/claim-by-code/', CustomerCodeVoucherClaimView.as_view(), name='customer-voucher-claim-by-code'),
    path('vouchers/validate/', CustomerVoucherValidateView.as_view(), name='customer-voucher-validate'),
    path('vouchers/<int:pk>/', CustomerVoucherDetailView.as_view(), name='customer-voucher-detail'),
]
