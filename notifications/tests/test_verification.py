from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from notifications import verification
from notifications.models import EmailVerification

User = get_user_model()


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_MAX_ATTEMPTS=5,
    EMAIL_VERIFICATION_CODE_TTL_MINUTES=10,
)
class VerificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='c@example.com', email='c@example.com', password='pw',
            is_active=False,
        )

    def test_issue_returns_code_and_persists_hashed(self):
        code = verification.issue_code(self.user)
        self.assertRegex(code, r'^\d{6}$')
        ev = EmailVerification.objects.get(user=self.user)
        # plaintext code must NOT be stored
        self.assertNotEqual(ev.code_hash, code)
        self.assertNotIn(code, ev.code_hash)

    def test_verify_happy_path_consumes(self):
        code = verification.issue_code(self.user)
        ok, err = verification.verify_code(self.user, code)
        self.assertTrue(ok)
        self.assertIsNone(err)
        ev = EmailVerification.objects.get(user=self.user)
        self.assertTrue(ev.is_consumed)

    def test_verify_wrong_code_increments_attempts(self):
        verification.issue_code(self.user)
        ok, err = verification.verify_code(self.user, '000000')
        self.assertFalse(ok)
        self.assertEqual(err, 'incorrect')
        ev = EmailVerification.objects.get(user=self.user)
        self.assertEqual(ev.attempts, 1)

    def test_verify_blocks_after_max_attempts(self):
        verification.issue_code(self.user)
        for _ in range(5):
            verification.verify_code(self.user, '000000')
        ok, err = verification.verify_code(self.user, '000000')
        self.assertFalse(ok)
        self.assertEqual(err, 'too_many_attempts')

    def test_verify_expired_code(self):
        code = verification.issue_code(self.user)
        ev = EmailVerification.objects.get(user=self.user)
        from datetime import timedelta

        from django.utils import timezone
        ev.expires_at = timezone.now() - timedelta(minutes=1)
        ev.save(update_fields=['expires_at'])
        ok, err = verification.verify_code(self.user, code)
        self.assertFalse(ok)
        self.assertEqual(err, 'expired')

    def test_consumed_code_cannot_be_reused(self):
        code = verification.issue_code(self.user)
        verification.verify_code(self.user, code)
        ok, err = verification.verify_code(self.user, code)
        self.assertFalse(ok)
        self.assertEqual(err, 'no_active_code')

    def test_issue_invalidates_prior_unconsumed(self):
        verification.issue_code(self.user)
        verification.issue_code(self.user)
        active = EmailVerification.objects.filter(
            user=self.user, consumed_at__isnull=True
        )
        # only the newest remains active; prior was consumed/invalidated
        self.assertEqual(active.count(), 1)

    def test_issue_and_send_sends_email(self):
        verification.issue_and_send(self.user)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
