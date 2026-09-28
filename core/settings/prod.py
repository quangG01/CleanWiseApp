import os
from urllib.parse import parse_qs, urlparse
from .base import * 

DEBUG = False

SECRET_KEY = os.environ["SECRET_KEY"] 

ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]
CORS_ALLOWED_ORIGINS = [o for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]


def build_database_config():
    keepalive = {
        'keepalives': 1,
        'keepalives_idle': 30,
        'keepalives_interval': 10,
        'keepalives_count': 5,
    }
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
            'OPTIONS': {'sslmode': query_params.get('sslmode', ['require'])[0], **keepalive},
        }
    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ['DB_NAME'],
        'USER': os.environ['DB_USER'],
        'PASSWORD': os.environ['DB_PASSWORD'],
        'HOST': os.environ['DB_HOST'],
        'PORT': os.environ.get('DB_PORT', '5432'),
        'CONN_MAX_AGE': 60,
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {'sslmode': os.environ.get('DB_SSLMODE', 'require'), **keepalive},
    }


DATABASES = {'default': build_database_config()}

# Sau reverse proxy (nginx) có HTTPS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "0") == "1"
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT