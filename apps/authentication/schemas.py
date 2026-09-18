from rest_framework import serializers
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from .serializers import (
    CustomerRegisterSerializer,
    LoginSerializer,
    GoogleLoginSerializer,
    CustomerProfileSerializer,
    TokenResponseSerializer,
    WorkerRegisterResponseSerializer,
    WorkerRegisterSerializer,
    WorkerProfileUpdateSerializer,
    AdminWorkerStatusUpdateSerializer,
    ForgotPasswordSerializer,
    VerifyPasswordResetOTPSerializer,
    ResetPasswordSerializer,
    UserSerializer,
)

# --- USER LIST SCHEMA ---
USER_LIST_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='user_list',
        summary='Danh sách người dùng (Admin)',
        description='Quản trị viên xem danh sách toàn bộ tài khoản trong hệ thống.',
        tags=['Users - Admin'],
        responses={200: UserSerializer(many=True)}
    )
)

# --- AUTH SCHEMAS ---
LOGIN_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='auth_login',
        summary='Đăng nhập tài khoản',
        description='Đăng nhập bằng số điện thoại/username và mật khẩu để lấy token.',
        request=LoginSerializer,
        tags=['Auth'],
        responses={200: TokenResponseSerializer()}
    )
)

GOOGLE_LOGIN_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='auth_google_login',
        summary='Đăng nhập/Đăng ký bằng Google',
        description='Xác thực bằng Google ID Token.',
        request=GoogleLoginSerializer,
        tags=['Auth'],
        responses={200: TokenResponseSerializer()}
    )
)

CUSTOMER_REGISTER_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='customer_register',
        summary='Đăng ký tài khoản khách hàng',
        description='Đăng ký khách hàng. Role luôn được backend gán là CUSTOMER.',
        request=CustomerRegisterSerializer,
        tags=['Auth'],
        responses={
            201: inline_serializer(
                name='CustomerRegisterSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': TokenResponseSerializer(),
                },
            ),
        },
    ),
)

CUSTOMER_PROFILE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='customer_profile_retrieve',
        summary='Lấy thông tin khách hàng',
        tags=['Customer - Profile'],
        responses={200: CustomerProfileSerializer}
    ),
    patch=extend_schema(
        operation_id='customer_profile_update',
        summary='Cập nhật thông tin khách hàng',
        request=CustomerProfileSerializer,
        tags=['Customer - Profile'],
        responses={200: CustomerProfileSerializer}
    )
)

# --- PASSWORD RESET SCHEMAS ---
FORGOT_PASSWORD_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='auth_forgot_password',
        summary='Quên mật khẩu',
        request=ForgotPasswordSerializer,
        tags=['Auth - Password Reset']
    )
)

VERIFY_PASSWORD_RESET_OTP_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='auth_verify_reset_otp',
        summary='Xác thực mã OTP quên mật khẩu',
        request=VerifyPasswordResetOTPSerializer,
        tags=['Auth - Password Reset']
    )
)

RESET_PASSWORD_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='auth_reset_password',
        summary='Đặt lại mật khẩu mới',
        request=ResetPasswordSerializer,
        tags=['Auth - Password Reset']
    )
)

# --- WORKER REGISTER & PROFILE SCHEMAS ---
WORKER_REGISTER_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='worker_register',
        summary='Đăng ký tài khoản nhân viên vệ sinh',
        request=WorkerRegisterSerializer,
        tags=['Worker - Auth'],
        responses={
            201: inline_serializer(
                name='WorkerRegisterSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': WorkerRegisterResponseSerializer(),
                },
            ),
        },
        description=(
            '### Kết quả đăng ký\n'
            '- Backend luôn gán role là `WORKER`.\n'
            '- Hồ sơ nhân viên được tạo ở trạng thái `DRAFT`.\n'
            '- Nhân viên tiếp tục cập nhật hồ sơ trước khi gửi admin duyệt.'
        ),
    ),
)

WORKER_PROFILE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='worker_profile_retrieve',
        summary='Lấy hồ sơ của nhân viên đang đăng nhập',
        description=(
            '### Mục đích\n'
            'Lấy hồ sơ gắn với access token của nhân viên đang đăng nhập.\n\n'
            '### Độ hoàn thiện hồ sơ\n'
            '- `is_complete`: hồ sơ đã đủ dữ liệu bắt buộc hay chưa.\n'
            '- `missing_fields`: danh sách field còn thiếu hoặc không còn hợp lệ.\n'
            '- `completion_percent`: phần trăm hoàn thiện hồ sơ.'
        ),
        tags=['Worker - Profile'],
        responses={
            200: inline_serializer(
                name='WorkerProfileRetrieveSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': WorkerProfileUpdateSerializer(),
                },
            ),
            401: OpenApiResponse(description='Chưa đăng nhập hoặc access token không hợp lệ.'),
            403: OpenApiResponse(description='Tài khoản không có role WORKER.'),
        },
    ),
    patch=extend_schema(
        operation_id='worker_profile_partial_update',
        summary='Cập nhật từng phần hồ sơ nhân viên',
        request=WorkerProfileUpdateSerializer,
        tags=['Worker - Profile'],
        responses={
            200: inline_serializer(
                name='WorkerProfileUpdateSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': WorkerProfileUpdateSerializer(),
                },
            ),
            400: OpenApiResponse(description='Dữ liệu không hợp lệ hoặc giấy tờ không đúng quy tắc.'),
            401: OpenApiResponse(description='Chưa đăng nhập hoặc access token không hợp lệ.'),
            403: OpenApiResponse(description='Tài khoản không có role WORKER.'),
        },
        description='Cập nhật thông tin cá nhân, số năm kinh nghiệm, CCCD, và loại dịch vụ.',
    ),
)

WORKER_PROFILE_SUBMIT_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='worker_profile_submit',
        summary='Gửi hồ sơ nhân viên để admin duyệt',
        request=None,
        tags=['Worker - Profile'],
        description=(
            '### Khi nhân viên gọi API này, backend sẽ\n'
            '1. Kiểm tra hồ sơ đã đầy đủ các thông tin bắt buộc.\n'
            '2. Kiểm tra loại dịch vụ đăng ký vẫn đang hoạt động.\n'
            '3. Chuyển trạng thái từ `DRAFT` sang `PENDING`.'
        ),
        responses={
            200: inline_serializer(
                name='WorkerProfileSubmitSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': WorkerProfileUpdateSerializer(),
                },
            ),
            400: OpenApiResponse(description='Hồ sơ còn thiếu dữ liệu hoặc không ở trạng thái DRAFT.'),
            401: OpenApiResponse(description='Chưa đăng nhập.'),
            403: OpenApiResponse(description='Không có quyền WORKER.'),
        },
    ),
)

# --- ADMIN WORKER SCHEMAS ---
ADMIN_WORKER_PROFILE_LIST_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='admin_worker_profile_list',
        summary='Danh sách hồ sơ nhân viên chờ duyệt (Admin)',
        tags=['Worker - Admin']
    )
)

ADMIN_WORKER_STATUS_UPDATE_SCHEMA = extend_schema_view(
    patch=extend_schema(
        operation_id='admin_worker_status_update',
        summary='Phê duyệt hoặc thay đổi trạng thái hồ sơ nhân viên (Admin)',
        request=AdminWorkerStatusUpdateSerializer,
        tags=['Worker - Admin']
    )
)