from uuid import uuid4

import cloudinary
import cloudinary.uploader
from django.conf import settings
from rest_framework import serializers

import socket
import requests
import urllib3
from cloudinary.exceptions import Error as CloudinaryError
from apps.common.retry import retry_on


def _cloudinary_retryable(exc):
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionError,
                        requests.exceptions.RequestException,
                        urllib3.exceptions.HTTPError)):
        return True
    if isinstance(exc, CloudinaryError):
        text = str(exc).lower()
        return any(k in text for k in ('timeout', 'timed out', ' 500', ' 502', ' 503', ' 504'))
    return False


@retry_on(_cloudinary_retryable)
def _upload_with_retry(file, **options):
    if hasattr(file, 'seek'):
        file.seek(0)
    return cloudinary.uploader.upload(file, **options)

def ensure_cloudinary_configured(field_name="file"):
    if not all([
        settings.CLOUDINARY_CLOUD_NAME,
        settings.CLOUDINARY_API_KEY,
        settings.CLOUDINARY_API_SECRET,
    ]):
        raise serializers.ValidationError({
            field_name: "Backend chưa cấu hình Cloudinary."
        })

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )


def upload_file(
    file,
    folder,
    public_id_prefix="file",
    field_name="file",
    resource_type="auto",
):
    ensure_cloudinary_configured(field_name=field_name)

    result = _upload_with_retry(
        file,
        folder=folder,
        public_id=f"{public_id_prefix}_{uuid4().hex}",
        resource_type=resource_type,
        overwrite=False,
    )

    return {
        "url": result["secure_url"],
        "public_id": result["public_id"],
        "resource_type": result.get("resource_type", resource_type),
    }


def upload_image(file, folder, public_id_prefix="image", field_name="file"):
    return upload_file(
        file,
        folder=folder,
        public_id_prefix=public_id_prefix,
        field_name=field_name,
        resource_type="image",
    )


def delete_uploaded_file(
    public_id,
    resource_type="image",
):
    if not public_id:
        return

    ensure_cloudinary_configured()

    return cloudinary.uploader.destroy(
        public_id,
        resource_type=resource_type,
        invalidate=True,
    )