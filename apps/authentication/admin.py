from django.contrib import admin
from .models import PasswordResetOTP, User, WorkerProfile, WorkerVerificationDocument

admin.site.register(User)
admin.site.register(WorkerProfile)
admin.site.register(WorkerVerificationDocument)
admin.site.register(PasswordResetOTP)
