from rest_framework.permissions import BasePermission


class IsChatbotCustomer(BasePermission):
    message = 'Trợ lý hiện chỉ hỗ trợ tài khoản khách hàng.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user.is_authenticated and user.is_active and user.role == 'CUSTOMER')
