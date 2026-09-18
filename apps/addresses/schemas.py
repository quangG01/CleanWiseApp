from rest_framework import serializers
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from .serializers import CustomerAddressSerializer

ADDRESS_LIST_CREATE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='customer_address_list',
        summary='Danh sách địa chỉ khách hàng',
        description='Lấy danh sách tất cả các địa chỉ đang hoạt động của khách hàng đang đăng nhập, sắp xếp theo mặc định và thời gian tạo.',
        tags=['Customer - Addresses'],
        responses={
            200: inline_serializer(
                name='CustomerAddressListSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': CustomerAddressSerializer(many=True),
                },
            )
        },
    ),
    post=extend_schema(
        operation_id='customer_address_create',
        summary='Thêm địa chỉ mới',
        description='Thêm một địa chỉ nhận dịch vụ mới. Nếu đây là địa chỉ đầu tiên hoặc được đánh dấu `is_default=True`, hệ thống sẽ tự động đặt làm địa chỉ mặc định.',
        request=CustomerAddressSerializer,
        tags=['Customer - Addresses'],
        responses={
            201: inline_serializer(
                name='CustomerAddressCreateSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': CustomerAddressSerializer(),
                },
            ),
            400: OpenApiResponse(description='Dữ liệu không hợp lệ hoặc số điện thoại không đúng định dạng.'),
        },
    ),
)

ADDRESS_DETAIL_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='customer_address_retrieve',
        summary='Chi tiết địa chỉ',
        description='Lấy thông tin chi tiết của một địa chỉ dựa trên ID.',
        tags=['Customer - Addresses'],
        responses={
            200: inline_serializer(
                name='CustomerAddressRetrieveSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': CustomerAddressSerializer(),
                },
            ),
            404: OpenApiResponse(description='Không tìm thấy địa chỉ hoặc không có quyền truy cập.'),
        },
    ),
    patch=extend_schema(
        operation_id='customer_address_partial_update',
        summary='Cập nhật địa chỉ',
        description='Cập nhật từng phần thông tin địa chỉ (như tên người nhận, số điện thoại, định vị GPS, v.v.).',
        request=CustomerAddressSerializer,
        tags=['Customer - Addresses'],
        responses={
            200: inline_serializer(
                name='CustomerAddressUpdateSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': CustomerAddressSerializer(),
                },
            ),
            400: OpenApiResponse(description='Lỗi dữ liệu hoặc cố tình bỏ chọn mặc định trực tiếp.'),
        },
    ),
    delete=extend_schema(
        operation_id='customer_address_destroy',
        summary='Xóa địa chỉ (Xóa mềm)',
        description='Đưa trạng thái địa chỉ sang `is_active=False` (xóa mềm) thay vì xóa vĩnh khỏi cơ sở dữ liệu.',
        tags=['Customer - Addresses'],
        responses={
            200: OpenApiResponse(description='Xóa địa chỉ thành công.'),
            404: OpenApiResponse(description='Không tìm thấy địa chỉ.'),
        },
    ),
)

ADDRESS_SET_DEFAULT_SCHEMA = extend_schema_view(
    patch=extend_schema(
        operation_id='customer_address_set_default',
        summary='Đặt làm địa chỉ mặc định',
        description='Chuyển một địa chỉ bất kỳ thành địa chỉ mặc định của khách hàng. Các địa chỉ khác sẽ tự động mất trạng thái mặc định.',
        tags=['Customer - Addresses'],
        responses={
            200: inline_serializer(
                name='CustomerAddressSetDefaultSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': CustomerAddressSerializer(),
                },
            ),
            404: OpenApiResponse(description='Không tìm thấy địa chỉ.'),
        },
    ),
)