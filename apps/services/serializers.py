# apps/services/serializers.py
import logging
import json
from pathlib import Path
from uuid import uuid4

import cloudinary.uploader
from django.conf import settings
from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.common.cloudinary_storage import ensure_cloudinary_configured, upload_image

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


def save_service_image(
    service,
    image_file,
    is_primary=False,
):
    folder = (
        f"{settings.CLOUDINARY_SERVICE_IMAGE_FOLDER}"
        f"/service_{service.id}"
    )

    # upload_image không nhận tham số max_size; kích thước đã được
    # ServiceImageFileField kiểm tra ở bước validate.
    uploaded = upload_image(
        image_file,
        folder=folder,
        public_id_prefix='service_image',
        field_name='images',
    )

    return ServiceImage.objects.create(
        service=service,
        image=uploaded['url'],
        is_primary=is_primary,
    )


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


def save_service_icon(service, icon_file):
    uploaded = upload_image(
        icon_file,
        folder=f"{settings.CLOUDINARY_SERVICE_ICON_FOLDER}/service_{service.id}",
        public_id_prefix='service_icon',
        field_name='icon_file',
    )
    return uploaded['url']


def delete_cloudinary_url(url):
    """Xóa file cũ trên Cloudinary; lỗi chỉ ghi log, không chặn luồng chính."""
    public_id = extract_cloudinary_public_id(url) if url else None
    if not public_id:
        return
    try:
        ensure_cloudinary_configured()
        cloudinary.uploader.destroy(public_id, resource_type='image', invalidate=True)
    except Exception:
        logger.warning('Cloudinary destroy failed for %s', public_id, exc_info=True)


# ============================================================
# READ SERIALIZERS
# ============================================================

class ServiceImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceImage
        fields = ['id', 'image', 'alt_text', 'sort_order', 'is_primary']
        read_only_fields = ['id', 'image']


class ServiceListSerializer(serializers.ModelSerializer):
    primary_image = serializers.SerializerMethodField(help_text='URL ảnh đại diện của dịch vụ; có thể là null.')

    class Meta:
        model = Service
        fields = [
            'id', 'code', 'section_code', 'name', 'description',
            'is_active', 'icon', 'primary_image',
        ]
        extra_kwargs = {
            'id': {'help_text': 'ID gửi trong field service_id khi nhân viên cập nhật hồ sơ.'},
            'code': {'help_text': 'Mã định danh duy nhất của dịch vụ.'},
            'section_code': {'help_text': 'Mã nhóm dịch vụ, dùng để lọc theo section_code.'},
            'name': {'help_text': 'Tên dịch vụ hiển thị.'},
            'description': {'help_text': 'Mô tả dịch vụ.'},
            'is_active': {'help_text': 'Trạng thái hoạt động; API công khai chỉ trả về true.'},
            'icon': {'help_text': 'URL icon dịch vụ do admin upload; có thể là null.'},
        }

    @extend_schema_field(OpenApiTypes.URI)
    def get_primary_image(self, obj):
        images = list(obj.images.all())
        return images[0].image if images else None


class ServiceDetailSerializer(serializers.ModelSerializer):
    images = ServiceImageSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        fields = [
            'id', 'code', 'section_code', 'name', 'description', 'icon',
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

    primary_image_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        write_only=True,
    )

    # Icon dịch vụ: gửi icon_file để thay/đặt mới, remove_icon=true để xóa
    icon_file = ServiceImageFileField(
        required=False,
        allow_null=True,
        write_only=True,
    )

    remove_icon = serializers.BooleanField(
        required=False,
        write_only=True,
    )

    class Meta:
        model = Service
        fields = [
            'id',
            'code',
            'section_code',
            'name',
            'description',
            'form_schema',
            'pricing_config',
            'is_active',
            'icon',
            'icon_file',
            'remove_icon',
            'images',
            'delete_image_ids',
            'primary_image_id',
        ]
        read_only_fields = ['id', 'icon']

    def validate_code(self, value):
        value = value.strip().upper()

        queryset = Service.objects.filter(code__iexact=value)

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                'Mã dịch vụ đã tồn tại.'
            )

        return value

    def validate_section_code(self, value):
        return value.strip().upper()

    def validate_form_schema(self, value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise serializers.ValidationError(
                    'form_schema phải là JSON hợp lệ.'
                )

        if not isinstance(value, dict):
            raise serializers.ValidationError(
                'form_schema phải là một object JSON.'
            )

        return value

    def validate_pricing_config(self, value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise serializers.ValidationError(
                    'pricing_config phải là JSON hợp lệ.'
                )

        if not isinstance(value, dict):
            raise serializers.ValidationError(
                'pricing_config phải là một object JSON.'
            )

        return value

    def validate(self, attrs):
        delete_image_ids = attrs.get('delete_image_ids', [])
        primary_image_id = attrs.get('primary_image_id')

        # CREATE
        if not self.instance:
            if delete_image_ids:
                raise serializers.ValidationError({
                    'delete_image_ids': (
                        'Không thể xoá ảnh khi đang tạo dịch vụ.'
                    )
                })

            if primary_image_id is not None:
                raise serializers.ValidationError({
                    'primary_image_id': (
                        'Không thể chọn ảnh chính cũ khi đang tạo dịch vụ.'
                    )
                })

            return attrs

        # UPDATE - kiểm tra ảnh muốn xoá
        if delete_image_ids:
            existing_ids = set(
                self.instance.images.filter(
                    id__in=delete_image_ids
                ).values_list('id', flat=True)
            )

            invalid_ids = set(delete_image_ids) - existing_ids

            if invalid_ids:
                raise serializers.ValidationError({
                    'delete_image_ids': (
                        'Một hoặc nhiều ảnh không thuộc dịch vụ này.'
                    )
                })

        # UPDATE - kiểm tra ảnh chính
        if primary_image_id is not None:
            primary_image = self.instance.images.filter(
                id=primary_image_id
            ).first()

            if not primary_image:
                raise serializers.ValidationError({
                    'primary_image_id': (
                        'Ảnh chính không thuộc dịch vụ này.'
                    )
                })

            if primary_image_id in delete_image_ids:
                raise serializers.ValidationError({
                    'primary_image_id': (
                        'Không thể chọn ảnh đang được xoá làm ảnh chính.'
                    )
                })

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        images = validated_data.pop('images', [])
        validated_data.pop('delete_image_ids', None)
        validated_data.pop('primary_image_id', None)
        icon_file = validated_data.pop('icon_file', None)
        validated_data.pop('remove_icon', None)

        service = Service.objects.create(**validated_data)

        if icon_file:
            service.icon = save_service_icon(service, icon_file)
            service.save(update_fields=['icon', 'updated_at'])

        for index, image_file in enumerate(images):
            save_service_image(
                service,
                image_file,
                is_primary=(index == 0),
            )

        return service

    @transaction.atomic
    def update(self, instance, validated_data):
        images = validated_data.pop('images', [])
        delete_image_ids = validated_data.pop(
            'delete_image_ids',
            [],
        )
        primary_image_id = validated_data.pop(
            'primary_image_id',
            None,
        )
        icon_file = validated_data.pop('icon_file', None)
        remove_icon = validated_data.pop('remove_icon', False)


        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

  
        old_icon = instance.icon
        if icon_file:
            instance.icon = save_service_icon(instance, icon_file)
            instance.save(update_fields=['icon', 'updated_at'])
            transaction.on_commit(lambda: delete_cloudinary_url(old_icon))
        elif remove_icon and old_icon:
            instance.icon = None
            instance.save(update_fields=['icon', 'updated_at'])
            transaction.on_commit(lambda: delete_cloudinary_url(old_icon))


        for image_id in delete_image_ids:
            image = instance.images.filter(
                id=image_id
            ).first()

            if image:
                delete_service_image(image)

        # --------------------------------------------------
        # 3. Upload ảnh mới
        # --------------------------------------------------
        new_images = []

        for image_file in images:
            new_image = save_service_image(
                instance,
                image_file,
                is_primary=False,
            )
            new_images.append(new_image)

        # --------------------------------------------------
        # 4. Nếu admin chọn ảnh chính cũ
        # --------------------------------------------------
        if primary_image_id is not None:
            instance.images.update(is_primary=False)

            primary_image = instance.images.filter(
                id=primary_image_id
            ).first()

            if primary_image:
                primary_image.is_primary = True
                primary_image.save(
                    update_fields=['is_primary']
                )

        elif not instance.images.filter(
            is_primary=True
        ).exists():
            first_image = instance.images.first()

            if first_image:
                first_image.is_primary = True
                first_image.save(
                    update_fields=['is_primary']
                )

        return instance