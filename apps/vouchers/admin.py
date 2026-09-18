from django.contrib import admin

from .models import UserVoucher, Voucher


admin.site.register(Voucher)
admin.site.register(UserVoucher)