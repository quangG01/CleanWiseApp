# apps/services/serializers.py
import logging
from pathlib import Path
from uuid import uuid4

import cloudinary.uploader
from django.conf import settings
from django.db import transaction
from rest_framework import serializers

from apps.common.cloudinary_storage import upload_image

from .models import Service, ServiceImage
from .utils import extract_cloudinary_public_id

logger = logging.getLogger(__name__)


# ============================================================
# IMAGE FIELD + HELPER
# ============================================================

class ServiceImageFileField(serializers.FileField):
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
    allowed_content_types = {'image/jpeg', 'image/png', 'image/webp'}

    def to_internal_value(self, data):
        if data in ('', None):
            return None
        if not hasattr(data, 'read'):
            raise serializers.ValidationError('Ảnh phải được gửi dưới dạng file.')
        extension = Path(data.name).suffix.lower()
        if extension not in self.allowed_extensions:
            raise serializers.ValidationError('Ảnh chỉ hỗ trợ JPG, JPEG, PNG hoặc WEBP.')
        content_type = getattr(data, 'content_type', '')
        if content_type and content_type not in self.allowed_content_types:
            raise serializers.ValidationError('File upload phải là ảnh hợp lệ.')
        max_size = getattr(settings, 'SERVICE_IMAGE_MAX_SIZE', 10 * 1024 * 1024)
        if data.size > max_size:
            raise serializers.ValidationError(
                f'Ảnh không được vượt quá {max_size // (1024 * 1024)}MB.'
            )
        return data


def save_service_image(service, image_file):
    folder = f"{settings.CLOUDINARY_SERVICE_IMAGE_FOLDER}/service_{service.id}"
    uploaded = upload_image(
        image_file,
        folder=folder,
        public_id_prefix='service_image',
        field_name='images',
        max_size=getattr(settings, 'SERVICE_IMAGE_MAX_SIZE', 10 * 1024 * 1024),
    )
    return ServiceImage.objects.create(service=service, image=uploaded['url'])


def delete_service_image(image):
    public_id = extract_cloudinary_public_id(image.image)
    if public_id:
        try:
            result = cloudinary.uploader.destroy(public_id, resource_type='image')
            if result.get('result') not in ('ok', 'not found'):
                raise serializers.ValidationError({'images': 'Không thể xoá ảnh trên Cloudinary.'})
        except serializers.ValidationError:
            raise
        except Exception as e:
            logger.error(f"Cloudinary destroy failed: {e}", exc_info=True)
            raise serializers.ValidationError({'images': 'Không thể xoá ảnh trên Cloudinary.'})
    image.delete()


# ============================================================
# READ SERIALIZERS
# ============================================================

class ServiceImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceImage
        fields = ['id', 'image', 'alt_text', 'sort_order', 'is_primary']
        read_only_fields = ['id', 'image']


class ServiceListSerializer(serializers.ModelSerializer):
    primary_image = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = ['id', 'code', 'section_code', 'name', 'description', 'is_active', 'primary_image']

    def get_primary_image(self, obj):
        image = obj.images.filter(is_primary=True).first() or obj.images.first()
        return image.image if image else None


class ServiceDetailSerializer(serializers.ModelSerializer):
    images = ServiceImageSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        fields = [
            'id', 'code', 'section_code', 'name', 'description',
            'form_schema', 'pricing_config', 'images', 'is_active',
            'created_at', 'updated_at',
        ]


# ============================================================
# ADMIN WRITE SERIALIZER
# ============================================================

class ServiceAdminWriteSerializer(serializers.ModelSerializer):
    images = serializers.ListField(
        child=ServiceImageFileField(),
        required=False,
        allow_empty=True,
        write_only=True,
    )
    delete_image_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
        write_only=True,
    )

    class Meta:
        model = Service
        fields = [
            'id', 'code', 'section_code', 'name', 'description',
            'form_schema', 'pricing_config', 'is_active',
            'images', 'delete_image_ids',
        ]
        read_only_fields = ['id']

    def validate_code(self, value):
        value = value.strip().upper()
        queryset = Service.objects.filter(code__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError('Mã dịch vụ đã tồn tại.')
        return value

    def validate_section_code(self, value):
        return value.strip().upper()

    def validate_form_schema(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('form_schema phải là một object JSON.')
        return value

    def validate_pricing_config(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('pricing_config phải là một object JSON.')
        return value

    def validate(self, attrs):
        delete_image_ids = attrs.get('delete_image_ids', [])
        if self.instance and delete_image_ids:
            existing_ids = set(
                self.instance.images.filter(id__in=delete_image_ids).values_list('id', flat=True)
            )
            invalid_ids = set(delete_image_ids) - existing_ids
            if invalid_ids:
                raise serializers.ValidationError({
                    'delete_image_ids': 'Một hoặc nhiều ảnh không thuộc dịch vụ này.'
                })
        elif delete_image_ids and not self.instance:
            raise serializers.ValidationError({
                'delete_image_ids': 'Không thể xoá ảnh khi đang tạo dịch vụ.'
            })
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        images = validated_data.pop('images', [])
        validated_data.pop('delete_image_ids', None)
        service = Service.objects.create(**validated_data)
        for image_file in images:
            save_service_image(service, image_file)
        return service

    @transaction.atomic
    def update(self, instance, validated_data):
        images = validated_data.pop('images', [])
        delete_image_ids = validated_data.pop('delete_image_ids', [])
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        for image_id in delete_image_ids:
            image = instance.images.filter(id=image_id).first()
            if image:
                delete_service_image(image)
        for image_file in images:
            save_service_image(instance, image_file)
        return instance