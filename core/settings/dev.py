import os
from urllib.parse import parse_qs, urlparse
from .base import *

DEBUG = True
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
            'OPTIONS': {
                'sslmode': query_params.get('sslmode', ['require'])[0],
            },
        }

    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME'),
        'USER': os.environ.get('DB_USER'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': os.environ.get('DB_HOST'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'OPTIONS': {
            'sslmode': os.environ.get('DB_SSLMODE', 'require'),
        },
    }


DATABASES = {
    'default': build_database_config()
}

CORS_ALLOW_ALL_ORIGINS = True
