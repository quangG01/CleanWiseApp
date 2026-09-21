from django.urls import path

from .views import (
    CustomerBankCatalogView,
    CustomerPaymentMethodDetailView,
    CustomerPaymentMethodListCreateView,
    CustomerPaymentMethodOptionsView,
    CustomerPaymentMethodSetDefaultView,
)


urlpatterns = [
    path('payment-methods/', CustomerPaymentMethodListCreateView.as_view(), name='customer-payment-method-list-create'),
    path('payment-methods/options/', CustomerPaymentMethodOptionsView.as_view(), name='customer-payment-method-options'),
    path('payment-methods/banks/', CustomerBankCatalogView.as_view(), name='customer-payment-method-banks'),
    path('payment-methods/<int:pk>/', CustomerPaymentMethodDetailView.as_view(), name='customer-payment-method-detail'),
    path('payment-methods/<int:pk>/default/', CustomerPaymentMethodSetDefaultView.as_view(), name='customer-payment-method-set-default'),
]
