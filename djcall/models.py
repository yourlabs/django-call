import itertools
import logging
import traceback
import sys

from django.db import close_old_connections
from django.db import connection
from django.db import models
from django.db import transaction
from django.db.models import signals
from django.utils import timezone
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from picklefield.fields import PickledObjectField

try:
    import uwsgi
except ImportError:
    uwsgi = None


logger = logging.getLogger(__name__)


def spooler(env):
    """
    uWSGI spooler callback

    We'll try to mimic what django does for requests
    """
    pk = env[b'call']

    # this is required otherwise some postgresql exceptions blow
    close_old_connections()

    with transaction.atomic():
        call = Call.objects.filter(pk=pk).first()

        success = getattr(uwsgi, 'SPOOL_OK', True)
        if call:
            try:
                call.call()
            except:
                max_attempts = call.caller.max_attempts
                close_old_connections()  # cleanup

                if max_attempts and call.caller.call_set.count() >= max_attempts:
                    return success
                raise  # will trigger retry from uwsgi
        else:
            logger.exception(
                f'Call(id={pk}) not found in db ! unspooling')

    close_old_connections()  # cleanup
    return success


if uwsgi:
    uwsgi.spooler = spooler


def get_spooler_path(name):
    if not uwsgi:
        return name

    if hasattr(name, 'encode'):
        name = name.encode('ascii')

    for spooler in uwsgi.spoolers:
        if hasattr(spooler, 'encode'):
            spooler = spooler.encode('ascii')
        if spooler.endswith(name):
            return spooler

    return name


def prune(**kwargs):
    keep = kwargs.get('keep', 10000)
    keep_qs = Call.objects.order_by('created')[:keep]
    drop_qs = Call.objects.exclude(
        pk__in=keep_qs.values_list('pk', flat=True)
    )
    print(f'Dropping {drop_qs.count()} Call objects')
    drop_qs._raw_delete(drop_qs.db)


class Metadata(models.Model):
    STATUS_CREATED = 0
    STATUS_SPOOLED = 1
    STATUS_STARTED = 2
    STATUS_SUCCESS = 3
    STATUS_RETRYING = 4
    STATUS_FAILURE = 5

    STATUS_CHOICES = (
        (STATUS_CREATED, _('Created')),
        (STATUS_SPOOLED, _('Spooled')),
        (STATUS_STARTED, _('Started')),
        (STATUS_SUCCESS, _('Success')),
        (STATUS_RETRYING, _('Retrying')),
        (STATUS_FAILURE, _('Failure')),
    )

    status = models.IntegerField(
        choices=STATUS_CHOICES,
        db_index=True,
        default=0,
        editable=False,
    )
    created = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        editable=False,
    )
    spooled = models.DateTimeField(null=True, editable=False)
    started = models.DateTimeField(null=True, editable=False)
    ended = models.DateTimeField(null=True, editable=False)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        editable=False,
    )

    def save_status(self, status, commit=True):
        self.status = getattr(self, f'STATUS_{status}'.upper())

        if self.status in (self.STATUS_FAILURE, self.STATUS_SUCCESS):
            self.ended = timezone.now()
        elif (self.status == self.STATUS_STARTED and
                self.status == self.STATUS_FAILURE):
            self.status = self.STATUS_RETRYING

        elif self.status == self.STATUS_STARTED:
            self.started = timezone.now()
        elif self.status == self.STATUS_SPOOLED:
            self.spooled = timezone.now()

        if commit:
            self.save()
            if not transaction.get_connection().in_atomic_block:
                transaction.commit()

    class Meta:
        abstract = True


class Caller(Metadata):
    kwargs = PickledObjectField(null=True)
    callback = models.CharField(
        max_length=255,
        db_index=True,
    )
    max_attempts = models.IntegerField(default=0)
    spooler = models.CharField(max_length=100, null=True, blank=True)
    priority = models.IntegerField(null=True, blank=True)
    signal_number = models.IntegerField(null=True, blank=True)

    def __str__(self):
        if hasattr(self.kwargs, 'items'):
            args = ', '.join([f'{k}={v}' for k, v in self.kwargs.items()])
        else:
            args = ''
        return f'{self.callback}({args})'

    @property
    def python_callback(self):
        parts = self.callback.split('.')
        i = self.callback.count('.')
        while i:
            try:
                mod = import_string('.'.join(parts[:i + 1]))
            except ImportError:
                if not i:
                    raise
                i -= 1
            else:
                ret = mod
                while 0 < i < self.callback.count('.'):
                    ret = getattr(ret, parts[len(parts) - i])
                    i -= 1
                return ret

    def python_callback_call(self):
        return self.python_callback(**self.kwargs)

    def call(self):
        if not self.pk:
            self.save()
        call = Call.objects.create(caller=self)
        call.call()
        return call

    def spool(self, spooler=None):
        if spooler:
            self.spooler = spooler
        self.save_status('spooled')
        call = Call.objects.create(caller=self)

        if uwsgi:
            arg = {b'call': str(call.pk).encode('ascii')}
            if self.spooler:
                arg[b'spooler'] = get_spooler_path(self.spooler)
            if self.priority:
                arg[b'priority'] = self.priority
            transaction.on_commit(lambda: uwsgi.spool(arg))
        else:
            call.call()

        return self


def default_kwargs(sender, instance, **kwargs):
    if instance.kwargs is None:
        instance.kwargs = dict()
signals.post_save.connect(default_kwargs, sender=Caller)


class Call(Metadata):
    STATUS_CHOICES = (
        (Caller.STATUS_CREATED, _('Created')),
        (Caller.STATUS_SPOOLED, _('Spooled')),
        (Caller.STATUS_STARTED, _('Started')),
        (Caller.STATUS_SUCCESS, _('Success')),
        (Caller.STATUS_FAILURE, _('Failure')),
    )

    caller = models.ForeignKey(Caller, on_delete=models.CASCADE)
    result = PickledObjectField(null=True, protocol=-1)
    exception = models.TextField(default='', editable=False)
    status = models.IntegerField(
        choices=STATUS_CHOICES,
        db_index=True,
        default=0,
        editable=False,
    )
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        editable=False,
    )

    def __init__(self, *args, **kwargs):
        if 'caller' not in kwargs and 'callback' in kwargs:
            kwargs['caller'] = Caller(
                callback=kwargs.pop('callback'),
                max_attempts=kwargs.pop('max_attempts'),
                kwargs=kwargs.pop('kwargs'),
            ).objects.create()

        if 'spooler' in kwargs:
            self.spooler = get_spooler_path(kwargs['spooler'])

        super().__init__(*args, **kwargs)

    def save_status(self, status, commit=True):
        super().save_status(status, commit=commit)
        self.caller.save_status(status, commit=commit)

    def call(self):
        logger.error(f'[djcall] {self.caller} -> Call(id={self.pk}).call()')
        self.save_status('started')

        sid = transaction.savepoint()
        try:
            self.result = self.caller.python_callback_call()
            transaction.savepoint_commit(sid)
        except Exception as e:
            tt, value, tb = sys.exc_info()
            transaction.savepoint_rollback(sid)
            self.exception = '\n'.join(traceback.format_exception(tt, value, tb))
            self.save_status('failure')
            logger.error(f'[djcall] {self.caller} -> Call(id={self.pk}).call(): error')
            raise

        self.save_status('success')
        logger.error(f'[djcall] {self.caller} -> Call(id={self.pk}).call(): success')


class CronManager(models.Manager):
    def register_signals(self):
        if not uwsgi:
            return

        def executor(signal_number):
            close_old_connections()
            result = Caller.objects.get(
                signal_number=signal_number
            ).call()
            close_old_connections()
            return result

        callers = Caller.objects.annotate(
            crons=models.Count('cron')
        ).prefetch_related('cron_set').exclude(crons=0)

        signal_number = 1
        for caller in callers:
            caller.signal_number = signal_number
            caller.save()

            uwsgi.register_signal(
                caller.signal_number,
                caller.spooler or 'worker',
                executor,
            )

            # logger doesn't work yet at this point of uwsgi startup apparentnly
            # logger.info(f'uwsgi.register_signal({signal_number}, {caller.callback})')
            logger.error(f'[djcall] uwsgi.register_signal({signal_number}, {caller.callback})')

            signal_number += 1

        transaction.commit()
        return callers

    def add_crons(self):
        if not uwsgi:
            return

        callers = self.register_signals()
        for caller in callers:
            for cron in caller.cron_set.all():
                cron.add_cron()


class Cron(models.Model):
    caller = models.ForeignKey(Caller, on_delete=models.CASCADE)
    minute = models.CharField(max_length=50, default='*')
    hour = models.CharField(max_length=50, default='*')
    day = models.CharField(max_length=50, default='*')
    month = models.CharField(max_length=50, default='*')
    weekday = models.CharField(max_length=50, default='*')

    objects = CronManager()

    def get_matrix(self):
        args = [
            str(self.minute),
            str(self.hour),
            str(self.day),
            str(self.month),
            str(self.weekday),
        ]

        for i, arg in enumerate(args):
            if arg == '*':
                args[i] = [-1]
            elif '-' in arg:
                n, m = arg.split('-')
                args[i] = list(range(int(n), int(m) + 1))
            else:
                args[i] = [int(arg)]

        return list(itertools.product(*args))

    def add_cron(self):
        for args in self.get_matrix():
            logger.error(f'[djcall] {self.caller} add cron : {args} signal {self.caller.signal_number}')
            uwsgi.add_cron(self.caller.signal_number, *args)
