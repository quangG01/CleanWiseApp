"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add an import:  from my_app import views
Class-based views
    1. Add an import:  from my_app import views
    2. Add an import:  from my_app import views
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add the import:  from django.urls import include, path
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='redoc'), name='redoc'),
    
    
]

### ======================================= URL API API AUTHENTICATION & USERS  =======================================
urlauthpatterns = [
    path('api/auth/', include('apps.authentication.urls')),
    path('api/customer/', include('apps.bookings.urls')),
    path('api/admin/', include('apps.bookings.admin_urls')),
]



urlpatterns += urlauthpatterns


### ======================================= URL API SERVICES =======================================
urlservicepatterns = [
    path('api/services/', include('apps.services.urls')),
]


urlpatterns += urlservicepatterns


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
