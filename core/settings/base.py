import os
from pathlib import Path
from datetime import timedelta

# Đường dẫn gốc tới thư mục project (nhảy lên 3 cấp từ core/settings/base.py)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-change-this-in-production')
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
PASSWORD_RESET_OTP_TTL_MINUTES = int(os.environ.get("PASSWORD_RESET_OTP_TTL_MINUTES", 10))
PASSWORD_RESET_OTP_MAX_ATTEMPTS = int(os.environ.get("PASSWORD_RESET_OTP_MAX_ATTEMPTS", 5))
FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY", "")

PAYOS_CLIENT_ID = os.environ.get("PAYOS_CLIENT_ID", "")
PAYOS_API_KEY = os.environ.get("PAYOS_API_KEY", "")
PAYOS_CHECKSUM_KEY = os.environ.get("PAYOS_CHECKSUM_KEY", "")
PAYOS_RETURN_URL = os.environ.get("PAYOS_RETURN_URL", "https://cleanwise.vn/payment/return")
PAYOS_CANCEL_URL = os.environ.get("PAYOS_CANCEL_URL", "https://cleanwise.vn/payment/cancel")

# # ============================================= Danh sách Django Apps & Third-party Packages # ============================================= 
INSTALLED_APPS = [
    'daphne',
    'channels',
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
    'apps.addresses',
    'apps.worker',
    'apps.payments',
    'apps.reviews',
    'apps.complaints',
    'apps.notifications',
    'apps.chat',
    'apps.services',
    'apps.bookings',
    'apps.vouchers',
    'apps.ai_engine',
    'apps.analytics',
    'apps.common',
    'apps.wallets',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
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
ASGI_APPLICATION = 'core.asgi.application'
AUTH_USER_MODEL = 'authentication.User'

# Redis is required when multiple ASGI processes serve WebSocket clients.
# The in-memory option is only for local development and tests.
if os.environ.get('CHAT_USE_IN_MEMORY_LAYER') == '1':
    CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/0')]},
        },
    }

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
CLOUDINARY_WORKER_PROFILE_FOLDER = f"{CLOUDINARY_ROOT_FOLDER}/worker_profiles"
WORKER_DOCUMENT_MAX_SIZE = int(os.environ.get("WORKER_DOCUMENT_MAX_SIZE", 10 * 1024 * 1024))
REVIEW_IMAGE_MAX_SIZE = int(os.environ.get("REVIEW_IMAGE_MAX_SIZE", 5 * 1024 * 1024))
REVIEW_MAX_IMAGES = int(os.environ.get("REVIEW_MAX_IMAGES", 5))

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
    'TAGS': [
        # --- NHÓM 1: Xác thực & Dùng chung ---
        {'name': 'Auth', 'description': 'Đăng nhập, đăng ký chung (Khách hàng & Nhân viên)'},
        {'name': 'Auth - Password Reset', 'description': 'Quên và đặt lại mật khẩu'},

        # --- NHÓM 2: Dành cho Khách hàng (Customer) ---
        {'name': 'Customer - Profile', 'description': 'Thông tin cá nhân khách hàng'},
        {'name': 'Customer - Addresses', 'description': 'Quản lý địa chỉ khách hàng'},
        {'name': 'Services', 'description': 'Xem danh sách dịch vụ'},
        {'name': 'Voucher - Customer', 'description': 'Ví voucher và ưu đãi của khách hàng'},
        {'name': 'Booking - Customer', 'description': 'Đặt lịch dịch vụ của khách hàng'},
        {'name': 'Review - Customer', 'description': 'Đánh giá nhân viên theo từng buổi đã hoàn thành'},

        # --- NHÓM 3: Dành cho Nhân viên (Worker) ---
        {'name': 'Worker - Auth', 'description': 'Đăng ký tài khoản nhân viên'},
        {'name': 'Worker - Profile', 'description': 'Hồ sơ cá nhân nhân viên'},
        {'name': 'Worker - Areas', 'description': 'Khu vực hoạt động khả dụng'},
        {'name': 'Worker - Working Areas', 'description': 'Đăng ký khu vực làm việc của nhân viên'},
        {'name': 'Worker - Schedules', 'description': 'Lịch làm việc của nhân viên'},
        {'name': 'Worker - Assignments', 'description': 'Nhận và hủy việc của nhân viên'},
        {'name': 'Review - Worker', 'description': 'Xem đánh giá và thống kê điểm của nhân viên'},

        # --- NHÓM 4: Dành cho Quản trị viên (Admin) ---
        {'name': 'Users - Admin', 'description': 'Quản lý người dùng hệ thống'},
        {'name': 'Worker - Admin', 'description': 'Phê duyệt hồ sơ nhân viên'},
        {'name': 'Services - Admin', 'description': 'Quản lý dịch vụ'},
        {'name': 'Booking - Admin', 'description': 'Quản lý lịch làm việc & phân công'},
        {'name': 'Voucher - Admin', 'description': 'Quản lý, tạo và tra cứu voucher'},
        {'name': 'Review - Admin', 'description': 'Kiểm duyệt và phản hồi đánh giá'},
    ],
    'EXTENSIONS_ROOT': {
        'x-tagGroups': [
            {
                'name': '1. Xác thực & Dùng chung',
                'tags': ['Auth', 'Auth - Password Reset'],
            },
            {
                'name': '2. Khách hàng (Customer)',
                'tags': ['Customer - Profile', 'Customer - Addresses', 'Services', 'Voucher - Customer', 'Booking - Customer', 'Review - Customer'],
            },
            {
                'name': '3. Nhân viên (Worker)',
                'tags': ['Worker - Auth', 'Worker - Profile', 'Worker - Areas', 'Worker - Working Areas', 'Worker - Schedules', 'Worker - Assignments', 'Review - Worker'],
            },
            {
                'name': '4. Quản trị viên (Admin)',
                'tags': ['Users - Admin', 'Worker - Admin', 'Services - Admin', 'Booking - Admin', 'Voucher - Admin', 'Review - Admin'],
            },
        ],
    },
    'ENUM_NAME_OVERRIDES': {
        'WorkerProfileStatusEnum': 'apps.authentication.models.WorkerProfile.Status',
        'UserVoucherStatusEnum': 'apps.vouchers.models.UserVoucher.Status',
    },
}
