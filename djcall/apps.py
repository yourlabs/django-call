from django import apps


class DjcallConfig(apps.AppConfig):
    name = 'djcall'

    def ready(self):
        from .models import Cron
        Cron.objects.add_crons()
