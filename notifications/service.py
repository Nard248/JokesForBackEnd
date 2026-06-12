"""The notification engine entry point.

Feature code calls send_email(); it renders a registered template, writes an
EmailMessageLog row, and dispatches through Django's configured EMAIL_BACKEND
(anymail->Resend in prod, console locally, locmem in tests). Synchronous in v1;
the EmailMessageLog.status field is the seam for future async (Cloud Tasks)
dispatch with no schema change.
"""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from .models import EmailMessageLog
from .templates_registry import render_template


class EmailSendError(Exception):
    """Raised when the transport layer fails to send. Caller decides UX."""


def send_email(to_email, template_name, context, user=None):
    """Render, log, and dispatch an email. Returns the EmailMessageLog row."""
    subject, html_body, text_body = render_template(template_name, context)

    log = EmailMessageLog.objects.create(
        to_email=to_email, template_name=template_name,
        subject=subject, status='pending', user=user,
    )
    try:
        msg = EmailMultiAlternatives(
            subject=subject, body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL, to=[to_email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send()
        log.status = 'sent'
        log.sent_at = timezone.now()
        log.save(update_fields=['status', 'sent_at'])
    except Exception as exc:
        log.status = 'failed'
        log.error = str(exc)
        log.save(update_fields=['status', 'error'])
        raise EmailSendError(str(exc)) from exc
    return log
