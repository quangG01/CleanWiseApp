from pathlib import Path

from django.conf import settings
from rest_framework import serializers
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field

from apps.common.cloudinary_storage import upload_image
from apps.services.utils import extract_cloudinary_public_id

import cloudinary.uploader

from .models import (
    ServiceCategory,
    Service,
    ServiceImage,
    ServicePackage,
)


# ======================================================================================================================
# IMAGE FIELD
# ======================================================================================================================

@extend_schema_field(OpenApiTypes.BINARY)
class ServiceImageFileField(serializers.FileField):
    """
    Field dùng để upload ảnh dịch vụ.

    File:
        -> validate
        -> upload Cloudinary
        -> DB chỉ lưu secure_url
    """

    allowed_extensions = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }

    allowed_content_types = {
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_null", True)
        super().__init__(*args, **kwargs)

    def to_internal_value(self, data):
        if data in ("", None):
            return None

        if not hasattr(data, "read"):
            raise serializers.ValidationError(
                "Ảnh phải được gửi dưới dạng file."
            )

        extension = Path(data.name).suffix.lower()

        if extension not in self.allowed_extensions:
            raise serializers.ValidationError(
                "Ảnh chỉ hỗ trợ định dạng JPG, JPEG, PNG hoặc WEBP."
            )

        content_type = getattr(data, "content_type", "")

        if (
            content_type
            and content_type not in self.allowed_content_types
        ):
            raise serializers.ValidationError(
                "File upload phải là ảnh JPG, JPEG hoặc PNG hoặc WEBP."
            )

        max_size = getattr(
            settings,
            "SERVICE_IMAGE_MAX_SIZE",
            10 * 1024 * 1024,
        )

        if data.size > max_size:
            max_size_mb = max_size // (1024 * 1024)

            raise serializers.ValidationError(
                f"Ảnh không được vượt quá {max_size_mb}MB."
            )

        return data


# ======================================================================================================================
# CLOUDINARY
# ======================================================================================================================

def save_service_image(service, image_file, validated_data=None):
    """
    Upload ảnh service lên Cloudinary
    và tạo ServiceImage trong DB.

    DB chỉ lưu URL Cloudinary.
    """

    validated_data = validated_data or {}

    folder = (
        f"{settings.CLOUDINARY_SERVICE_IMAGE_FOLDER}"
        f"/service_{service.id}"
    )

    uploaded_image = upload_image(
        image_file,
        folder=folder,
        public_id_prefix="service_image",
        field_name="image",
        max_size=getattr(
            settings,
            "SERVICE_IMAGE_MAX_SIZE",
            10 * 1024 * 1024,
        ),
    )

    return ServiceImage.objects.create(
        service=service,
        image=uploaded_image["url"],
        **validated_data,
    )


def delete_service_image(image):
    """
    Xóa ảnh trên Cloudinary.

    DB URL
        -> extract public_id
        -> Cloudinary destroy
        -> xóa record DB
    """

    image_url = image.image

    public_id = extract_cloudinary_public_id(
        image_url
    )

    if public_id:
        try:
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type="image",
            )

            if result.get("result") not in (
                "ok",
                "not found",
            ):
                raise serializers.ValidationError({
                    "images": (
                        "Không thể xoá ảnh "
                        "trên Cloudinary."
                    )
                })

        except serializers.ValidationError:
            raise

        except Exception:
            raise serializers.ValidationError({
                "images": (
                    "Không thể xoá ảnh "
                    "trên Cloudinary."
                )
            })

    image.delete()


# ======================================================================================================================
# SERVICE CATEGORY
# ======================================================================================================================

class ServiceCategorySerializer(serializers.ModelSerializer):

    image = serializers.CharField(
        read_only=True
    )

    image_file = ServiceImageFileField(
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = ServiceCategory

        fields = [
            "id",
            "name",
            "description",
            "icon",
            "image",
            "image_file",
            "is_active",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "image",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):

        image_file = validated_data.pop(
            "image_file",
            None,
        )

        category = ServiceCategory.objects.create(
            **validated_data
        )

        if image_file:

            uploaded_image = upload_image(
                image_file,
                folder=(
                    f"{settings.CLOUDINARY_SERVICE_CATEGORY_FOLDER}"
                    f"/category_{category.id}"
                ),
                public_id_prefix="category_image",
                field_name="image_file",
                max_size=getattr(
                    settings,
                    "SERVICE_CATEGORY_IMAGE_MAX_SIZE",
                    10 * 1024 * 1024,
                ),
            )

            category.image = uploaded_image["url"]

            category.save(
                update_fields=[
                    "image",
                    "updated_at",
                ],
            )

        return category

    def update(self, instance, validated_data):

        image_file = validated_data.pop(
            "image_file",
            None,
        )

        for attr, value in validated_data.items():
            setattr(
                instance,
                attr,
                value,
            )

        if image_file:

            uploaded_image = upload_image(
                image_file,
                folder=(
                    f"{settings.CLOUDINARY_SERVICE_CATEGORY_FOLDER}"
                    f"/category_{instance.id}"
                ),
                public_id_prefix="category_image",
                field_name="image_file",
                max_size=getattr(
                    settings,
                    "SERVICE_CATEGORY_IMAGE_MAX_SIZE",
                    10 * 1024 * 1024,
                ),
            )

            instance.image = uploaded_image["url"]

        instance.save()

        return instance


# ======================================================================================================================
# SERVICE IMAGE READ
# ======================================================================================================================

class ServiceImageSerializer(serializers.ModelSerializer):

    class Meta:
        model = ServiceImage

        fields = [
            "id",
            "image",
            "alt_text",
            "sort_order",
            "is_primary",
        ]

        read_only_fields = [
            "id",
            "image",
        ]


# ======================================================================================================================
# SERVICE PACKAGE
# ======================================================================================================================

class ServicePackageSerializer(serializers.ModelSerializer):

    class Meta:
        model = ServicePackage

        fields = [
            "id",
            "name",
            "description",
            "frequency",
            "number_of_sessions",
            "discount_percent",
            "package_price",
            "is_active",
        ]

        read_only_fields = [
            "id",
        ]


# ======================================================================================================================
# SERVICE LIST
# ======================================================================================================================

class ServiceListSerializer(serializers.ModelSerializer):

    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
    )

    primary_image = serializers.SerializerMethodField()

    class Meta:
        model = Service

        fields = [
            "id",
            "name",
            "category",
            "category_name",
            "base_price",
            "duration_minutes",
            "unit",
            "is_active",
            "primary_image",
        ]

    @extend_schema_field(OpenApiTypes.URI)
    def get_primary_image(self, obj):

        image = obj.images.first()

        if not image:
            return None

        return image.image


# ======================================================================================================================
# SERVICE DETAIL
# ======================================================================================================================

class ServiceDetailSerializer(serializers.ModelSerializer):

    category = ServiceCategorySerializer(
        read_only=True,
    )

    packages = ServicePackageSerializer(
        many=True,
        read_only=True,
    )

    images = ServiceImageSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = Service

        fields = [
            "id",
            "name",
            "description",
            "category",
            "base_price",
            "duration_minutes",
            "unit",
            "min_quantity",
            "max_quantity",
            "is_active",
            "packages",
            "images",
            "created_at",
            "updated_at",
        ]


# ======================================================================================================================
# SERVICE WRITE
# ======================================================================================================================

class ServiceWriteSerializer(serializers.ModelSerializer):
    """
    Serializer tạo/sửa service.

    POST:
        - Thông tin service
        - images: upload 1 ảnh

    PATCH:
        - Cập nhật thông tin service
        - images: upload thêm 1 ảnh
        - delete_image_ids: xoá ảnh cũ

    Với multipart/form-data:

        name = Vệ sinh nhà
        category = 1
        base_price = 300000
        images = file.jpg

    delete_image_ids có thể gửi:

        1,2,3

    hoặc:

        [1,2,3]
    """

    images = ServiceImageFileField(
        required=False,
        allow_null=True,
        write_only=True,
    )

    delete_image_ids = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
    )

    class Meta:
        model = Service

        fields = [
            "id",
            "category",
            "name",
            "description",
            "base_price",
            "duration_minutes",
            "unit",
            "min_quantity",
            "max_quantity",
            "is_active",
            "images",
            "delete_image_ids",
        ]

        read_only_fields = [
            "id",
        ]

    def _parse_delete_image_ids(self, value):
        """
        Chuyển delete_image_ids thành list[int].
        """

        if value in (
            None,
            "",
            [],
        ):
            return []

        if isinstance(value, list):

            try:
                return [
                    int(x)
                    for x in value
                ]
            except (
                ValueError,
                TypeError,
            ):
                raise serializers.ValidationError(
                    "delete_image_ids phải là danh sách ID hợp lệ."
                )

        value = str(value).strip()

        if not value:
            return []

        # ---------------------------------------------------------
        # JSON:
        # [1,2,3]
        # ---------------------------------------------------------

        if (
            value.startswith("[")
            and value.endswith("]")
        ):
            import json

            try:
                data = json.loads(value)

                if not isinstance(data, list):
                    raise ValueError

                return [
                    int(x)
                    for x in data
                ]

            except (
                ValueError,
                TypeError,
            ):
                raise serializers.ValidationError(
                    "delete_image_ids phải có dạng [1,2,3]."
                )

        # ---------------------------------------------------------
        # CSV:
        # 1,2,3
        # ---------------------------------------------------------

        try:
            return [
                int(x.strip())
                for x in value.split(",")
                if x.strip()
            ]

        except ValueError:
            raise serializers.ValidationError(
                "delete_image_ids phải có dạng 1,2,3 hoặc [1,2,3]."
            )

    def validate(self, attrs):

        category = attrs.get(
            "category",
            getattr(
                self.instance,
                "category",
                None,
            ),
        )

        name = attrs.get(
            "name",
            getattr(
                self.instance,
                "name",
                None,
            ),
        )

        # ---------------------------------------------------------
        # Kiểm tra service trùng
        # ---------------------------------------------------------

        queryset = Service.objects.filter(
            category=category,
            name=name,
        )

        if self.instance:

            queryset = queryset.exclude(
                pk=self.instance.pk,
            )

        if queryset.exists():

            raise serializers.ValidationError({
                "name": (
                    "Dịch vụ này đã tồn tại "
                    "trong danh mục."
                )
            })

        # ---------------------------------------------------------
        # Parse delete_image_ids
        # ---------------------------------------------------------

        delete_image_ids = (
            self._parse_delete_image_ids(
                attrs.get(
                    "delete_image_ids"
                )
            )
        )

        attrs["delete_image_ids"] = (
            delete_image_ids
        )

        # ---------------------------------------------------------
        # Validate delete_image_ids
        # ---------------------------------------------------------

        if (
            self.instance
            and delete_image_ids
        ):

            existing_ids = set(
                self.instance.images.filter(
                    id__in=delete_image_ids
                ).values_list(
                    "id",
                    flat=True,
                )
            )

            invalid_ids = (
                set(delete_image_ids)
                - existing_ids
            )

            if invalid_ids:

                raise serializers.ValidationError({
                    "delete_image_ids": (
                        "Một hoặc nhiều ảnh "
                        "không thuộc dịch vụ này."
                    )
                })

        elif (
            delete_image_ids
            and not self.instance
        ):

            raise serializers.ValidationError({
                "delete_image_ids": (
                    "Không thể xoá ảnh khi "
                    "đang tạo dịch vụ."
                )
            })

        return attrs

    def create(self, validated_data):

        image_file = validated_data.pop(
            "images",
            None,
        )

        validated_data.pop(
            "delete_image_ids",
            [],
        )

        # ---------------------------------------------------------
        # Tạo service
        # ---------------------------------------------------------

        service = Service.objects.create(
            **validated_data
        )

        # ---------------------------------------------------------
        # Upload ảnh
        # ---------------------------------------------------------

        if image_file:

            save_service_image(
                service=service,
                image_file=image_file,
            )

        return service

    def update(
        self,
        instance,
        validated_data,
    ):

        image_file = validated_data.pop(
            "images",
            None,
        )

        delete_image_ids = (
            validated_data.pop(
                "delete_image_ids",
                [],
            )
        )

        # ---------------------------------------------------------
        # Update service
        # ---------------------------------------------------------

        for attr, value in validated_data.items():

            setattr(
                instance,
                attr,
                value,
            )

        instance.save()

        # ---------------------------------------------------------
        # Xóa ảnh cũ
        # ---------------------------------------------------------

        for image_id in delete_image_ids:

            image = instance.images.filter(
                id=image_id
            ).first()

            if image:

                delete_service_image(
                    image
                )

        # ---------------------------------------------------------
        # Upload ảnh mới
        # ---------------------------------------------------------

        if image_file:

            save_service_image(
                service=instance,
                image_file=image_file,
            )

        return instance
