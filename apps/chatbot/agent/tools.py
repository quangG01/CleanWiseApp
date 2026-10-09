import json
import time

from django.core.serializers.json import DjangoJSONEncoder
from django.db import close_old_connections
from langchain.tools import ToolRuntime, tool

from .schemas import (AgentContext, BookingDetailsInput, BookingSchedulesInput,
                      ListBookingsInput, SearchServicesInput, ServiceDetailsInput, SelectResponseCardsInput, SearchHelpInput)
from ..services import queries
from ..services.knowledge import search_help


def result(callback, runtime):
    if time.monotonic() > runtime.context.deadline:
        raise TimeoutError('Chatbot run deadline exceeded')
    close_old_connections()
    try:
        data, cards = callback()
        return json.dumps(data, cls=DjangoJSONEncoder, ensure_ascii=False), {'cards': cards}
    except queries.ToolQueryError as exc:
        return json.dumps({'error': 'NOT_FOUND_OR_INVALID_INPUT', 'detail': str(exc)}, ensure_ascii=False), {'cards': []}
    finally:
        close_old_connections()


@tool(args_schema=SearchServicesInput, response_format='content_and_artifact')
def search_services(runtime: ToolRuntime[AgentContext], query: str = '', section_code: str = '', page: int = 1):
    """Tìm dịch vụ đang hoạt động. Dùng từ khóa ngắn (ví dụ dọn nhà, máy lạnh), hoặc query rỗng để xem danh mục."""
    def fetch():
        data = queries.search_services(query, section_code, page)
        return data, [{'type': 'service', 'id': item['id']} for item in data['results']]
    return result(fetch, runtime)


@tool(args_schema=ServiceDetailsInput, response_format='content_and_artifact')
def get_service_details(service_id: int, runtime: ToolRuntime[AgentContext]):
    """Xem mô tả, lựa chọn form và bảng giá một dịch vụ. Bảng giá chưa phải tổng tiền sau voucher/số buổi."""
    return result(lambda: (queries.get_service_details(service_id), [{'type': 'service', 'id': service_id}]), runtime)


@tool(args_schema=ListBookingsInput, response_format='content_and_artifact')
def list_my_bookings(runtime: ToolRuntime[AgentContext], status: str | None = None, date_from: str = '', date_to: str = '', page: int = 1,
                     payment_status: str | None = None, service_query: str = '', limit: int = 5):
    """Tra đơn phù hợp trạng thái, thanh toán, dịch vụ và ngày lịch dịch vụ. Mới nhất trước, limit=1 cho đơn gần nhất."""
    def fetch():
        data = queries.list_my_bookings(runtime.context.customer_id, status, date_from, date_to, page,
                                       payment_status, service_query, limit)
        return data, [{'type': 'booking', 'id': item['id']} for item in data['results']]
    return result(fetch, runtime)


@tool(args_schema=BookingDetailsInput, response_format='content_and_artifact')
def get_my_booking_detail(booking_reference: str, runtime: ToolRuntime[AgentContext]):
    """Xem đơn của khách: tiến độ, thanh toán, số buổi còn lại, lịch tiếp theo và check-in/phân công thực tế."""
    def fetch():
        data = queries.get_my_booking_detail(runtime.context.customer_id, booking_reference)
        return data, [{'type': 'booking', 'id': data['id']}]
    return result(fetch, runtime)


@tool(args_schema=BookingSchedulesInput, response_format='content_and_artifact')
def get_my_booking_schedules(booking_reference: str, runtime: ToolRuntime[AgentContext], page: int = 1):
    """Xem các buổi trong đơn của khách, 10 buổi/trang. Dùng khi đơn có nhiều buổi hoặc cần xem buổi cụ thể."""
    def fetch():
        data = queries.get_my_booking_schedules(runtime.context.customer_id, booking_reference, page)
        return data, [{'type': 'schedule', 'id': item['id']} for item in data['results']]
    return result(fetch, runtime)


@tool(args_schema=SelectResponseCardsInput, response_format='content_and_artifact')
def select_response_cards(references: list):
    """Chọn thẻ liên quan để gửi kèm câu trả lời sau khi tra cứu. Không gửi mọi đơn đã xem để tìm kiếm. Chọn [] khi không có kết quả phù hợp."""
    selected = [ref.model_dump() if hasattr(ref, 'model_dump') else ref for ref in references]
    return 'Đã ghi nhận lựa chọn thẻ. Hãy trả lời khách bằng lời.', {'selected_cards': selected}


@tool(args_schema=SearchHelpInput, response_format='content_and_artifact')
def search_help_articles(query: str, runtime: ToolRuntime[AgentContext]):
    """Tìm hướng dẫn/FAQ/chính sách đã xuất bản cho khách hàng. Trả đoạn nguồn và phiên bản; không dùng cho giá/số dư/trạng thái cá nhân hiện tại."""
    return result(lambda: search_help(query), runtime)


CUSTOMER_TOOLS = [search_services, get_service_details, list_my_bookings, search_help_articles,
                  get_my_booking_detail, get_my_booking_schedules, select_response_cards]
