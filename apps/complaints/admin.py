from django.contrib import admin

from .models import Complaint, ComplaintAttachment


admin.site.register(Complaint)
admin.site.register(ComplaintAttachment)
