from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.common.cache_utils import bump_version
from .models import Service, ServiceImage


@receiver([post_save, post_delete], sender=Service)
@receiver([post_save, post_delete], sender=ServiceImage)
def invalidate_services_cache(sender, **kwargs):
    # on_commit: chỉ xóa SAU khi transaction ghi DB xong. Nếu xóa trước,
    # request khác có thể nạp lại dữ liệu cũ vào cache trong lúc chưa commit.
    transaction.on_commit(lambda: bump_version('services'))