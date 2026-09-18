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
    BookingCreateSerializer,
    BookingDetailSerializer,
    BookingListSerializer,
    AreaSummarySerializer,
    UserVoucherSerializer,
    VoucherAdminSerializer,
    VoucherAdminWriteSerializer,
    VoucherCodeClaimSerializer,
    WorkerWorkingAreaSerializer,
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

WorkerWorkingAreaResponse = inline_serializer(
    name='WorkerWorkingAreaResponse',
    fields={
        'message': serializers.CharField(),
        'data': WorkerWorkingAreaSerializer(),
    },
)

WorkerWorkingAreaListResponse = inline_serializer(
    name='WorkerWorkingAreaListResponse',
    fields={
        'message': serializers.CharField(),
        'data': WorkerWorkingAreaSerializer(many=True),
    },
)

WorkerWorkingAreaMessageResponse = inline_serializer(
    name='WorkerWorkingAreaMessageResponse',
    fields={'message': serializers.CharField()},
)


WORKER_ACTIVE_AREA_LIST_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='worker_active_area_list',
        summary='Danh mục khu vực đang hoạt động',
        description=(
            '### Mục đích\n'
            'Cung cấp danh mục khu vực để nhân viên lựa chọn nơi có thể làm việc.\n\n'
            '### Bộ lọc\n'
            '- `city`: lọc chính xác theo tỉnh/thành phố.\n'
            '- `search`: tìm gần đúng theo tên khu vực hoặc tỉnh/thành phố.\n\n'
            'Chỉ các khu vực đang hoạt động được trả về.'
        ),
        tags=['Worker - Working Areas'],
        parameters=[
            OpenApiParameter(
                name='city',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Lọc chính xác theo tỉnh/thành phố, không phân biệt hoa thường.',
            ),
            OpenApiParameter(
                name='search',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Tìm gần đúng theo tên khu vực hoặc tỉnh/thành phố.',
            ),
        ],
        responses={200: AreaSummarySerializer(many=True)},
    ),
)


WORKER_WORKING_AREA_LIST_CREATE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='worker_working_area_list',
        summary='Danh sách khu vực làm việc của nhân viên',
        description=(
            '### Mục đích\n'
            'Trả về các khu vực mà nhân viên đang đăng nhập đã chọn để nhận việc.\n\n'
            '> Nhân viên chỉ xem được dữ liệu của chính mình.'
        ),
        tags=['Worker - Working Areas'],
        responses={200: WorkerWorkingAreaListResponse},
    ),
    post=extend_schema(
        operation_id='worker_working_area_create',
        summary='Thêm khu vực làm việc',
        description=(
            '### Cách sử dụng\n'
            '1. Gọi `GET /api/worker/areas/` để lấy danh mục.\n'
            '2. Chọn một khu vực và gửi ID vào `area_id`.\n\n'
            '### Quy tắc\n'
            '- Khu vực phải đang hoạt động.\n'
            '- Nhân viên không thể chọn trùng một khu vực.\n'
            '- Backend tự lấy nhân viên từ access token.'
        ),
        tags=['Worker - Working Areas'],
        request=WorkerWorkingAreaSerializer,
        examples=[
            OpenApiExample(
                'Chọn khu vực',
                value={'area_id': 3},
                request_only=True,
            ),
        ],
        responses={
            201: WorkerWorkingAreaResponse,
            400: OpenApiResponse(description='Khu vực không hợp lệ hoặc đã được chọn.'),
            403: OpenApiResponse(description='Tài khoản không có quyền nhân viên.'),
        },
    ),
)


WORKER_WORKING_AREA_DETAIL_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='worker_working_area_detail',
        summary='Chi tiết khu vực làm việc đã chọn',
        description=(
            'Trả về một khu vực làm việc đã chọn của nhân viên đang đăng nhập.\n\n'
            '> Truy cập lựa chọn của nhân viên khác sẽ trả về `404`.'
        ),
        tags=['Worker - Working Areas'],
        responses={
            200: WorkerWorkingAreaResponse,
            404: OpenApiResponse(description='Không tìm thấy lựa chọn khu vực của nhân viên hiện tại.'),
        },
    ),
    patch=extend_schema(
        operation_id='worker_working_area_update',
        summary='Thay đổi khu vực làm việc đã chọn',
        description=(
            '### Cách sử dụng\n'
            '- Gửi `area_id` mới để thay đổi khu vực.\n'
            '- Khu vực mới phải đang hoạt động và chưa được nhân viên chọn trước đó.'
        ),
        tags=['Worker - Working Areas'],
        request=WorkerWorkingAreaSerializer,
        responses={
            200: WorkerWorkingAreaResponse,
            400: OpenApiResponse(description='Khu vực không hợp lệ hoặc đã được chọn.'),
            404: OpenApiResponse(description='Không tìm thấy lựa chọn khu vực của nhân viên hiện tại.'),
        },
    ),
    delete=extend_schema(
        operation_id='worker_working_area_delete',
        summary='Xóa khu vực khỏi danh sách làm việc',
        description=(
            '### Phạm vi xóa\n'
            '- Chỉ xóa lựa chọn khu vực của nhân viên đang đăng nhập.\n'
            '- Không xóa khu vực khỏi danh mục chung của hệ thống.'
        ),
        tags=['Worker - Working Areas'],
        responses={
            200: WorkerWorkingAreaMessageResponse,
            404: OpenApiResponse(description='Không tìm thấy lựa chọn khu vực của nhân viên hiện tại.'),
        },
    ),
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


BOOKING_CUSTOMER_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='customer_booking_list',
        summary='Danh sách đơn hàng của khách hàng',
        description='Lấy danh sách booking theo tài khoản hiện tại, có thể lọc theo trạng thái và phân trang.',
        tags=['Booking - Customer'],
        responses={200: OpenApiResponse(description='Danh sách đơn hàng của khách hàng.')},
    ),
    post=extend_schema(
        operation_id='customer_booking_create',
        summary='Tạo booking mới',
        description='Khách hàng đặt dịch vụ bằng cách gửi thông tin dịch vụ, địa chỉ, lịch làm việc và có thể áp dụng voucher nếu hợp lệ.',
        tags=['Booking - Customer'],
        request=BookingCreateSerializer,
        responses={
            201: OpenApiResponse(description='Đặt dịch vụ thành công.'),
            400: OpenApiResponse(description='Dữ liệu đầu vào không hợp lệ.'),
        },
    ),
)


BOOKING_DETAIL_CUSTOMER_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='customer_booking_detail',
        summary='Chi tiết đơn hàng của khách hàng',
        description='Lấy thông tin chi tiết của một booking gồm dịch vụ, lịch trình, thông tin giá và trạng thái hiện tại.',
        tags=['Booking - Customer'],
        responses={200: OpenApiResponse(description='Chi tiết booking.')},
    ),
)


BOOKING_ADMIN_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='admin_assign_worker',
        summary='Gán nhân viên cho lịch làm việc',
        description='Quản trị viên phân công nhân viên cho một buổi làm việc cụ thể trong booking.',
        tags=['Booking - Admin'],
        request=BookingCreateSerializer,
        responses={
            201: OpenApiResponse(description='Gán nhân viên thành công.'),
            400: OpenApiResponse(description='Dữ liệu đầu vào không hợp lệ.'),
        },
    ),
)


BOOKING_WORKER_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='worker_schedule_available_list',
        summary='Danh sách lịch khả dụng cho worker',
        description='Hiển thị các buổi làm việc còn trống mà nhân viên có thể nhận để làm việc.',
        tags=['Booking - Worker'],
        responses={200: OpenApiResponse(description='Danh sách lịch khả dụng.')},
    ),
    post=extend_schema(
        operation_id='worker_claim_schedule',
        summary='Nhận việc cho lịch làm việc',
        description='Nhân viên nhận một buổi làm việc được phân công hoặc sẵn sàng để thực hiện.',
        tags=['Booking - Worker'],
        responses={
            201: OpenApiResponse(description='Nhận việc thành công.'),
            400: OpenApiResponse(description='Không thể nhận việc.'),
        },
    ),
)


BOOKING_WORKER_ASSIGNMENT_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='worker_cancel_assignment',
        summary='Hủy nhận việc',
        description='Nhân viên hủy lịch làm việc đã nhận và cung cấp lý do hủy.',
        tags=['Booking - Worker'],
        responses={200: OpenApiResponse(description='Hủy nhận việc thành công.')},
    ),
)
