import os
from pathlib import Path
from datetime import timedelta

# Đường dẫn gốc tới thư mục project (nhảy lên 3 cấp từ core/settings/base.py)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Tự động nhận diện thư mục apps/ để import không bị lỗi
import sys
sys.path.insert(0, os.path.join(BASE_DIR, 'apps'))

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-change-this-in-production')
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
PASSWORD_RESET_OTP_TTL_MINUTES = int(os.environ.get("PASSWORD_RESET_OTP_TTL_MINUTES", 10))
PASSWORD_RESET_OTP_MAX_ATTEMPTS = int(os.environ.get("PASSWORD_RESET_OTP_MAX_ATTEMPTS", 5))

# # ============================================= Danh sách Django Apps & Third-party Packages # ============================================= 
INSTALLED_APPS = [
    # Django core apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party packages
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'drf_spectacular',

    # Local apps
    'apps.authentication',
    'apps.services',
    'apps.bookings',
    'apps.ai_engine',
    'apps.analytics',
    'apps.common',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Đặt lên trên cùng để xử lý CORS
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'
AUTH_USER_MODEL = 'authentication.User'

# ============================================= Password validation=============================================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

#============================================= Internationalization =============================================
LANGUAGE_CODE = 'vi-vn'
TIME_ZONE = 'Asia/Ho_Chi_Minh'
USE_I18N = True
USE_TZ = True

# ============================================= Static & Media files =============================================
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
CUSTOMER_AVATAR_UPLOAD_DIR = os.environ.get(
    "CUSTOMER_AVATAR_UPLOAD_DIR",
    "customer_avatars"
)
CUSTOMER_AVATAR_MAX_SIZE = int(os.environ.get("CUSTOMER_AVATAR_MAX_SIZE", 5 * 1024 * 1024))
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")
CLOUDINARY_ROOT_FOLDER = "cleanwise"
CLOUDINARY_CUSTOMER_AVATAR_FOLDER = f"{CLOUDINARY_ROOT_FOLDER}/customer_avatars"
CLOUDINARY_SERVICE_IMAGE_FOLDER = f"{CLOUDINARY_ROOT_FOLDER}/service_images"
CLOUDINARY_REVIEW_IMAGE_FOLDER = f"{CLOUDINARY_ROOT_FOLDER}/review_images"

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ============================================= Email =============================================
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True") == "True"
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    EMAIL_HOST_USER or "no-reply@cleanwise.local"
)

# =============================================Cấu hình Django REST Framework (DRF)============================================= 
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    
    # !! Bọc khi API gặp LỖI
    'EXCEPTION_HANDLER': 'apps.common.exceptions.custom_exception_handler',
    
    # !! Bọc khi API THÀNH CÔNG (Trả data hợp lệ)
    'DEFAULT_RENDERER_CLASSES': (
        'apps.common.renderers.CustomJSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer', # Giữ lại giao diện DRF Web
    ),
}

# ============================================= Cấu hình Simple JWT=============================================
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ============================================= Cấu hình Swagger API Documentation=============================================
SPECTACULAR_SETTINGS = {
    'TITLE': 'CleanWiseApp Backend API',
    'VERSION': '1.0.0',
}
