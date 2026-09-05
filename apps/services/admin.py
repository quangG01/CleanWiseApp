from django.contrib import admin
from .models import Service, ServiceCategory, ServiceImage, ServicePackage

admin.site.register(ServiceCategory)
admin.site.register(Service)
admin.site.register(ServiceImage)
admin.site.register(ServicePackage)
