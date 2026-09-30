from .models import BookingActivity


def record_booking_activity(
    *, booking, event_type, message, actor=None, schedule=None,
    old_data=None, new_data=None, metadata=None,
):
    """Ghi audit có chủ đích từ service để luôn giữ được actor và lý do."""
    return BookingActivity.objects.create(
        booking=booking,
        schedule=schedule,
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        event_type=event_type,
        message=message,
        old_data=old_data,
        new_data=new_data,
        metadata=metadata or {},
    )
