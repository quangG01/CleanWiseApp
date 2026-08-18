from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.http import Http404
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from datetime import datetime


def custom_exception_handler(exc, context):
    """
    Custom exception handler cho Django REST Framework.
    Xử lý và chuẩn hóa toàn bộ lỗi (400, 401, 403, 404, 405, 429, 500...).
    """
    # Gọi exception handler mặc định của DRF để lấy response ban đầu
    response = exception_handler(exc, context)

    # 1. Chuyển đổi các ngoại lệ mặc định của Django sang DRF
    if isinstance(exc, Http404):
        response = Response(
            {"detail": "Yêu cầu không tồn tại."},
            status=status.HTTP_404_NOT_FOUND
        )
    elif isinstance(exc, PermissionDenied):
        response = Response(
            {"detail": "Bạn không có quyền thực hiện thao tác này."},
            status=status.HTTP_403_FORBIDDEN
        )
    elif isinstance(exc, DjangoValidationError):
        response = Response(
            {"detail": exc.messages if hasattr(exc, 'messages') else str(exc)},
            status=status.HTTP_400_BAD_REQUEST
        )

    # 2. Xử lý trường hợp có Response (Lỗi do DRF hoặc Django đã được bắt)
    if response is not None:
        error_code = get_error_code(response.status_code, exc)
        message = get_error_message(response.status_code, response.data)
        errors_detail = format_errors_detail(response.data)

        custom_data = {
            "success": False,
            "status_code": response.status_code,
            "error_code": error_code,
            "message": message,
            "errors": errors_detail,
            "timestamp": datetime.now().isoformat()
        }
        return Response(custom_data, status=response.status_code)

    # 3. Xử lý Unhandled Exceptions / Crash Server (Mã 500)
    return Response(
        {
            "success": False,
            "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": "Lỗi hệ thống nội bộ. Vui lòng thử lại sau.",
            "errors": None,
            "timestamp": datetime.now().isoformat()
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR
    )


def get_error_code(status_code, exc):
    """Xác định Mã lỗi (String ID) dựa trên HTTP Status Code và Exception Type."""
    if hasattr(exc, 'default_code') and exc.default_code:
        return str(exc.default_code).upper()

    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        429: "TOO_MANY_REQUESTS",
    }
    return code_map.get(status_code, "API_ERROR")


def get_error_message(status_code, data):
    """Tạo câu thông báo tổng quan ngắn gọn theo ngữ cảnh lỗi."""
    if status_code == 400:
        return "Dữ liệu gửi lên không hợp lệ."
    elif status_code == 401:
        return "Phiên làm việc hết hạn hoặc chưa được xác thực."
    elif status_code == 403:
        return "Bạn không có quyền truy cập tài nguyên này."
    elif status_code == 404:
        return "Không tìm thấy tài nguyên yêu cầu."
    elif status_code == 429:
        return "Tần suất gửi yêu cầu quá cao. Vui lòng thử lại sau."
    elif isinstance(data, dict) and "detail" in data:
        return str(data["detail"])
    
    return "Đã xảy ra lỗi trong quá trình xử lý."


def format_errors_detail(data):
    """Chuẩn hóa dữ liệu chi tiết lỗi về dạng dict hoặc list rõ ràng."""
    if isinstance(data, dict):
        # Nếu có trường 'detail', trích xuất ra gọn gàng
        if "detail" in data and len(data) == 1:
            return None
        return data
    elif isinstance(data, list):
        return {"non_field_errors": data}
    return data