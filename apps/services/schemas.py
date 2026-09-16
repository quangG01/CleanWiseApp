# apps/services/schemas.py
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view

from .serializers import ServiceAdminWriteSerializer, ServiceDetailSerializer, ServiceListSerializer

SERVICE_LIST_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Danh sách dịch vụ (khách hàng)',
        description='Ai cũng xem được. Chỉ trả dịch vụ đang hoạt động.',
        tags=['Services'],
        parameters=[
            OpenApiParameter(name='section_code', type=str, required=False),
            OpenApiParameter(name='search', type=str, required=False),
        ],
        responses={200: ServiceListSerializer(many=True)},
    ),
)

SERVICE_DETAIL_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Chi tiết dịch vụ (khách hàng)',
        description='Trả về form_schema và pricing_config để FE dựng form đặt lịch.',
        tags=['Services'],
        responses={200: ServiceDetailSerializer},
    ),
)

ADMIN_SERVICE_LIST_CREATE_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Danh sách dịch vụ (admin)',
        tags=['Services - Admin'],
        parameters=[
            OpenApiParameter(name='section_code', type=str, required=False),
            OpenApiParameter(name='is_active', type=bool, required=False),
            OpenApiParameter(name='search', type=str, required=False),
        ],
        responses={200: ServiceListSerializer(many=True)},
    ),
    post=extend_schema(
        summary='Tạo dịch vụ mới',
        description='Chỉ Admin. form_schema/pricing_config gửi dạng object JSON.',
        tags=['Services - Admin'],
        request=ServiceAdminWriteSerializer,
        responses={201: ServiceDetailSerializer},
    ),
)

ADMIN_SERVICE_DETAIL_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Chi tiết dịch vụ (admin)',
        tags=['Services - Admin'],
        responses={200: ServiceDetailSerializer},
    ),
    patch=extend_schema(
        summary='Cập nhật dịch vụ',
        description='Chỉ Admin. Cập nhật từng phần: giá, mô tả, form_schema, ảnh...',
        tags=['Services - Admin'],
        request=ServiceAdminWriteSerializer,
        responses={200: ServiceDetailSerializer},
    ),
)