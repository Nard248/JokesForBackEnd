from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase

from notifications import verification
from notifications.models import EmailVerification

User = get_user_model()

VERIFY_URL = '/api/v1/auth/verify-email/'
RESEND_URL = '/api/v1/auth/resend-verification/'


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_REQUIRED=True,
)
class VerifyEmailEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='p@example.com', email='p@example.com', password='pw',
            is_active=False,
        )

    def _issue(self):
        return verification.issue_code(self.user)

    def test_verify_happy_path_activates_and_sets_cookies(self):
        code = self._issue()
        resp = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': code}, format='json'
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('user', resp.json())
        self.assertIn('jokes-access-token', resp.cookies)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_verify_wrong_code(self):
        self._issue()
        resp = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': '000000'}, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('code', resp.json())

    def test_verify_expired_code(self):
        code = self._issue()
        from datetime import timedelta

        from django.utils import timezone
        ev = EmailVerification.objects.get(user=self.user)
        ev.expires_at = timezone.now() - timedelta(minutes=1)
        ev.save(update_fields=['expires_at'])
        resp = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': code}, format='json'
        )
        self.assertEqual(resp.status_code, 400)

    def test_verify_unknown_email_uniform_400(self):
        resp = self.client.post(
            VERIFY_URL, {'email': 'nobody@example.com', 'code': '123456'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_REQUIRED=True,
)
class ResendEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='r@example.com', email='r@example.com', password='pw',
            is_active=False,
        )

    def test_resend_sends_new_code_and_invalidates_prior(self):
        verification.issue_code(self.user)
        resp = self.client.post(
            RESEND_URL, {'email': self.user.email}, format='json'
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(mail.outbox), 1)
        active = EmailVerification.objects.filter(
            user=self.user, consumed_at__isnull=True
        )
        self.assertEqual(active.count(), 1)

    def test_resend_unknown_email_uniform_200(self):
        resp = self.client.post(
            RESEND_URL, {'email': 'nobody@example.com'}, format='json'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
