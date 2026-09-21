from django.urls import path

from .views import (
    WorkerBankCatalogView,
    WorkerPaymentMethodDetailView,
    WorkerPaymentMethodListCreateView,
    WorkerPaymentMethodOptionsView,
    WorkerPaymentMethodSetDefaultView,
)


urlpatterns = [
    path('payment-methods/', WorkerPaymentMethodListCreateView.as_view(), name='worker-payment-method-list-create'),
    path('payment-methods/options/', WorkerPaymentMethodOptionsView.as_view(), name='worker-payment-method-options'),
    path('payment-methods/banks/', WorkerBankCatalogView.as_view(), name='worker-payment-method-banks'),
    path('payment-methods/<int:pk>/', WorkerPaymentMethodDetailView.as_view(), name='worker-payment-method-detail'),
    path('payment-methods/<int:pk>/default/', WorkerPaymentMethodSetDefaultView.as_view(), name='worker-payment-method-set-default'),
]
