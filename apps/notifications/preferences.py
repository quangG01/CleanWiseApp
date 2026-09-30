from .models import NotificationPreference


def get_preference(user):
    """Dùng ở API: lấy hoặc tạo cài đặt của người dùng."""
    pref, _ = NotificationPreference.objects.get_or_create(user=user)
    return pref


def can_push(user_id) -> bool:
    """Có được gửi push cho user_id này không.
    Chưa có dòng cài đặt = mặc định bật."""
    return (
        NotificationPreference.objects
        .filter(user_id=user_id)
        .values_list('push_enabled', flat=True)
        .first()
    ) is not False