"""OpenAPI schemas owned by the booking domain."""

from drf_spectacular.utils import extend_schema, extend_schema_view


BOOKING_CUSTOMER_SCHEMA = extend_schema_view(
    get=extend_schema(operation_id='customer_booking_list', summary='Danh sách đơn hàng của khách hàng', tags=['Booking - Customer']),
    post=extend_schema(operation_id='customer_booking_create', summary='Tạo booking mới', tags=['Booking - Customer']),
)


BOOKING_DETAIL_CUSTOMER_SCHEMA = extend_schema_view(
    get=extend_schema(operation_id='customer_booking_detail', summary='Chi tiết đơn hàng của khách hàng', tags=['Booking - Customer']),
)
