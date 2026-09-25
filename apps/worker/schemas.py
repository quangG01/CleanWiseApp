from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers

from .constants import MIN_CANCEL_HOURS
from .serializers import (
    CancelAssignmentSerializer,
    CustomerWorkerProfileSerializer,
    FavoriteWorkerSerializer,
    WorkerMyScheduleSerializer,
    WorkerScheduleSerializer,
)

_RESULT = inline_serializer(name='WorkerAssignmentResult', fields={
    'message': serializers.CharField(),
    'data': inline_serializer(name='WorkerAssignmentResultData', fields={
        'assignment_id': serializers.IntegerField(),
        'schedule_id': serializers.IntegerField(),
        'status': serializers.CharField(),
    }),
})


CUSTOMER_WORKER_PROFILE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='customer_worker_profile_retrieve',
        summary='Hồ sơ công khai của nhân viên',
        description='Chỉ xem được nhân viên đang hoạt động đã được phân công cho đơn của khách hàng.',
        responses={200: CustomerWorkerProfileSerializer},
        tags=['Customer - Favorite Workers'],
    ),
)

CUSTOMER_FAVORITE_WORKER_LIST_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='customer_favorite_worker_list',
        summary='Danh sách nhân viên yêu thích',
        responses={200: FavoriteWorkerSerializer(many=True)},
        tags=['Customer - Favorite Workers'],
    ),
)

CUSTOMER_FAVORITE_WORKER_DETAIL_SCHEMA = extend_schema_view(
    put=extend_schema(
        operation_id='customer_favorite_worker_add',
        summary='Thêm nhân viên vào danh sách yêu thích',
        description='Thao tác idempotent; gọi lại không tạo bản ghi trùng.',
        request=None,
        responses={200: FavoriteWorkerSerializer, 201: FavoriteWorkerSerializer},
        tags=['Customer - Favorite Workers'],
    ),
    delete=extend_schema(
        operation_id='customer_favorite_worker_remove',
        summary='Bỏ yêu thích nhân viên',
        description='Xóa cứng quan hệ yêu thích. Thao tác idempotent.',
        request=None,
        responses={
            204: OpenApiResponse(
                description='Đã bỏ yêu thích hoặc bản ghi không còn tồn tại.',
            ),
        },
        tags=['Customer - Favorite Workers'],
    ),
)

# --- NHÓM WORKER - AREAS & WORKING AREAS ---

WORKER_ACTIVE_AREA_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='worker_active_area_list',
        summary='Danh sách khu vực hoạt động khả dụng',
        description='Cho nhân viên xem danh sách các khu vực/thành phố đang hoạt động trong hệ thống, hỗ trợ lọc theo thành phố (city) hoặc tìm kiếm theo tên.',
        tags=['Worker - Areas']
    )
)

WORKER_WORKING_AREA_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='worker_working_area_list',
        summary='Danh sách khu vực làm việc của tôi',
        description='Lấy danh sách các khu vực mà nhân viên đang đăng ký nhận việc.',
        tags=['Worker - Working Areas']
    ),
    put=extend_schema(
        operation_id='worker_working_area_bulk_update',
        summary='Cập nhật danh sách khu vực làm việc',
        description=(
            'Thay thế toàn bộ danh sách khu vực làm việc của nhân viên bằng danh sách area_ids gửi lên. '
            'Phải chọn ít nhất 1 khu vực.'
        ),
        tags=['Worker - Working Areas']
    ),
)


# --- NHÓM WORKER - SCHEDULES & ASSIGNMENTS ---

WORKER_AVAILABLE_SCHEDULE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='worker_available_schedule_list',
        summary='Danh sách buổi làm việc khả dụng',
        description=(
            'Buổi còn trống thuộc dịch vụ nhân viên đã đăng ký, nằm trong khu vực làm việc, chưa bắt đầu '
            'và không trùng giờ với việc đã nhận. Hồ sơ phải ACTIVE. Các buổi cùng booking_id thuộc cùng 1 đơn '
            '(gói tháng), total_sessions là tổng số buổi chưa hủy của đơn.'
        ),
        parameters=[
            OpenApiParameter('booking_id', int, description='Chỉ lấy các buổi của 1 đơn'),
            OpenApiParameter('date_from', str, description='YYYY-MM-DD'),
            OpenApiParameter('date_to', str, description='YYYY-MM-DD'),
        ],
        responses={200: WorkerScheduleSerializer(many=True)},
        tags=['Worker - Schedules'],
    )
)

WORKER_MY_SCHEDULE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='worker_my_schedule_list',
        summary='Danh sách buổi làm việc của tôi',
        description='Các buổi đã nhận (kèm địa chỉ chi tiết, SĐT khách, can_cancel, cancel_deadline).',
        parameters=[OpenApiParameter(
            'status', str,
            enum=['PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'MISSED'],
        )],
        responses={200: WorkerMyScheduleSerializer(many=True)},
        tags=['Worker - Schedules'],
    )
)

WORKER_CLAIM_SCHEDULE_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='worker_claim_schedule',
        summary='Nhận việc (Claim schedule)',
        description=(
            'Điều kiện: hồ sơ ACTIVE, đúng dịch vụ, trong khu vực làm việc, buổi chưa bắt đầu, '
            'chưa có người nhận, không trùng giờ.'
        ),
        request=None,
        responses={201: _RESULT},
        tags=['Worker - Assignments'],
    )
)

WORKER_CANCEL_ASSIGNMENT_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='worker_cancel_assignment',
        summary='Hủy nhận việc',
        description=(
            f'Hủy tự do khi còn từ {MIN_CANCEL_HOURS} tiếng trở lên trước giờ bắt đầu; '
            f'dưới {MIN_CANCEL_HOURS} tiếng sẽ bị chặn và phải liên hệ admin. '
            'Buổi đã hủy quay lại danh sách khả dụng để nhân viên khác nhận.'
        ),
        request=CancelAssignmentSerializer,
        responses={200: _RESULT},
        tags=['Worker - Assignments'],
    )
)


# --- NHÓM ADMIN - ASSIGNMENT ---

ADMIN_ASSIGN_WORKER_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='admin_assign_worker',
        summary='Quản trị viên gán nhân viên vào lịch làm',
        description='Cho phép Admin/Quản trị viên chủ động chỉ định và phân công một nhân viên cụ thể vào một buổi làm việc (schedule) trong hệ thống.',
        tags=['Booking - Admin']  # Hoặc đưa vào tag Admin chung tùy ý bạn
    )
)
