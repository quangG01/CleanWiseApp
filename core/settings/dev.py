import os
from urllib.parse import parse_qs, urlparse
from .base import *

DEBUG = True
DEBUG_PROPAGATE_EXCEPTIONS = True 
ALLOWED_HOSTS = ['*']


def build_database_config():
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        parsed_url = urlparse(database_url)
        query_params = parse_qs(parsed_url.query)

        return {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': parsed_url.path.lstrip('/'),
            'USER': parsed_url.username,
            'PASSWORD': parsed_url.password,
            'HOST': parsed_url.hostname,
            'PORT': parsed_url.port or '5432',
            'CONN_MAX_AGE': 60,
            'CONN_HEALTH_CHECKS': True,
            'OPTIONS': {
                'sslmode': query_params.get('sslmode', ['require'])[0],
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5,
            },
        }

    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME'),
        'USER': os.environ.get('DB_USER'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': os.environ.get('DB_HOST'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'CONN_MAX_AGE': 60,
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {
            'sslmode': os.environ.get('DB_SSLMODE', 'require'),
            'keepalives': 1,
            'keepalives_idle': 30,
            'keepalives_interval': 10,
            'keepalives_count': 5,
        },
    }


DATABASES = {
    'default': build_database_config()
}

CORS_ALLOW_ALL_ORIGINS = True

# Local development thường không chạy RabbitMQ/Celery. Tắt enqueue push mặc
# định để request nghiệp vụ không phải chờ broker timeout. Có thể bật lại bằng
# PUSH_NOTIFICATIONS_ENABLED=1 khi đã khởi động broker và Celery worker.
PUSH_NOTIFICATIONS_ENABLED = os.environ.get('PUSH_NOTIFICATIONS_ENABLED', '0') == '1'

# One local runserver process can deliver chat events without a Redis service.
# Deployments with REDIS_URL keep the shared channel layer from base settings.
if not os.environ.get('REDIS_URL'):
    CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
    }
    
    
CSRF_TRUSTED_ORIGINS = ["https://take-unreeling-shaping.ngrok-free.dev"]
