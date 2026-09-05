from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from .serializers import GoogleLoginSerializer, RegisterSerializer, TokenResponseSerializer, UserSerializer

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


