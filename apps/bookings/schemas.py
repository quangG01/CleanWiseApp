from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)

from .serializers import (
    CustomerAddressSerializer,
    UserVoucherAdminSerializer,
    UserVoucherCustomerSerializer,
    VoucherAdminSerializer,
    VoucherClaimCodeSerializer,
    VoucherPublicSerializer,
)


CUSTOMER_ADDRESS_LIST_CREATE_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Lấy danh sách địa điểm khách hàng',
        description='Chỉ trả các địa điểm đang hoạt động của khách hàng hiện tại; địa điểm mặc định đứng đầu.',
        tags=['2. Customer Addresses'],
        responses={200: CustomerAddressSerializer(many=True)},
    ),
    post=extend_schema(
        summary='Thêm địa điểm khách hàng',
        description='''
        Thêm địa điểm theo mô hình hành chính hai cấp gồm tỉnh/thành phố và xã/phường/đặc khu.
        Địa điểm đầu tiên tự động trở thành mặc định. Nếu `is_default=true`, backend sẽ bỏ
        mặc định ở địa điểm khác. `area_id` phải là khu vực phục vụ đang hoạt động và phải
        khớp với `city`, `ward`.
        ''',
        tags=['2. Customer Addresses'],
        request=CustomerAddressSerializer,
        responses={201: CustomerAddressSerializer},
    ),
)

CUSTOMER_ADDRESS_DETAIL_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Xem chi tiết địa điểm',
        description='Chỉ chủ sở hữu mới được xem địa điểm đang hoạt động.',
        tags=['2. Customer Addresses'],
        responses={200: CustomerAddressSerializer},
    ),
    patch=extend_schema(
        summary='Chỉnh sửa địa điểm',
        description='''
        Cập nhật từng phần; chỉ cần gửi các field muốn thay đổi. Không thể bỏ mặc định trực tiếp
        khỏi địa điểm hiện tại; hãy đặt địa điểm khác làm mặc định. Không cho sửa địa điểm đã xóa mềm.
        ''',
        tags=['2. Customer Addresses'],
        request=CustomerAddressSerializer,
        responses={200: CustomerAddressSerializer},
    ),
    delete=extend_schema(
        summary='Xóa địa điểm',
        description='Xóa mềm bằng cách đặt `is_active=false`. Nếu xóa địa điểm mặc định, backend tự chọn địa điểm thay thế.',
        tags=['2. Customer Addresses'],
        responses={200: OpenApiResponse(description='Xóa địa điểm thành công.')},
    ),
)

CUSTOMER_ADDRESS_SET_DEFAULT_SCHEMA = extend_schema_view(
    patch=extend_schema(
        summary='Đặt địa điểm mặc định',
        description='Đặt địa điểm đang hoạt động của khách hàng hiện tại làm địa điểm mặc định duy nhất.',
        tags=['2. Customer Addresses'],
        request=None,
        responses={200: CustomerAddressSerializer},
    )
)

ADMIN_VOUCHER_LIST_CREATE_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Danh sách voucher cho admin',
        description='Liệt kê voucher, hỗ trợ lọc trạng thái hoạt động, loại giảm giá và tìm theo code hoặc tên.',
        tags=['3. Vouchers - Admin'],
        parameters=[
            OpenApiParameter(name='is_active', type=bool, required=False),
            OpenApiParameter(
                name='discount_type',
                type=str,
                required=False,
                enum=['PERCENT', 'FIXED'],
            ),
            OpenApiParameter(
                name='distribution_type',
                type=str,
                required=False,
                enum=['PUBLIC', 'CODE_ONLY', 'ASSIGNED'],
            ),
            OpenApiParameter(name='search', type=str, required=False),
        ],
        responses={200: VoucherAdminSerializer(many=True)},
    ),
    post=extend_schema(
        summary='Tạo voucher',
        description='''
        Tạo voucher toàn hệ thống. `code` được chuẩn hóa thành chữ hoa. Với loại PERCENT,
        `discount_value` không được vượt quá 100. `start_at` phải trước `end_at`.
        ''',
        tags=['3. Vouchers - Admin'],
        request=VoucherAdminSerializer,
        responses={201: VoucherAdminSerializer},
    ),
)

ADMIN_VOUCHER_DETAIL_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Xem chi tiết voucher',
        tags=['3. Vouchers - Admin'],
        responses={200: VoucherAdminSerializer},
    ),
    patch=extend_schema(
        summary='Cập nhật voucher',
        description='''
        Cập nhật từng phần. Sau khi voucher đã phát sinh lượt dùng, không được sửa code,
        loại/giá trị giảm, mức giảm tối đa, đơn tối thiểu, thời gian bắt đầu hoặc giới hạn mỗi người.
        Admin vẫn có thể sửa tên, mô tả, thời gian kết thúc, tăng tổng lượt và bật/tắt voucher.
        ''',
        tags=['3. Vouchers - Admin'],
        request=VoucherAdminSerializer,
        responses={200: VoucherAdminSerializer},
    ),
    delete=extend_schema(
        summary='Ngừng sử dụng voucher',
        description='Xóa mềm bằng cách đặt `is_active=false`; lịch sử sử dụng được giữ nguyên.',
        tags=['3. Vouchers - Admin'],
        responses={200: OpenApiResponse(description='Ngừng sử dụng voucher thành công.')},
    ),
)

CUSTOMER_AVAILABLE_VOUCHER_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Danh sách voucher công khai có thể nhận',
        description='''
        Chỉ trả voucher PUBLIC đang hoạt động, trong thời gian hiệu lực, còn lượt toàn hệ thống
        và khách hàng hiện tại chưa từng nhận. CODE_ONLY và ASSIGNED không xuất hiện tại đây.
        ''',
        tags=['4. Customer Vouchers'],
        responses={200: VoucherPublicSerializer(many=True)},
    ),
)

CUSTOMER_VOUCHER_CLAIM_SCHEMA = extend_schema_view(
    post=extend_schema(
        summary='Nhận voucher công khai',
        description='''
        Nhận voucher PUBLIC vào ví. Gọi lại cùng voucher không tạo bản ghi trùng; nếu voucher
        từng bị ẩn thì backend hiển thị lại. Nhận voucher chưa tăng used_count và chưa áp dụng booking.
        ''',
        tags=['4. Customer Vouchers'],
        request=None,
        responses={
            200: UserVoucherCustomerSerializer,
            201: UserVoucherCustomerSerializer,
        },
    ),
)

CUSTOMER_VOUCHER_CLAIM_CODE_SCHEMA = extend_schema_view(
    post=extend_schema(
        summary='Nhận voucher bằng mã',
        description='Nhận voucher PUBLIC hoặc CODE_ONLY. Voucher ASSIGNED chỉ có thể do admin/hệ thống cấp.',
        tags=['4. Customer Vouchers'],
        request=VoucherClaimCodeSerializer,
        responses={
            200: UserVoucherCustomerSerializer,
            201: UserVoucherCustomerSerializer,
        },
    ),
)

CUSTOMER_VOUCHER_LIST_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Xem ví voucher của khách hàng',
        description='''
        Mặc định chỉ trả voucher đang hiển thị. Trạng thái hiển thị được suy ra từ UserVoucher,
        thời gian/hoạt động của Voucher và số lượt RESERVED/USED trong BookingVoucher.
        ''',
        tags=['4. Customer Vouchers'],
        parameters=[
            OpenApiParameter(
                name='status',
                type=str,
                required=False,
                enum=['AVAILABLE', 'UPCOMING', 'EXPIRED', 'EXHAUSTED', 'DISABLED', 'REVOKED'],
            ),
        ],
        responses={200: UserVoucherCustomerSerializer(many=True)},
    ),
)

CUSTOMER_VOUCHER_DETAIL_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Xem voucher trong ví',
        description='Khách hàng chỉ được truy cập voucher thuộc ví của chính mình.',
        tags=['4. Customer Vouchers'],
        responses={200: UserVoucherCustomerSerializer},
    ),
    patch=extend_schema(
        summary='Ẩn hoặc hiển thị voucher trong ví',
        description='Chỉ field is_visible được phép cập nhật. Voucher đã bị admin thu hồi không thể hiển thị lại.',
        tags=['4. Customer Vouchers'],
        request=UserVoucherCustomerSerializer,
        responses={200: UserVoucherCustomerSerializer},
    ),
    delete=extend_schema(
        summary='Ẩn voucher khỏi ví',
        description='Xóa mềm bằng is_visible=false; quyền sở hữu và lịch sử vẫn được giữ nguyên.',
        tags=['4. Customer Vouchers'],
        responses={200: OpenApiResponse(description='Đã ẩn voucher khỏi ví.')},
    ),
)

ADMIN_USER_VOUCHER_LIST_CREATE_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Danh sách voucher đã cấp cho người dùng',
        tags=['5. User Vouchers - Admin'],
        parameters=[
            OpenApiParameter(name='user_id', type=int, required=False),
            OpenApiParameter(name='voucher_id', type=int, required=False),
            OpenApiParameter(
                name='status',
                type=str,
                required=False,
                enum=['AVAILABLE', 'REVOKED'],
            ),
            OpenApiParameter(
                name='source',
                type=str,
                required=False,
                enum=['CUSTOMER_CLAIM', 'ADMIN', 'CAMPAIGN'],
            ),
        ],
        responses={200: UserVoucherAdminSerializer(many=True)},
    ),
    post=extend_schema(
        summary='Cấp voucher cho khách hàng',
        description='''
        Admin có thể cấp mọi loại voucher đang hoạt động và chưa hết hạn, kể cả voucher sắp bắt đầu.
        Nếu quan hệ đã tồn tại thì không tạo trùng; voucher đã thu hồi sẽ được khôi phục.
        ''',
        tags=['5. User Vouchers - Admin'],
        request=UserVoucherAdminSerializer,
        responses={
            200: UserVoucherAdminSerializer,
            201: UserVoucherAdminSerializer,
        },
    ),
)

ADMIN_USER_VOUCHER_DETAIL_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary='Xem chi tiết voucher đã cấp',
        tags=['5. User Vouchers - Admin'],
        responses={200: UserVoucherAdminSerializer},
    ),
    patch=extend_schema(
        summary='Cập nhật voucher đã cấp',
        description='''
        Cho phép sửa admin_note và chuyển trạng thái AVAILABLE/REVOKED. Không được thay đổi
        user_id hoặc voucher_id sau khi cấp để bảo toàn lịch sử.
        ''',
        tags=['5. User Vouchers - Admin'],
        request=UserVoucherAdminSerializer,
        responses={200: UserVoucherAdminSerializer},
    ),
    delete=extend_schema(
        summary='Thu hồi voucher của người dùng',
        description='Xóa mềm bằng trạng thái REVOKED, đặt revoked_at và ẩn khỏi ví khách hàng.',
        tags=['5. User Vouchers - Admin'],
        responses={200: OpenApiResponse(description='Thu hồi voucher thành công.')},
    ),
)
