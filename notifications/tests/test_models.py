from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from notifications.models import EmailMessageLog, EmailVerification

User = get_user_model()


class EmailVerificationModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='v@example.com', email='v@example.com', password='pw',
        )

    def test_is_expired_true_when_past(self):
        ev = EmailVerification.objects.create(
            user=self.user, code_hash='x',
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertTrue(ev.is_expired)

    def test_is_expired_false_when_future(self):
        ev = EmailVerification.objects.create(
            user=self.user, code_hash='x',
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.assertFalse(ev.is_expired)

    def test_is_consumed_reflects_consumed_at(self):
        ev = EmailVerification.objects.create(
            user=self.user, code_hash='x',
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.assertFalse(ev.is_consumed)
        ev.consumed_at = timezone.now()
        self.assertTrue(ev.is_consumed)


class EmailMessageLogModelTests(TestCase):
    def test_defaults(self):
        log = EmailMessageLog.objects.create(
            to_email='a@example.com', template_name='verification_code',
            subject='Your code',
        )
        self.assertEqual(log.status, 'pending')
        self.assertEqual(log.error, '')
        self.assertIsNone(log.sent_at)
