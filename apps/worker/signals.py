from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.common.cache_utils import bump_version
from .models import Area


@receiver([post_save, post_delete], sender=Area)
def invalidate_areas_cache(sender, **kwargs):
    transaction.on_commit(lambda: bump_version('areas'))