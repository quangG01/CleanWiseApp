from rest_framework import serializers
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from .serializers import (
    CustomerProfileSerializer,
    ForgotPasswordSerializer,
    GoogleLoginSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    TokenResponseSerializer,
    UserSerializer,
)

# Khai báo sẵn các schema
USER_LIST_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary="Lấy danh sách người dùng",
        description="Trả về danh sách tất cả người dùng trong hệ thống (Hỗ trợ lọc theo Role).",
        tags=["1. Authentication & Users"],
        parameters=[
            OpenApiParameter(
                name="role",
                type=str,
                description="Lọc theo vai trò: ADMIN, CUSTOMER, WORKER",
                required=False
            )
        ]
    )
)

CUSTOMER_PROFILE_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary="Lấy hồ sơ khách hàng",
        description="Trả về thông tin hồ sơ của khách hàng đang đăng nhập.",
        tags=["1. Authentication & Users"],
        responses={200: CustomerProfileSerializer}
    ),
    patch=extend_schema(
        summary="Cập nhật hồ sơ khách hàng",
        description="""
        Cập nhật thông tin hồ sơ của khách hàng đang đăng nhập.
        Các trường được phép cập nhật: first_name, last_name, email, phone_number,
        gender, birth_date, avatar.

        Nếu cập nhật avatar, frontend gửi request dạng multipart/form-data,
        trong đó field avatar là file ảnh JPG, PNG hoặc WEBP. Backend lưu file vào local storage
        dưới thư mục media/customer_avatars/user_<id>/ và lưu URL của ảnh vào database.
        """,
        tags=["1. Authentication & Users"],
        request=inline_serializer(
            name="CustomerProfileUpdateRequest",
            fields={
                "first_name": serializers.CharField(required=False),
                "last_name": serializers.CharField(required=False),
                "email": serializers.EmailField(required=False),
                "phone_number": serializers.CharField(required=False, allow_blank=True),
                "gender": serializers.ChoiceField(
                    choices=["MALE", "FEMALE", "OTHER"],
                    required=False
                ),
                "birth_date": serializers.DateField(required=False),
                "avatar": serializers.FileField(required=False),
            }
        ),
        responses={200: CustomerProfileSerializer}
    )
)

LOGIN_SCHEMA = extend_schema_view(
    post=extend_schema(
        summary="Đăng nhập hệ thống",
        description="Xác thực bằng số điện thoại hoặc username kèm mật khẩu và cấp JWT Token.",
        tags=["1. Authentication & Users"],
        responses={200: TokenResponseSerializer}
    )
)

REGISTER_SCHEMA = extend_schema_view(
    post=extend_schema(
        summary="Đăng ký tài khoản",
        description=""" Tạo tài khoản khách hàng hoặc nhân viên và cấp JWT Token sau khi đăng ký thành công, lưu ý:
        + Không cần truyền role, mặc định là CUSTOMER. 
        + Không thể đăng ký trực tiếp ADMIN. 
        """,
        tags=["1. Authentication & Users"],
        request=RegisterSerializer,
        responses={201: TokenResponseSerializer}
    )
)

GOOGLE_LOGIN_SCHEMA = extend_schema_view(
    post=extend_schema(
        summary="Đăng nhập / đăng ký bằng Google",
        description="""
        Nhận Google ID token từ frontend.
        Nếu email chưa tồn tại, hệ thống tự tạo tài khoản CUSTOMER và CustomerProfile.
        Nếu email đã tồn tại, hệ thống đăng nhập vào tài khoản đó.
        """,
        tags=["1. Authentication & Users"],
        request=GoogleLoginSerializer,
        responses={200: TokenResponseSerializer}
    )
)


FORGOT_PASSWORD_SCHEMA = extend_schema_view(
    post=extend_schema(
        summary="Gửi email khôi phục mật khẩu",
        description="""
        Nhận email người dùng và gửi liên kết đặt lại mật khẩu nếu email tồn tại.

        Backend sẽ tạo uid và token khôi phục mật khẩu, sau đó gắn vào link gửi qua email:
        FRONTEND_RESET_PASSWORD_URL?uid=...&token=...

        Frontend mở màn hình đặt lại mật khẩu từ link trong email, lấy uid và token trên URL,
        rồi gọi API POST /api/auth/reset-password/ cùng mật khẩu mới để hoàn tất khôi phục.

        API luôn trả về thông báo chung để tránh lộ email đã đăng ký trong hệ thống.
        """,
        tags=["1. Authentication & Users"],
        request=ForgotPasswordSerializer,
        responses={200: OpenApiResponse(description="Đã xử lý yêu cầu khôi phục mật khẩu.")}
    )
)

RESET_PASSWORD_SCHEMA = extend_schema_view(
    post=extend_schema(
        summary="Đặt lại mật khẩu mới",
        description="""
        Nhận uid và token mà frontend lấy từ link khôi phục mật khẩu trong email,
        kèm mật khẩu mới và xác nhận mật khẩu mới.

        Nếu uid và token hợp lệ, backend sẽ cập nhật mật khẩu mới cho tài khoản.
        """,
        tags=["1. Authentication & Users"],
        request=ResetPasswordSerializer,
        responses={200: OpenApiResponse(description="Đặt lại mật khẩu thành công.")}
    )
)

