from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
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
    WorkerRegisterResponseSerializer,
    WorkerRegisterSerializer,
    WorkerProfileUpdateSerializer,
    AdminWorkerStatusUpdateSerializer,
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
        trong đó field avatar là file ảnh JPG, PNG hoặc WEBP. Backend upload file lên Cloudinary
        dưới folder CLOUDINARY_CUSTOMER_AVATAR_FOLDER/user_<id>/ và lưu secure_url của ảnh vào database.
        """,
        tags=["1. Authentication & Users"],
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "email": {"type": "string", "format": "email"},
                    "phone_number": {"type": "string"},
                    "gender": {
                        "type": "string",
                        "enum": ["MALE", "FEMALE", "OTHER"],
                    },
                    "birth_date": {"type": "string", "format": "date"},
                    "avatar": {"type": "string", "format": "binary"},
                },
            }
        },
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

WORKER_REGISTER_SCHEMA = extend_schema_view(
    post=extend_schema(
        summary="Đăng ký tài khoản nhân viên",
        description="""
        Tạo tài khoản dành riêng cho ứng dụng nhân viên và cấp JWT Token.
        Backend luôn gán role là WORKER và tạo WorkerProfile với trạng thái DRAFT;
        frontend không cần và không thể lựa chọn role hoặc trạng thái hồ sơ.
        """,
        tags=["1. Authentication & Users"],
        request=WorkerRegisterSerializer,
        responses={201: WorkerRegisterResponseSerializer}
    )
)

WORKER_PROFILE_SCHEMA = extend_schema_view(
    patch=extend_schema(
        summary="Cập nhật hồ sơ nhân viên",
        description="""
        Cập nhật từng phần hồ sơ của nhân viên đang đăng nhập. Vì đây là PATCH,
        frontend chỉ cần gửi các field muốn thay đổi; những field không gửi sẽ được giữ nguyên.

        **Nhóm thông tin cá nhân**

        - `full_name`: Họ tên đầy đủ theo giấy tờ tùy thân.
        - `phone_number`: Số điện thoại duy nhất trong hệ thống.
        - `gender`: `MALE`, `FEMALE` hoặc `OTHER`.
        - `birth_date`: Ngày sinh dạng `YYYY-MM-DD`; nhân viên phải đủ 18 tuổi.
        - `portrait`: Ảnh chân dung JPG, PNG hoặc WEBP, tối đa 5 MB.

        **Nhóm CCCD/CMND**

        - `identity_number`: Gồm 9 hoặc 12 chữ số và không được trùng.
        - `identity_issued_date`: Ngày cấp dạng `YYYY-MM-DD`, không được ở tương lai.
        - `identity_issued_place`: Cơ quan hoặc nơi cấp.
        - `identity_front`, `identity_back`: Ảnh hai mặt CCCD/CMND.

        Khi cập nhật ảnh CCCD/CMND, bắt buộc gửi `identity_front` và `identity_back`
        đồng thời trong cùng một request. Gửi thiếu một mặt sẽ nhận lỗi HTTP 400.

        **Nhóm địa chỉ hiện tại**

        - `province`: Tỉnh/thành phố.
        - `ward`: Phường/xã.
        - `address_line`: Số nhà, tên đường và địa chỉ chi tiết.
        - `latitude`, `longitude`: Tọa độ vị trí, không bắt buộc.

        **Nhóm chứng chỉ hành nghề**

        - `certificate_file`: JPG, PNG, WEBP hoặc PDF, tối đa 10 MB.
        - `certificate_number`: Số giấy phép hoặc số chứng chỉ.
        - `certificate_expiry_date`: Ngày hết hạn dạng `YYYY-MM-DD`; chứng chỉ phải còn hạn.

        **Nhóm tài khoản ngân hàng**

        - `bank_code`: Mã ngân hàng, ví dụ `VCB`, `TCB`, `MB`.
        - `bank_account_number`: Gồm 6–20 chữ số; backend mã hóa trước khi lưu.
        - `bank_account_holder`: Tên chủ tài khoản, nên viết in hoa.

        Response không trả số tài khoản đầy đủ mà chỉ trả dạng che, ví dụ `******6789`.

        **Điều khoản và trạng thái hồ sơ**

        - `terms_accepted`: Phải là `true` để hồ sơ được xem là hoàn chỉnh.
        - `DRAFT`: Được cập nhật toàn bộ. Nếu còn thiếu dữ liệu thì tiếp tục giữ `DRAFT`.
        - `REJECTED`: Được sửa toàn bộ; khi đủ dữ liệu sẽ chuyển lại `PENDING`.
        - `PENDING`: Vẫn được cập nhật toàn bộ và giữ trạng thái `PENDING`.
        - `ACTIVE`: Chỉ được cập nhật địa chỉ và tọa độ. Thông tin định danh,
          CCCD, chứng chỉ, ngân hàng và số điện thoại bị khóa.
        - `SUSPENDED`: Không được cập nhật.

        Khi tất cả field bắt buộc và tài liệu đã đầy đủ, backend tự động chuyển hồ sơ
        sang `PENDING`, ghi nhận `submitted_at` và chờ admin xét duyệt.

        **Lưu ý request**

        - Dùng `application/json` nếu chỉ cập nhật dữ liệu text.
        - Dùng `multipart/form-data` nếu request có `portrait`, ảnh CCCD hoặc chứng chỉ.
        - Client không được gửi hoặc tự thay đổi `status`, `role`, `approved_by`, `approved_at`.
        """,
        tags=["1. Authentication & Users"],
        request=WorkerProfileUpdateSerializer,
        responses={200: WorkerProfileUpdateSerializer},
    )
)

ADMIN_WORKER_PROFILE_LIST_SCHEMA = extend_schema_view(
    get=extend_schema(
        summary="Danh sách hồ sơ nhân viên chờ duyệt",
        description="""
        Mặc định trả về các hồ sơ nhân viên có trạng thái PENDING để admin xét duyệt.
        Có thể truyền query parameter `status` để xem hồ sơ ở trạng thái khác.
        Response bao gồm thông tin cá nhân, địa chỉ, URL tài liệu xác minh,
        trạng thái completeness và thông tin xét duyệt. Số tài khoản ngân hàng luôn được che.
        """,
        tags=["1. Authentication & Users - Admin"],
        parameters=[
            OpenApiParameter(
                name="status",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["DRAFT", "PENDING", "ACTIVE", "REJECTED", "SUSPENDED"],
                description="Trạng thái cần lọc; mặc định là PENDING.",
            )
        ],
        responses={200: WorkerProfileUpdateSerializer(many=True)},
    )
)

ADMIN_WORKER_STATUS_UPDATE_SCHEMA = extend_schema_view(
    patch=extend_schema(
        summary="Cập nhật trạng thái hồ sơ nhân viên",
        description="""
        Cho phép admin chuyển trạng thái hồ sơ nhân viên.

        - `ACTIVE`: duyệt hồ sơ; chỉ thực hiện khi hồ sơ đầy đủ, đồng thời ghi `approved_by` và `approved_at`.
        - `REJECTED`: từ chối hồ sơ; bắt buộc truyền `reason`.
        - `SUSPENDED`: tạm khóa nghiệp vụ nhân viên; có thể truyền `reason`.
        - `PENDING`: đưa hồ sơ đầy đủ về hàng chờ duyệt và làm mới `submitted_at`.
        - `DRAFT`: đưa hồ sơ về trạng thái bổ sung thông tin.

        API chỉ cập nhật `WorkerProfile.status`; vai trò `User.role=WORKER` không bị thay đổi.
        """,
        tags=["1. Authentication & Users - Admin"],
        request=AdminWorkerStatusUpdateSerializer,
        responses={200: WorkerProfileUpdateSerializer},
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

