from django.urls import path
from .views import UserListView, LoginView, RegisterView, GoogleLoginView  

urlpatterns = [
    path('users/', UserListView.as_view(), name='user-list'),
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path("login-google/", GoogleLoginView.as_view(), name="google-login"),
]
