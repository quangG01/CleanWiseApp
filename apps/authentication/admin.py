from django.contrib import admin
from .models import CustomerProfile, User, WorkerProfile, WorkerVerificationDocument

admin.site.register(User)
admin.site.register(CustomerProfile)
admin.site.register(WorkerProfile)
admin.site.register(WorkerVerificationDocument)
