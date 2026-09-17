"""OpenAPI decorators kept separate from the authentication behavior."""

from rest_framework import serializers
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view, inline_serializer

from .serializers import (
    CustomerRegisterSerializer,
    TokenResponseSerializer,
    WorkerRegisterResponseSerializer,
    WorkerRegisterSerializer,
    WorkerProfileUpdateSerializer,
)


def _schema(view_class):
    return view_class


USER_LIST_SCHEMA = _schema
LOGIN_SCHEMA = _schema
CUSTOMER_REGISTER_SCHEMA = extend_schema_view(
    post=extend_schema(
        request=CustomerRegisterSerializer,
        responses={
            201: inline_serializer(
                name='CustomerRegisterSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': TokenResponseSerializer(),
                },
            ),
        },
        description='Đăng ký khách hàng. Role luôn được backend gán là CUSTOMER.',
    ),
)
GOOGLE_LOGIN_SCHEMA = _schema
FORGOT_PASSWORD_SCHEMA = _schema
VERIFY_PASSWORD_RESET_OTP_SCHEMA = _schema
RESET_PASSWORD_SCHEMA = _schema
CUSTOMER_PROFILE_SCHEMA = _schema
WORKER_REGISTER_SCHEMA = extend_schema_view(
    post=extend_schema(
        request=WorkerRegisterSerializer,
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
            '### Dữ liệu trả về\n'
            '- Thông tin tài khoản và thông tin nghề nghiệp.\n'
            '- Loại dịch vụ đã đăng ký.\n'
            '- Ảnh chân dung và giấy tờ xác minh.\n'
            '- Trạng thái xét duyệt hồ sơ.\n\n'
            '### Độ hoàn thiện hồ sơ\n'
            '- `is_complete`: hồ sơ đã đủ dữ liệu bắt buộc hay chưa.\n'
            '- `missing_fields`: danh sách field còn thiếu hoặc không còn hợp lệ.\n'
            '- `completion_percent`: phần trăm hoàn thiện hồ sơ.\n\n'
            '> API này không cho phép xem hồ sơ của nhân viên khác.'
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
            400: OpenApiResponse(description='Dữ liệu không hợp lệ, dịch vụ không hoạt động hoặc giấy tờ không đúng quy tắc.'),
            401: OpenApiResponse(description='Chưa đăng nhập hoặc access token không hợp lệ.'),
            403: OpenApiResponse(description='Tài khoản không có role WORKER.'),
        },
        description=(
            '### Cách sử dụng\n'
            '- Chỉ gửi những field cần thay đổi.\n'
            '- Dữ liệu thông thường có thể gửi bằng `application/json`.\n'
            '- Khi tải file, sử dụng `multipart/form-data`.\n\n'
            '### Thông tin tài khoản\n'
            'Các field sau được lưu trên tài khoản người dùng:\n'
            '- `first_name`: tên nhân viên.\n'
            '- `last_name`: họ và tên đệm.\n'
            '- `phone_number`: số điện thoại duy nhất.\n'
            '- `gender`: `MALE`, `FEMALE` hoặc `OTHER`.\n'
            '- `birth_date`: ngày sinh; nhân viên phải đủ 18 tuổi.\n\n'
            '### Thông tin nghề nghiệp\n'
            '- `bio`: giới thiệu hoặc mô tả kinh nghiệm.\n'
            '- `experience_years`: số năm kinh nghiệm, không được âm.\n'
            '- `identity_number`: CCCD/CMND gồm 9 hoặc 12 chữ số.\n'
            '- `service_id`: ID của một dịch vụ đang hoạt động.\n'
            '- Gửi `service_id dùng null` để bỏ loại dịch vụ đã chọn.\n\n'
            '### Ảnh và giấy tờ\n'
            '- `portrait`: ảnh chân dung JPG, JPEG, PNG hoặc WEBP.\n'
            '- `identity_front`: ảnh mặt trước CCCD/CMND.\n'
            '- `identity_back`: ảnh mặt sau CCCD/CMND.\n'
            '- `certificate_file`: chứng chỉ tùy chọn, dạng ảnh hoặc PDF.\n'
            '- `identity_front` và `identity_back` phải được gửi cùng nhau khi cập nhật.\n\n'
            '### Field chỉ đọc\n'
            'Không được gửi các field sau; backend sẽ trả lỗi `400`:\n'
            '- `role`, `status`\n'
            '- `approved_by`, `approved_at`, `rejection_reason`\n'
            '- `average_rating`, `total_completed_jobs`\n\n'
            '### Lưu ý về xét duyệt\n'
            '> Cập nhật hồ sơ không tự gửi cho admin và không tự thay đổi trạng thái xét duyệt.'
        ),
        examples=[
            OpenApiExample(
                'Cập nhật thông tin và loại dịch vụ',
                value={
                    'first_name': 'An',
                    'last_name': 'Nguyễn',
                    'phone_number': '0912345678',
                    'gender': 'MALE',
                    'birth_date': '1995-01-01',
                    'bio': 'Có kinh nghiệm vệ sinh nhà ở.',
                    'experience_years': 2,
                    'identity_number': '012345678901',
                    'service_id': 1,
                },
                request_only=True,
            ),
            OpenApiExample(
                'Bỏ loại dịch vụ đã chọn',
                value={'service_id': None},
                request_only=True,
            ),
        ],
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
            '3. Kiểm tra nhân viên có ít nhất một khu vực làm việc đang hoạt động.\n'
            '4. Nếu hợp lệ, chuyển trạng thái:\n\n'
            '```text\n'
            'DRAFT → PENDING\n'
            '```\n\n'
            '### Dữ liệu bắt buộc\n'
            '- Họ tên, số điện thoại, giới tính và ngày sinh.\n'
            '- Số CCCD/CMND và ảnh chân dung.\n'
            '- Ảnh CCCD/CMND mặt trước và mặt sau.\n'
            '- Một loại dịch vụ đang hoạt động.\n'
            '- Ít nhất một khu vực làm việc đang hoạt động.\n\n'
            '### Khi hồ sơ chưa đầy đủ\n'
            '- Backend giữ nguyên trạng thái `DRAFT`.\n'
            '- Response lỗi trả `missing_fields` và `completion_percent`.\n\n'
            '### Giới hạn trạng thái\n'
            '> Chỉ hồ sơ `DRAFT` được gửi. Hồ sơ đã `PENDING`, `ACTIVE`, `REJECTED` '
            'hoặc `SUSPENDED` sẽ bị từ chối.'
        ),
        responses={
            200: inline_serializer(
                name='WorkerProfileSubmitSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'data': WorkerProfileUpdateSerializer(),
                },
            ),
            400: OpenApiResponse(
                description=(
                    'Hồ sơ còn thiếu dữ liệu, dịch vụ/khu vực không còn hoạt động '
                    'hoặc trạng thái hiện tại không phải DRAFT.'
                ),
            ),
            401: OpenApiResponse(description='Chưa đăng nhập hoặc access token không hợp lệ.'),
            403: OpenApiResponse(description='Tài khoản không có role WORKER.'),
        },
    ),
)

ADMIN_WORKER_PROFILE_LIST_SCHEMA = _schema
ADMIN_WORKER_STATUS_UPDATE_SCHEMA = _schema
