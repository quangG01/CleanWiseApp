# apps/complaints/schemas.py

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)


COMPLAINT_ISSUE_TYPE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='complaint_issue_type_list',
        summary='Danh sách loại sự cố',
        description=(
            'Lấy danh sách các loại sự cố đang hoạt động, đúng vai trò '
            'người gọi (khách hàng hoặc nhân viên), để chọn khi tạo khiếu nại.'
        ),
        tags=['Complaint'],
    ),
)


COMPLAINT_LIST_CREATE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='complaint_list',
        summary='Danh sách khiếu nại của tôi',
        description=(
            'Khách hàng hoặc nhân viên chỉ thấy khiếu nại chính mình đã gửi.'
        ),
        tags=['Complaint'],
    ),

    post=extend_schema(
        operation_id='complaint_create',
        summary='Tạo khiếu nại mới',
        description=(
            'Khách hàng hoặc nhân viên chọn loại sự cố, nhập mô tả chi tiết '
            'không bắt buộc và có thể đính kèm file. Nhân viên bắt buộc gắn '
            'đúng buổi làm việc (schedule) mình đã nhận.'
        ),
        tags=['Complaint'],
    ),
)


COMPLAINT_DETAIL_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='complaint_detail',
        summary='Chi tiết khiếu nại',
        description=(
            'Xem chi tiết khiếu nại, loại sự cố, nội dung, trạng thái xử lý '
            'và file đính kèm. Chỉ người gửi khiếu nại hoặc admin xem được.'
        ),
        tags=['Complaint'],
    ),
)


COMPLAINT_CANCEL_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='complaint_cancel',
        summary='Hủy khiếu nại',
        description=(
            'Người đã gửi khiếu nại có thể hủy khi trạng thái còn PENDING.'
        ),
        tags=['Complaint'],
    ),
)


COMPLAINT_RESOLVE_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='admin_complaint_resolve',
        summary='Xử lý khiếu nại',
        description=(
            'Admin cập nhật trạng thái xử lý '
            'và ghi chú kết quả.'
        ),
        tags=['Complaint - Admin'],
    ),
)