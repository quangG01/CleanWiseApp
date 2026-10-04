# apps/complaints/permissions.py

from apps.common.permissions import get_user_role
from rest_framework.permissions import BasePermission


class IsComplaintOwnerOrAdmin(BasePermission):
    """
    Chỉ người GỬI khiếu nại (khách hoặc nhân viên) hoặc ADMIN/superuser
    mới xem được complaint. Người bị khiếu nại (worker khi reporter là
    khách) KHÔNG tự động xem được — tránh biến đây thành kênh đối chất.
    """

    message = 'Bạn không có quyền truy cập khiếu nại này.'

    def has_object_permission(self, request, view, obj):
        user = request.user

        if (
            user.is_superuser
            or get_user_role(user) == 'ADMIN'
        ):
            return True

        return obj.reporter_id == user.id