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
)

urlpatterns = [
    path('users/', UserListView.as_view(), name='user-list'),
    path(
        'customer/profile/',
        CustomerProfileView.as_view(),
        name='customer-profile'
    ),
    path('register/', RegisterView.as_view(), name='register'),
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