from django import apps
from django.db import transaction


class DjcallConfig(apps.AppConfig):
    name = 'djcall'

    def ready(self):
        try:
            import uwsgi
        except ImportError:
            return

        from .models import Caller, Cron

        caller = Caller.objects.filter(callback='djcall.models.prune').first()
        if not caller:
            caller = Caller.objects.create(
                callback='djcall.models.prune',
                kwargs=dict(keep=10000),
            )

        cron = Cron.objects.filter(caller=caller).first()
        if not cron:
            cron = Cron.objects.create(caller=caller, hour=4, minute=0)
        Cron.objects.add_crons()
