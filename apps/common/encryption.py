import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _get_fernet():
    configured_key = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
    if configured_key:
        key = configured_key.encode()
    else:
        digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_value(value):
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_value(value):
    return _get_fernet().decrypt(value.encode()).decode()
