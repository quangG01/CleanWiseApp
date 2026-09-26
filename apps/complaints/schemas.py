# apps/complaints/schemas.py

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)


COMPLAINT_ISSUE_TYPE_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='customer_complaint_issue_type_list',
        summary='Danh sách loại sự cố',
        description=(
            'Lấy danh sách các loại sự cố đang hoạt động '
            'để khách hàng lựa chọn khi tạo khiếu nại.'
        ),
        tags=['Complaint - Customer'],
    ),
)


COMPLAINT_CUSTOMER_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='customer_complaint_list',
        summary='Danh sách khiếu nại của khách hàng',
        description=(
            'Khách hàng chỉ thấy khiếu nại của mình.'
        ),
        tags=['Complaint - Customer'],
    ),

    post=extend_schema(
        operation_id='customer_complaint_create',
        summary='Tạo khiếu nại mới',
        description=(
            'Khách hàng chọn loại sự cố, nhập mô tả chi tiết '
            'không bắt buộc và có thể đính kèm file.'
        ),
        tags=['Complaint - Customer'],
    ),
)


COMPLAINT_DETAIL_CUSTOMER_SCHEMA = extend_schema_view(
    get=extend_schema(
        operation_id='customer_complaint_detail',
        summary='Chi tiết khiếu nại',
        description=(
            'Xem chi tiết khiếu nại, loại sự cố, '
            'nội dung, trạng thái xử lý và file đính kèm.'
        ),
        tags=['Complaint - Customer'],
    ),
)


COMPLAINT_CANCEL_SCHEMA = extend_schema_view(
    post=extend_schema(
        operation_id='customer_complaint_cancel',
        summary='Hủy khiếu nại',
        description=(
            'Khách hàng có thể hủy khiếu nại '
            'khi trạng thái là PENDING.'
        ),
        tags=['Complaint - Customer'],
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