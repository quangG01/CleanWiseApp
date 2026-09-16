"""OpenAPI documentation for booking and voucher endpoints."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers

from .models import Voucher
from .serializers import (
    UserVoucherSerializer,
    VoucherAdminSerializer,
    VoucherAdminWriteSerializer,
    VoucherCodeClaimSerializer,
)


VoucherAdminResponse = inline_serializer(
    name='VoucherAdminResponse',
    fields={
        'message': serializers.CharField(),
        'data': VoucherAdminSerializer(),
    },
)

VoucherAdminListResponse = inline_serializer(
    name='VoucherAdminListResponse',
    fields={
        'message': serializers.CharField(),
        'data': VoucherAdminSerializer(many=True),
    },
)

VoucherMessageResponse = inline_serializer(
    name='VoucherMessageResponse',
    fields={'message': serializers.CharField()},
)

UserVoucherClaimResponse = inline_serializer(
    name='UserVoucherClaimResponse',
    fields={
        'message': serializers.CharField(),
        'data': UserVoucherSerializer(),
    },
)

UserVoucherListResponse = inline_serializer(
    name='UserVoucherListResponse',
    fields={
        'message': serializers.CharField(),
        'data': UserVoucherSerializer(many=True),
    },
)

VOUCHER_REQUEST_EXAMPLES = [
    OpenApiExample(
        'Voucher giảm theo phần trăm',
        value={
            'code': 'WELCOME20',
            'name': 'Ưu đãi khách hàng mới',
            'description': 'Giảm 20%, tối đa 50000đ cho đơn từ 200000đ.',
            'distribution_type': Voucher.DistributionType.PUBLIC,
            'discount_type': Voucher.DiscountType.PERCENT,
            'discount_value': '20.00',
            'max_discount_amount': '50000.00',
            'min_order_amount': '200000.00',
            'issuance_limit': 1000,
            'start_at': '2026-09-16T00:00:00+07:00',
            'end_at': '2026-12-31T23:59:59+07:00',
            'is_active': True,
        },
        request_only=True,
    ),
    OpenApiExample(
        'Voucher giảm số tiền cố định',
        description='Với FIXED, không truyền max_discount_amount hoặc đặt là null.',
        value={
            'code': 'GIAM50K',
            'name': 'Giảm ngay 50.000đ',
            'distribution_type': Voucher.DistributionType.CODE_ONLY,
            'discount_type': Voucher.DiscountType.FIXED,
            'discount_value': '50000.00',
            'max_discount_amount': None,
            'min_order_amount': '300000.00',
            'issuance_limit': None,
            'start_at': '2026-09-16T00:00:00+07:00',
            'end_at': '2026-12-31T23:59:59+07:00',
            'is_active': True,
        },
        request_only=True,
    ),
]


ADMIN_VOUCHER_LIST_CREATE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='admin_voucher_list',
        summary='Danh sách voucher dành cho admin',
        description='Lấy tất cả voucher và có thể lọc theo trạng thái, loại giảm, cách phát hành hoặc từ khóa.',
        tags=['Voucher - Admin'],
        parameters=[
            OpenApiParameter(
                name='is_active',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description='Lọc voucher đang bật (true) hoặc đã tắt (false).',
            ),
            OpenApiParameter(
                name='discount_type',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                enum=Voucher.DiscountType.values,
                description='PERCENT hoặc FIXED.',
            ),
            OpenApiParameter(
                name='distribution_type',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                enum=Voucher.DistributionType.values,
                description='PUBLIC, CODE_ONLY hoặc ASSIGNED.',
            ),
            OpenApiParameter(
                name='search',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Tìm gần đúng theo mã hoặc tên voucher.',
            ),
        ],
        responses={200: VoucherAdminListResponse},
    ),
    post=extend_schema(
        operation_id='admin_voucher_create',
        summary='Tạo voucher mới',
        description=(
            'Tạo voucher và tự khởi tạo số lượng đã phát bằng 0. '
            'PERCENT yêu cầu discount_value từ 0.01 đến 100 và có thể đặt max_discount_amount. '
            'FIXED không được đặt max_discount_amount. end_at phải sau start_at.'
        ),
        tags=['Voucher - Admin'],
        request=VoucherAdminWriteSerializer,
        examples=VOUCHER_REQUEST_EXAMPLES,
        responses={
            201: VoucherAdminResponse,
            400: OpenApiResponse(description='Payload không hợp lệ hoặc mã voucher đã tồn tại.'),
            401: OpenApiResponse(description='Chưa đăng nhập.'),
            403: OpenApiResponse(description='Tài khoản không có quyền admin.'),
        },
    ),
)


ADMIN_VOUCHER_DETAIL_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='admin_voucher_detail',
        summary='Chi tiết voucher dành cho admin',
        tags=['Voucher - Admin'],
        responses={200: VoucherAdminResponse, 404: OpenApiResponse(description='Không tìm thấy voucher.')},
    ),
    patch=extend_schema(
        operation_id='admin_voucher_update',
        summary='Cập nhật một phần voucher',
        description=(
            'Chỉ gửi các trường cần thay đổi. Các quy tắc về loại giảm, giá trị giảm, '
            'thời gian hiệu lực và giới hạn phát hành giống API tạo mới.'
        ),
        tags=['Voucher - Admin'],
        request=VoucherAdminWriteSerializer,
        responses={
            200: VoucherAdminResponse,
            400: OpenApiResponse(description='Dữ liệu cập nhật không hợp lệ.'),
            404: OpenApiResponse(description='Không tìm thấy voucher.'),
        },
    ),
    delete=extend_schema(
        operation_id='admin_voucher_disable',
        summary='Ngừng sử dụng voucher',
        description='Không xóa dữ liệu; API chỉ chuyển is_active thành false.',
        tags=['Voucher - Admin'],
        responses={200: VoucherMessageResponse, 404: OpenApiResponse(description='Không tìm thấy voucher.')},
    ),
)


ADMIN_VOUCHER_BY_CODE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='admin_voucher_detail_by_code',
        summary='Lấy chi tiết voucher theo mã',
        description='Mã voucher không phân biệt chữ hoa, chữ thường.',
        tags=['Voucher - Admin'],
        parameters=[
            OpenApiParameter(
                name='code',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description='Mã voucher, ví dụ WELCOME20.',
            ),
        ],
        responses={200: VoucherAdminResponse, 404: OpenApiResponse(description='Không tìm thấy voucher.')},
    ),
)


CUSTOMER_CODE_VOUCHER_CLAIM_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='customer_voucher_claim_by_code',
        summary='Nhận voucher bằng mã',
        description=(
            'Nhận voucher PUBLIC hoặc CODE_ONLY bằng mã. Backend tự xác định source tương ứng; '
            'mã không phân biệt chữ hoa, chữ thường. Voucher phải còn hiệu lực, còn lượt phát hành '
            'và chưa có trong ví khách hàng. Voucher ASSIGNED không thể tự nhận qua API này.'
        ),
        tags=['Voucher - Customer'],
        request=VoucherCodeClaimSerializer,
        examples=[
            OpenApiExample(
                'Nhập mã voucher',
                value={'code': 'GIAM50K'},
                request_only=True,
            ),
        ],
        responses={
            201: UserVoucherClaimResponse,
            400: OpenApiResponse(description='Mã không hợp lệ, voucher không thể nhận hoặc đã được nhận.'),
        },
    ),
)


CUSTOMER_VOUCHER_WALLET_LIST_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='customer_voucher_wallet_list',
        summary='Danh sách voucher trong ví của khách hàng',
        description=(
            'Trả về tất cả voucher khách hàng đã nhận hoặc được cấp. Mỗi phần tử có source, '
            'status và is_usable để frontend xác định voucher còn áp dụng được hay không.'
        ),
        tags=['Voucher - Customer'],
        responses={200: UserVoucherListResponse},
    ),
)
