from django.contrib import admin
from .models import (
    Booking,
    BookingSchedule,
    BookingScheduleImage,
)

admin.site.register(Booking)
admin.site.register(BookingSchedule)
admin.site.register(BookingScheduleImage)
