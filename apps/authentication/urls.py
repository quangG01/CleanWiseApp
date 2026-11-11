from django.urls import path
from .admin_customer_views import AdminCustomerDetailView, AdminCustomerStatusView
from .worker_change_views import (
    AdminWorkerServiceReviewView, WorkerEmailChangeConfirmView, WorkerEmailChangeRequestView,
    WorkerServiceRequestView,
)
from .views import (
    UserListView,
    CustomerProfileView,
    LoginView,
    CustomerRegisterView,
    GoogleLoginView,
    ForgotPasswordView,
    VerifyPasswordResetOTPView,
    ResetPasswordView,
    WorkerRegisterView,
    WorkerProfileView,
    WorkerProfileSubmitView,
    AdminWorkerProfileListView,
    AdminWorkerContactUpdateView,
    AdminWorkerProfileReviewHistoryView,
    AdminWorkerStatusUpdateView,
    CustomTokenRefreshView,
    LogoutView,
    ChangePasswordView
)

urlpatterns = [
    path('admin/customers/<int:pk>/', AdminCustomerDetailView.as_view(), name='admin-customer-detail'),
    path('admin/customers/<int:pk>/status/', AdminCustomerStatusView.as_view(), name='admin-customer-status'),
    path('users/', UserListView.as_view(), name='user-list'),
    path('customer/profile/', CustomerProfileView.as_view(), name='customer-profile'),
    path('register/', CustomerRegisterView.as_view(), name='register'),
    path('worker/register/', WorkerRegisterView.as_view(), name='worker-register'),
    path('worker/profile/', WorkerProfileView.as_view(), name='worker-profile'),
    path('worker/profile/service-request/', WorkerServiceRequestView.as_view(), name='worker-service-request'),
    path('worker/email-change/request/', WorkerEmailChangeRequestView.as_view(), name='worker-email-change-request'),
    path('worker/email-change/confirm/', WorkerEmailChangeConfirmView.as_view(), name='worker-email-change-confirm'),
    path('admin/worker-profiles/<int:pk>/service-request/', AdminWorkerServiceReviewView.as_view(), name='admin-worker-service-review'),
    path(
        'worker/profile/submit/',
        WorkerProfileSubmitView.as_view(),
        name='worker-profile-submit',
    ),
    path(
        'admin/worker-profiles/',
        AdminWorkerProfileListView.as_view(),
        name='admin-worker-profile-list',
    ),
    path(
        'admin/worker-profiles/<int:pk>/status/',
        AdminWorkerStatusUpdateView.as_view(),
        name='admin-worker-status-update',
    ),
    path(
        'admin/worker-profiles/<int:pk>/review-history/',
        AdminWorkerProfileReviewHistoryView.as_view(),
        name='admin-worker-profile-review-history',
    ),
    path(
        'admin/worker-profiles/<int:pk>/contact/',
        AdminWorkerContactUpdateView.as_view(),
        name='admin-worker-contact-update',
    ),
    path('login/', LoginView.as_view(), name='login'),
    path("login-google/", GoogleLoginView.as_view(), name="google-login"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("verify-reset-otp/", VerifyPasswordResetOTPView.as_view(), name="verify-reset-otp"),
    path("reset-password/", ResetPasswordView.as_view(), name="reset-password"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
]
