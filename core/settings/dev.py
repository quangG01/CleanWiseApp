from .base import *

DEBUG = True
ALLOWED_HOSTS = ['*']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'cleanwisedb',       # Tên database bạn tạo trong PostgreSQL
        'USER': 'postgres',        # Username mặc định của Postgres
        'PASSWORD': 'admin',# Mật khẩu PostgreSQL của bạn
        'HOST': '127.0.0.1',
        'PORT': '5433',
    }
}

CORS_ALLOW_ALL_ORIGINS = True