from django.urls import path

from .views import (
    CustomerCodeVoucherClaimView,
    CustomerVoucherDetailView,
    CustomerVoucherListView,
    CustomerVoucherValidateView,
    CustomerVoucherWalletListView,
)


urlpatterns = [
    path('vouchers/', CustomerVoucherListView.as_view(), name='customer-voucher-list'),
    path('vouchers/my-vouchers/', CustomerVoucherWalletListView.as_view(), name='customer-voucher-wallet-list'),
    path('vouchers/claim-by-code/', CustomerCodeVoucherClaimView.as_view(), name='customer-voucher-claim-by-code'),
    path('vouchers/validate/', CustomerVoucherValidateView.as_view(), name='customer-voucher-validate'),
    path('vouchers/<int:pk>/', CustomerVoucherDetailView.as_view(), name='customer-voucher-detail'),
]
