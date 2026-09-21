from django.contrib import admin

from .models import Payment, UserPaymentMethod


admin.site.register(Payment)


@admin.register(UserPaymentMethod)
class UserPaymentMethodAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'method_type', 'usage_type', 'bank_name',
        'account_number_last4', 'verification_status', 'is_default', 'is_active',
    )
    list_filter = ('method_type', 'usage_type', 'verification_status', 'is_default', 'is_active')
    search_fields = ('user__username', 'user__email', 'bank_name', 'account_holder_name')
    readonly_fields = ('account_number_encrypted', 'account_number_last4', 'created_at', 'updated_at')
