from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    UserListView,
    CustomerProfileView,
    LoginView,
    RegisterView,
    GoogleLoginView,
    ForgotPasswordView,
    VerifyPasswordResetOTPView,
    ResetPasswordView,
    WorkerRegisterView,
    WorkerProfileView,
    AdminWorkerProfileListView,
    AdminWorkerStatusUpdateView,
)

urlpatterns = [
    path('users/', UserListView.as_view(), name='user-list'),
    path(
        'customer/profile/',
        CustomerProfileView.as_view(),
        name='customer-profile'
    ),
    path('register/', RegisterView.as_view(), name='register'),
    path('worker/register/', WorkerRegisterView.as_view(), name='worker-register'),
    path('worker/profile/', WorkerProfileView.as_view(), name='worker-profile'),
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
    path('login/', LoginView.as_view(), name='login'),
    path(
        "login-google/",
        GoogleLoginView.as_view(),
        name="google-login"
    ),
    path(
        "forgot-password/",
        ForgotPasswordView.as_view(),
        name="forgot-password"
    ),
    path(
        "verify-reset-otp/",
        VerifyPasswordResetOTPView.as_view(),
        name="verify-reset-otp"
    ),
    path(
        "reset-password/",
        ResetPasswordView.as_view(),
        name="reset-password"
    ),
    path(
        "refresh/",
        TokenRefreshView.as_view(),
        name="token-refresh"
    ),
]