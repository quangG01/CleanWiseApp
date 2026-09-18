from django.contrib import admin

from .models import Area, BookingAssignment, WorkerAvailability, WorkerWorkingArea


admin.site.register(Area)
admin.site.register(WorkerWorkingArea)
admin.site.register(WorkerAvailability)
admin.site.register(BookingAssignment)
