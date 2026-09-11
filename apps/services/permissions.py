from rest_framework import permissions

from apps.common.permissions import IsAdminRole


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    GET/HEAD/OPTIONS: Cho phép mọi người truy cập.

    POST/PATCH/PUT/DELETE:
    Chỉ ADMIN hoặc superuser.
    """

    message = "Chỉ quản trị viên mới có quyền thực hiện thao tác này."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True

        return IsAdminRole().has_permission(request, view)
