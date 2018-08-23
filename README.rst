First made a dead simple pure python generic spooler for uwsgi:
https://gist.github.com/jpic/d28333b0573c3c555fbe6e55862ecddb

The made a first implementation including CRUDLFA+ support:
https://github.com/yourlabs/django-uwsgi-spooler

This version adds:

- Cron model and support for uWSGI cron, can't add/remove them without restart,
  but can change kwargs and options online
- CRUDLA+ support is on hold waiting for what's currently in
  https://github.com/tbinetruy/CHIP because i don't want to build crud support
  here with templates because of the debt this will add, it's time to use
  components in CRUDLFA+ to make the CRUD for Cron/Background tasks awesome
