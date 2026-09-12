from pathlib import Path
from uuid import uuid4

import cloudinary
import cloudinary.uploader
from django.conf import settings
from rest_framework import serializers


ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}

ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}


def ensure_cloudinary_configured(field_name="file"):
    """
    Kiểm tra backend đã cấu hình đầy đủ Cloudinary chưa.
    """

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


def validate_image_file(
    file,
    field_name="file",
    max_size=None,
):
    """
    Kiểm tra file ảnh trước khi upload Cloudinary.
    """

    if file in ("", None):
        raise serializers.ValidationError({
            field_name: "Vui lòng chọn file ảnh."
        })

    if not hasattr(file, "read"):
        raise serializers.ValidationError({
            field_name: "File không hợp lệ."
        })

    # Kiểm tra extension
    extension = Path(file.name).suffix.lower()

    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise serializers.ValidationError({
            field_name: "Ảnh chỉ hỗ trợ JPG, JPEG, PNG hoặc WEBP."
        })

    # Kiểm tra Content-Type
    content_type = getattr(file, "content_type", "")

    if content_type and content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise serializers.ValidationError({
            field_name: "File phải là ảnh JPG, PNG hoặc WEBP."
        })

    # Kiểm tra dung lượng
    if max_size is not None and file.size > max_size:
        max_size_mb = max_size / (1024 * 1024)

        raise serializers.ValidationError({
            field_name: (
                f"Kích thước ảnh không được vượt quá "
                f"{max_size_mb:.0f}MB."
            )
        })

    return file


def upload_image(
    file,
    folder,
    public_id_prefix="image",
    field_name="file",
    max_size=None,
):
    """
    Upload image lên Cloudinary.

    Returns:
        {
            "url": "...",
            "public_id": "..."
        }
    """

    validate_image_file(
        file=file,
        field_name=field_name,
        max_size=max_size,
    )

    ensure_cloudinary_configured(
        field_name=field_name
    )

    public_id = f"{public_id_prefix}_{uuid4().hex}"

    try:
        result = cloudinary.uploader.upload(
            file,
            folder=folder,
            public_id=public_id,
            resource_type="image",
            overwrite=False,
            quality="auto",
            fetch_format="auto",
        )
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)

        logger.error(
            f"Cloudinary upload failed: {e}",
            exc_info=True,
        )

        raise serializers.ValidationError({
            field_name: (
                f"Upload ảnh lên Cloudinary thất bại: {str(e)}"
            )
        })

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
