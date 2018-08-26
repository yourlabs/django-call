"""

# Define your callback
def cb(someid, call):
    obj = YourModel.objects.get(id=someid)

    # spawn sub tasks
    for child in obj.children:
        Call(
            callback='subcb',
            kwargs=dict(childid=child.id),
            parent=call,
        ).launch()

    # return something that will be pickled too
    return dict(processed=obj.children)

call = Call(callback='your.cb', kwargs=dict(someid=1))

# Call now, through uWSGI spooler if available
call.launch()  # otherwise use spool() or execute()

while call.status == Call.STATUS_PENDING:
    call.refresh_from_db()

while call.status == Call.STATUS_SPOOLED:
    call.refresh_from_db()

while call.status == Call.STATUS_STARTED:
    call.refresh_from_db()

if call.status == Call.STATUS_SUCCESS:
    print('way to go !')

if call.status == Call.STATUS_ERROR:
    print(call.traceback)

for call in call.callable.call_set.all():
    print(call.remaining_tries)

# Call on sundays, will register in uWSGI cron if available
cron = Cron(weekday=1, callback='your.cb')

cron.register()

# List calls from cron, with subcalls from errors
for call in cron.callable.call_set.all():
    print(call.callable.call_set.all())

# "Weird" pattern right ? but simple and stupid though, somewhat, thanks to
# model inheritance
"""
import itertools
import traceback
import sys

from django.db import models
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from picklefield.fields import PickledObjectField

try:
    import uwsgi
except ImportError:
    uwsgi = None


def spooler(env):
    success = getattr(uwsgi, 'SPOOL_OK', True)
    call = Call.objects.filter(pk=env[b'call']).first()
    if call:
        try:
            call.call()
        except:
            if call.caller.call_set.count() >= call.caller.max_attempts:
                return success
            raise  # will trigger retry from uwsgi
    return success


if uwsgi:
    uwsgi.spooler = spooler


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
            transaction.commit()

    class Meta:
        abstract = True


class Caller(Metadata):
    kwargs = PickledObjectField(null=True, protocol=-1)
    callback = models.CharField(
        max_length=255,
        db_index=True,
    )
    max_attempts = models.IntegerField(default=1)
    spooler = models.CharField(max_length=100, null=True, blank=True)
    priority = models.IntegerField(null=True, blank=True)

    @property
    def python_callback(self):
        return import_string(self.callback)

    def python_callback_call(self):
        return self.python_callback(**self.kwargs)

    def call(self):
        if not self.pk:
            self.save()

        call = Call.objects.create(caller=self)
        call.call()
        return call

    def spool(self):
        self.save_status('spooled')
        call = Call.objects.create(caller=self)

        if uwsgi:
            uwsgi.spool({b'call': str(self.pk).encode('ascii')})
        else:
            call.call()

        return self


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
            self.spooler = self.get_spooler_path(kwargs['spooler'])

        super().__init__(*args, **kwargs)

    @staticmethod
    def get_spooler_path(name):
        if not uwsgi:
            return name

        for spooler in uwsgi.spoolers:
            spooler = spooler.encode('ascii')
            if spooler.endswith(name):
                return spooler

        return name

    def save_status(self, status, commit=True):
        super().save_status(status, commit=commit)
        self.caller.save_status(status, commit=commit)

    def call(self):
        self.save_status('started')
        try:
            self.result = self.caller.python_callback_call()
        except Exception as e:
            tt, value, tb = sys.exc_info()
            self.exception = '\n'.join(traceback.format_exception(tt, value, tb))
            self.save_status('failure')
            raise
        else:
            self.save_status('success')


class CronManager(models.Manager):
    def add_crons(self):
        if not uwsgi:
            return

        signal_number = 1
        for caller in Caller.objects.all():
            crons = caller.cron_set.all()

            if not crons:
                continue

            uwsgi.register_signal(
                signal_number,
                'worker',
                lambda: caller.call(),
            )

            for cron in crons:
                cron.add_cron(signal_number)

            signal_number += 1


class Cron(models.Model):
    caller = models.ForeignKey(Caller, on_delete=models.CASCADE)
    minute = models.CharField(max_length=50)
    hour = models.CharField(max_length=50)
    day = models.CharField(max_length=50)
    month = models.CharField(max_length=50)
    weekday = models.CharField(max_length=50)

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

    def add_cron(self, signal_number):
        for args in self.get_matrix():
            uwsgi.add_cron(
                signal_number,
                'worker',
                *args
            )
