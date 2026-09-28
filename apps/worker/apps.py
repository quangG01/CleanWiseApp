from django.apps import AppConfig


class WorkerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.worker'

    def ready(self):
        from . import signals