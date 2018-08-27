from django.conf import settings
from django.core.mail import EmailMessage


def email_send(**kwargs):
    email = EmailMessage(
        subject=kwargs.get('subject'),
        body=kwargs.get('body'),
        from_email=kwargs.get('from_email', settings.DEFAULT_FROM_EMAIL),
        to=kwargs.get('to'),
        bcc=kwargs.get('bcc', None),
        cc=kwargs.get('cc', None),
        headers=kwargs.get('headers', None),
        reply_to=kwargs.get('reply_to', None),
    )

    if 'content_subtype' in kwargs:
        email.content_subtype = kwargs['content_subtype']

    email.send()
