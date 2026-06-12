from django.core import mail
from django.test import TestCase, override_settings

from notifications.models import EmailMessageLog
from notifications.service import send_email, EmailSendError


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SendEmailTests(TestCase):
    def test_sends_and_logs_sent(self):
        log = send_email(
            'to@example.com', 'verification_code',
            {'code': '123456', 'ttl_minutes': 10},
        )
        self.assertEqual(log.status, 'sent')
        self.assertIsNotNone(log.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['to@example.com'])
        self.assertIn('123456', msg.body)  # text body
        # html alternative present
        self.assertTrue(any('123456' in c for c, _ in msg.alternatives))

    def test_failure_marks_log_failed_and_raises(self):
        with override_settings(
            EMAIL_BACKEND='notifications.tests.test_engine.BoomBackend'
        ):
            with self.assertRaises(EmailSendError):
                send_email('to@example.com', 'verification_code',
                           {'code': '000000', 'ttl_minutes': 10})
        log = EmailMessageLog.objects.latest('created_at')
        self.assertEqual(log.status, 'failed')
        self.assertTrue(log.error)


from django.core.mail.backends.base import BaseEmailBackend


class BoomBackend(BaseEmailBackend):
    def send_messages(self, messages):
        raise RuntimeError('provider down')
