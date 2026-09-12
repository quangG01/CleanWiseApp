from rest_framework.permissions import BasePermission


def get_user_role(user):
    return getattr(user, "role", None)


class IsRole(BasePermission):
    """
    Kiểm tra user đã đăng nhập và có role nằm trong allowed_roles.
    Superuser luôn được phép.
    """

    allowed_roles = ()
    message = "Bạn không có quyền truy cập tài nguyên này."

    def has_permission(self, request, view):
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and (
                get_user_role(user) in self.allowed_roles
                or user.is_superuser
            )
        )


class IsAdminRole(IsRole):
    allowed_roles = ("ADMIN",)
    message = "Chỉ quản trị viên mới có quyền thực hiện thao tác này."


class IsCustomerRole(IsRole):
    allowed_roles = ("CUSTOMER",)
    message = "Chỉ khách hàng mới có quyền thực hiện thao tác này."


class IsWorkerRole(IsRole):
    allowed_roles = ("WORKER",)
    message = "Chỉ nhân viên mới có quyền thực hiện thao tác này."


class IsAdminOrCustomerRole(IsRole):
    allowed_roles = ('ADMIN', 'CUSTOMER')
    message = "Chỉ quản trị viên hoặc khách hàng mới có quyền thực hiện thao tác này."



class IsAdminOrWorkerRole(AllowSuperuserMixin, IsRole):
    allowed_roles = ('ADMIN', 'WORKER')
    message = "Chỉ quản trị viên hoặc nhân viên mới có quyền thực hiện thao tác này."


class IsCustomerOrWorkerRole(IsRole):
    allowed_roles = ("CUSTOMER", "WORKER")
    message = "Chỉ khách hàng hoặc nhân viên mới có quyền thực hiện thao tác này."
