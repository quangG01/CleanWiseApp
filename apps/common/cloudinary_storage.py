from uuid import uuid4

import cloudinary
import cloudinary.uploader
from django.conf import settings
from rest_framework import serializers


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

    result = cloudinary.uploader.upload(
        file,
        folder=folder,
        public_id=f"{public_id_prefix}_{uuid4().hex}",
        resource_type=resource_type,
        overwrite=False,
    )

    return {
        "url": result["secure_url"],
        "public_id": result["public_id"],
    }


def upload_image(file, folder, public_id_prefix="image", field_name="file"):
    return upload_file(
        file,
        folder=folder,
        public_id_prefix=public_id_prefix,
        field_name=field_name,
        resource_type="image",
    )
