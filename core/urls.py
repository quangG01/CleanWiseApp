"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
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
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    
    
]

### ======================================= URL API API AUTHENTICATION & USERS  =======================================
urlauthpatterns = [
    path('api/auth/', include('apps.authentication.urls')),
    path('api/customer/', include('apps.addresses.urls')),
    path('api/customer/', include('apps.vouchers.urls')),
    path('api/customer/', include('apps.bookings.urls')),
    path('api/customer/', include('apps.reviews.urls')),
    path('api/customer/', include('apps.payments.urls')),
    path('api/worker/', include('apps.worker.urls')),
    path('api/worker/', include('apps.reviews.worker_urls')),
    path('api/worker/', include('apps.payments.worker_urls')),
    path('api/admin/', include('apps.vouchers.admin_urls')),
    path('api/admin/', include('apps.worker.admin_urls')),
    path('api/admin/', include('apps.reviews.admin_urls')),
]



urlpatterns += urlauthpatterns

urladminservicepatterns = [
    path('api/admin/services/', include('apps.services.admin_urls')),
]

urlpatterns += urladminservicepatterns

urlservicepatterns = [
    path('api/services/', include('apps.services.urls')),
]

urlpatterns += urlservicepatterns

urlpatterns += [path('api/chat/', include('apps.chat.urls'))]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
