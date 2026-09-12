from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
)

from .serializers import (
    ServiceCategorySerializer,
    ServiceDetailSerializer,
    ServiceListSerializer,
    ServicePackageSerializer,
    ServiceWriteSerializer,
)


# ======================================================================================================================
# SERVICE CATEGORY
# ======================================================================================================================

SERVICE_CATEGORY_LIST_SCHEMA = extend_schema_view(

    get=extend_schema(
        summary="Danh sách loại dịch vụ",
        description=(
            "Ai cũng có thể xem danh sách "
            "loại dịch vụ."
        ),
        tags=["Services"],
        parameters=[
            OpenApiParameter(
                name="is_active",
                type=bool,
                required=False,
                description=(
                    "Lọc theo trạng thái hoạt động."
                ),
            ),
        ],
        responses={
            200: ServiceCategorySerializer(
                many=True
            ),
        },
    ),

    post=extend_schema(
        summary="Tạo loại dịch vụ",
        description=(
            "Chỉ Admin mới được tạo loại dịch vụ.\n\n"
            "Request sử dụng multipart/form-data.\n"
            "Có thể upload ảnh bằng trường image_file."
        ),
        tags=["Services"],
        request=ServiceCategorySerializer,
        responses={
            201: ServiceCategorySerializer,
        },
    ),
)


# ======================================================================================================================
# SERVICE CATEGORY DETAIL
# ======================================================================================================================

SERVICE_CATEGORY_DETAIL_SCHEMA = extend_schema_view(

    get=extend_schema(
        summary="Chi tiết loại dịch vụ",
        description=(
            "Xem chi tiết một loại dịch vụ."
        ),
        tags=["Services"],
        responses={
            200: ServiceCategorySerializer,
        },
    ),

    patch=extend_schema(
        summary="Cập nhật loại dịch vụ",
        description=(
            "Chỉ Admin mới được cập nhật.\n\n"
            "Request sử dụng multipart/form-data.\n"
            "Có thể cập nhật thông tin, bật/tắt "
            "loại dịch vụ và upload image_file."
        ),
        tags=["Services"],
        request=ServiceCategorySerializer,
        responses={
            200: ServiceCategorySerializer,
        },
    ),
)


# ======================================================================================================================
# SERVICE
# ======================================================================================================================

SERVICE_LIST_SCHEMA = extend_schema_view(

    get=extend_schema(
        summary="Danh sách dịch vụ",
        description=(
            "Danh sách dịch vụ.\n\n"
            "Hỗ trợ:\n"
            "- Lọc theo category_id\n"
            "- Lọc theo is_active\n"
            "- Tìm kiếm theo tên dịch vụ"
        ),
        tags=["Services"],
        parameters=[
            OpenApiParameter(
                name="category_id",
                type=int,
                required=False,
                description=(
                    "Lọc theo ID loại dịch vụ."
                ),
            ),
            OpenApiParameter(
                name="is_active",
                type=bool,
                required=False,
                description=(
                    "Lọc theo trạng thái hoạt động."
                ),
            ),
            OpenApiParameter(
                name="search",
                type=str,
                required=False,
                description=(
                    "Tìm kiếm theo tên dịch vụ."
                ),
            ),
        ],
        responses={
            200: ServiceListSerializer(
                many=True
            ),
        },
    ),

    post=extend_schema(
        summary="Tạo dịch vụ",
        description=(
            "Chỉ Admin mới được tạo dịch vụ.\n\n"
            "Request sử dụng multipart/form-data.\n"
            "Có thể upload ảnh bằng trường images."
        ),
        tags=["Services"],
        request=ServiceWriteSerializer,
        responses={
            201: ServiceDetailSerializer,
        },
    ),
)


# ======================================================================================================================
# SERVICE DETAIL
# ======================================================================================================================

SERVICE_DETAIL_SCHEMA = extend_schema_view(

    get=extend_schema(
        summary="Chi tiết dịch vụ",
        description=(
            "Trả về thông tin dịch vụ "
            "kèm danh sách packages và images."
        ),
        tags=["Services"],
        responses={
            200: ServiceDetailSerializer,
        },
    ),

    patch=extend_schema(
        summary="Cập nhật dịch vụ",
        description=(
            "Chỉ Admin mới được cập nhật dịch vụ.\n\n"
            "Request sử dụng multipart/form-data.\n\n"
            "Có thể:\n"
            "- Cập nhật thông tin dịch vụ\n"
            "- Upload ảnh mới bằng images\n"
            "- Xóa ảnh cũ bằng delete_image_ids"
        ),
        tags=["Services"],
        request=ServiceWriteSerializer,
        responses={
            200: ServiceDetailSerializer,
        },
    ),
)


# ======================================================================================================================
# SERVICE PACKAGE
# ======================================================================================================================

SERVICE_PACKAGE_LIST_SCHEMA = extend_schema_view(

    get=extend_schema(
        summary="Danh sách gói dịch vụ",
        description=(
            "Lấy danh sách các gói thuộc một dịch vụ."
        ),
        tags=["Services"],
        responses={
            200: ServicePackageSerializer(
                many=True
            ),
        },
    ),

    post=extend_schema(
        summary="Tạo gói dịch vụ",
        description=(
            "Chỉ Admin mới được tạo gói dịch vụ."
        ),
        tags=["Services"],
        request=ServicePackageSerializer,
        responses={
            201: ServicePackageSerializer,
        },
    ),
)
