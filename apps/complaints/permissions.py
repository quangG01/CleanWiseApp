# apps/complaints/permissions.py

from apps.common.permissions import get_user_role
from rest_framework.permissions import BasePermission


class IsComplaintOwnerOrAdmin(BasePermission):
    """
    Chỉ chủ khiếu nại hoặc ADMIN/superuser
    mới xem được complaint.
    """

    message = 'Bạn không có quyền truy cập khiếu nại này.'

    def has_object_permission(self, request, view, obj):
        user = request.user

        if (
            user.is_superuser
            or get_user_role(user) == 'ADMIN'
        ):
            return True

        return obj.customer_id == user.id