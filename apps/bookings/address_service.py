from django.db import transaction

from .models import CustomerAddress


@transaction.atomic
def set_default_address(address):
    """Đặt một địa điểm hoạt động làm mặc định duy nhất của khách hàng."""
    address.customer.__class__.objects.select_for_update().get(pk=address.customer_id)
    CustomerAddress.objects.select_for_update().filter(
        customer=address.customer,
        is_active=True,
    ).update(is_default=False)
    address.is_default = True
    address.save(update_fields=['is_default', 'updated_at'])
    return address


@transaction.atomic
def soft_delete_address(address):
    """Xóa mềm địa điểm và chọn địa điểm mặc định thay thế khi cần."""
    was_default = address.is_default
    address.is_active = False
    address.is_default = False
    address.save(update_fields=['is_active', 'is_default', 'updated_at'])

    if was_default:
        replacement = (
            CustomerAddress.objects.select_for_update()
            .filter(customer=address.customer, is_active=True)
            .order_by('-updated_at', '-created_at', '-id')
            .first()
        )
        if replacement:
            set_default_address(replacement)
    return address
