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
    VerifyPasswordResetOTPSerializer,
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
        summary="Gửi mã xác thực khôi phục mật khẩu",
        description="""
        Nhận email người dùng và gửi mã xác thực khôi phục mật khẩu nếu email tồn tại.

        Backend sẽ tạo mã OTP gồm 6 chữ số, lưu bản hash của mã kèm thời gian hết hạn,
        rồi gửi mã OTP đó về email cho người dùng.

        Frontend hiển thị màn hình nhập mã xác thực. Sau khi người dùng nhập mã,
        frontend gọi API POST /api/auth/verify-reset-otp/ với email và code.
        Nếu mã hợp lệ, frontend mới chuyển sang màn hình nhập mật khẩu mới.

        API luôn trả về thông báo chung để tránh lộ email đã đăng ký trong hệ thống.
        """,
        tags=["1. Authentication & Users"],
        request=ForgotPasswordSerializer,
        responses={200: OpenApiResponse(description="Đã xử lý yêu cầu khôi phục mật khẩu.")}
    )
)

VERIFY_PASSWORD_RESET_OTP_SCHEMA = extend_schema_view(
    post=extend_schema(
        summary="Xác minh mã OTP khôi phục mật khẩu",
        description="""
        Nhận email và mã OTP mà người dùng nhập từ email.

        Nếu mã OTP hợp lệ, chưa hết hạn, chưa được sử dụng và chưa vượt quá số lần nhập sai,
        backend sẽ đánh dấu mã này là đã xác minh. Sau bước này frontend có thể hiển thị
        form nhập mật khẩu mới.
        """,
        tags=["1. Authentication & Users"],
        request=VerifyPasswordResetOTPSerializer,
        responses={200: OpenApiResponse(description="Mã xác thực hợp lệ.")}
    )
)

RESET_PASSWORD_SCHEMA = extend_schema_view(
    post=extend_schema(
        summary="Đặt lại mật khẩu mới",
        description="""
        Nhận email, mã xác thực OTP mà người dùng nhập từ email,
        kèm mật khẩu mới và xác nhận mật khẩu mới.

        API này chỉ đổi mật khẩu nếu mã OTP đã được xác minh thành công qua
        POST /api/auth/verify-reset-otp/ trước đó. Backend vẫn kiểm tra lại email,
        mã OTP, hạn dùng và trạng thái sử dụng trước khi cập nhật mật khẩu.
        """,
        tags=["1. Authentication & Users"],
        request=ResetPasswordSerializer,
        responses={200: OpenApiResponse(description="Đặt lại mật khẩu thành công.")}
    )
)

