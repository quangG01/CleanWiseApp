from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from .serializers import TokenResponseSerializer, UserSerializer

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
        description="Xác thực Username/Password và cấp JWT Token.",
        tags=["1. Authentication & Users"],
        responses={200: TokenResponseSerializer}
    )
)