from drf_spectacular.utils import extend_schema, extend_schema_view

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
    post=extend_schema(
        operation_id='worker_working_area_create',
        summary='Đăng ký khu vực làm việc mới',
        description='Thêm một khu vực mới vào danh sách khu vực có thể nhận việc của nhân viên.',
        tags=['Worker - Working Areas']
    ),
)

WORKER_WORKING_AREA_DETAIL_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='worker_working_area_detail',
        summary='Chi tiết khu vực làm việc',
        description='Xem thông tin chi tiết một khu vực làm việc đã đăng ký theo ID.',
        tags=['Worker - Working Areas']
    ),
    patch=extend_schema(
        operation_id='worker_working_area_update',
        summary='Cập nhật khu vực làm việc',
        description='Chỉnh sửa thông tin khu vực làm việc của nhân viên.',
        tags=['Worker - Working Areas']
    ),
    delete=extend_schema(
        operation_id='worker_working_area_delete',
        summary='Xóa khu vực làm việc',
        description='Hủy đăng ký một khu vực làm việc khỏi danh sách của nhân viên.',
        tags=['Worker - Working Areas']
    ),
)


# --- NHÓM WORKER - SCHEDULES & ASSIGNMENTS ---

WORKER_AVAILABLE_SCHEDULE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='worker_available_schedule_list',
        summary='Danh sách buổi làm việc khả dụng',
        description='Lấy danh sách các lịch trình/buổi làm việc phù hợp với khu vực và thời gian mà nhân viên có thể nhận.',
        tags=['Worker - Schedules']
    )
)

WORKER_MY_SCHEDULE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='worker_my_schedule_list',
        summary='Danh sách buổi làm việc của tôi',
        description='Lấy danh sách các lịch trình mà nhân viên đã nhận hoặc được phân công, có hỗ trợ lọc theo trạng thái.',
        tags=['Worker - Schedules']
    )
)

WORKER_CLAIM_SCHEDULE_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='worker_claim_schedule',
        summary='Nhận việc (Claim schedule)',
        description='Nhân viên tự động nhận một buổi làm việc khả dụng trong hệ thống.',
        tags=['Worker - Assignments']
    )
)

WORKER_CANCEL_ASSIGNMENT_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='worker_cancel_assignment',
        summary='Hủy nhận việc',
        description='Nhân viên hủy một phân công/nhận việc đã thực hiện trước đó kèm theo lý do cụ thể.',
        tags=['Worker - Assignments']
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