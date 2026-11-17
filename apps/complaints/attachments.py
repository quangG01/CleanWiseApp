from contextlib import contextmanager
import logging

from django.conf import settings
from rest_framework import serializers

from apps.common.cloudinary_storage import delete_uploaded_file, upload_image

logger = logging.getLogger(__name__)
MAX_COMPLAINT_ATTACHMENTS = 5


def validate_complaint_image(value):
    if value.content_type not in ('image/jpeg', 'image/png', 'image/webp'):
        raise serializers.ValidationError('Chỉ chấp nhận file ảnh (jpeg/png/webp).')
    if value.size > 5 * 1024 * 1024:
        raise serializers.ValidationError('Ảnh tối đa 5MB.')
    return value


@contextmanager
def uploaded_complaint_images(files, *, public_id_prefix='complaint'):
    uploads = []
    try:
        for file in files:
            uploaded = upload_image(
                file, folder=settings.CLOUDINARY_COMPLAINT_IMAGE_FOLDER,
                public_id_prefix=public_id_prefix, field_name='attachments',
            )
            uploads.append({
                'file': uploaded['url'],
                'public_id': uploaded['public_id'],
                'file_type': file.content_type,
            })
        yield uploads
    except Exception:
        for upload in uploads:
            try:
                delete_uploaded_file(upload['public_id'])
            except Exception:
                logger.warning('Could not remove failed complaint evidence upload', exc_info=True)
        raise
