from django.db import transaction

from .models import UserPaymentMethod


@transaction.atomic
def set_default_payment_method(method):
    UserPaymentMethod.objects.select_for_update().filter(
        user=method.user,
        usage_type=method.usage_type,
        is_active=True,
        is_default=True,
    ).exclude(pk=method.pk).update(is_default=False)

    if not method.is_default:
        method.is_default = True
        method.save(update_fields=['is_default', 'updated_at'])
    return method


@transaction.atomic
def soft_delete_payment_method(method):
    was_default = method.is_default
    method.is_active = False
    method.is_default = False
    method.save(update_fields=['is_active', 'is_default', 'updated_at'])

    if was_default:
        replacement = UserPaymentMethod.objects.select_for_update().filter(
            user=method.user,
            usage_type=method.usage_type,
            is_active=True,
        ).order_by('-created_at').first()
        if replacement:
            replacement.is_default = True
            replacement.save(update_fields=['is_default', 'updated_at'])
    return method
