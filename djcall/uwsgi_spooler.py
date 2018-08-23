try:
    import uwsgi
except ImportError:
    uwsgi = None


def spooler(env):
    pk = UUID(env[b'uuid'].decode('ascii'))
    task = Task.objects.filter(pk=pk).first()
    if task:
        task.execute()
    return getattr(uwsgi, 'SPOOL_OK', True)


if uwsgi:
    uwsgi.spooler = spooler
