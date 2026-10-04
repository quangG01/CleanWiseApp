import base64
import hashlib

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings


def _derived_fernet():
    """Khóa suy ra từ SECRET_KEY: chỉ dùng cho dev, và để GIẢI MÃ dữ liệu cũ đã mã hóa trước khi có FIELD_ENCRYPTION_KEY."""
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _get_fernet():
    fernets = []
    configured_key = getattr(settings, 'FIELD_ENCRYPTION_KEY', '')
    if configured_key:
        fernets.append(Fernet(configured_key.encode()))
    fernets.append(_derived_fernet())
    # MultiFernet: mã hóa luôn bằng khóa đầu tiên (FIELD_ENCRYPTION_KEY nếu có),
    # giải mã thử lần lượt từng khóa -> bật FIELD_ENCRYPTION_KEY không làm hỏng dữ liệu cũ.
    return MultiFernet(fernets)


def encrypt_value(value):
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_value(value):
    return _get_fernet().decrypt(value.encode()).decode()