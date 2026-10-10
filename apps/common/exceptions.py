# apps/common/exceptions.py

import logging

from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.http import Http404
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.db import IntegrityError, OperationalError
from datetime import datetime

logger = logging.getLogger("apps.common.exceptions")


class ConcurrentUpdateError(Exception):
    """
    Raise khi optimistic lock version không khớp
    (record vừa bị request khác sửa trong lúc xử lý),
    hoặc khi cần báo conflict tường minh ở tầng business logic.
    """

    def __init__(self, message="Dữ liệu vừa được cập nhật bởi request khác, vui lòng thử lại."):
        self.message = message
        super().__init__(self.message)


def custom_exception_handler(exc, context):
    """
    Custom exception handler cho Django REST Framework.
    Xử lý và chuẩn hóa toàn bộ lỗi (400, 401, 403, 404, 405, 409, 429, 500, 503...).
    """
    response = exception_handler(exc, context)

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
    elif isinstance(exc, ConcurrentUpdateError):

        response = Response(
            {"detail": str(exc)},
            status=status.HTTP_409_CONFLICT
        )
    elif isinstance(exc, IntegrityError):

        response = Response(
            {"detail": "Dữ liệu xung đột với ràng buộc hệ thống (có thể do trùng lặp thao tác)."},
            status=status.HTTP_409_CONFLICT
        )
    elif isinstance(exc, OperationalError):
        response = Response(
            {"detail": "Hệ thống đang xử lý yêu cầu khác, vui lòng thử lại sau ít giây."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    if response is not None:
        error_code = get_error_code(response.status_code, exc)
        message = get_error_message(response.status_code, response.data)
        if error_code == 'CHAT_CONTENT_BLOCKED':
            message = str(response.data['message'])
        errors_detail = format_errors_detail(response.data)

        custom_data = {
            "success": False,
            "status_code": response.status_code,
            "error_code": error_code,
            "message": message,
            "errors": errors_detail,
            "timestamp": datetime.now().isoformat()
        }
        new_response = Response(custom_data, status=response.status_code)
        retry_after = response.get('Retry-After')
        if retry_after:
            new_response['Retry-After'] = retry_after
        return new_response

    request = context.get("request")
    view = context.get("view")
    logger.exception(
        "Unhandled exception tại %s %s (view=%s): %s",
        getattr(request, "method", "?"),
        getattr(request, "path", "?"),
        view.__class__.__name__ if view else "?",
        exc,
    )

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
        503: "SERVICE_UNAVAILABLE",
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
    elif status_code == 409:
        return "Dữ liệu vừa bị thay đổi bởi thao tác khác."
    elif status_code == 429:
        return "Tần suất gửi yêu cầu quá cao. Vui lòng thử lại sau."
    elif status_code == 503:
        return "Hệ thống đang bận, vui lòng thử lại sau."
    elif isinstance(data, dict) and "detail" in data:
        return str(data["detail"])

    return "Đã xảy ra lỗi trong quá trình xử lý."


def format_errors_detail(data):
    """Chuẩn hóa dữ liệu chi tiết lỗi về dạng dict hoặc list rõ ràng."""
    if isinstance(data, dict):
        if "detail" in data and len(data) == 1:
            return None
        return data
    elif isinstance(data, list):
        return {"non_field_errors": data}
    return data
