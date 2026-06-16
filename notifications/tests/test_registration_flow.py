from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase

from notifications.models import EmailVerification

User = get_user_model()

REG_URL = '/api/v1/auth/registration/'


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_REQUIRED=True,
)
class GatedRegistrationTests(APITestCase):
    def test_register_creates_inactive_user_no_tokens(self):
        resp = self.client.post(REG_URL, {
            'email': 'new@example.com',
            'password1': 'sup3rsecret!', 'password2': 'sup3rsecret!',
            'date_of_birth': '2000-01-01',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['email'], 'new@example.com')
        self.assertNotIn('access', body)
        self.assertNotIn('user', body)
        self.assertNotIn('jokes-access-token', resp.cookies)

        self.assertIn('detail', body)

        user = User.objects.get(email='new@example.com')
        self.assertFalse(user.is_active)
        self.assertEqual(EmailVerification.objects.filter(user=user).count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND='notifications.tests.test_registration_flow.BoomBackend')
    def test_register_returns_502_when_email_fails_but_keeps_user_recoverable(self):
        resp = self.client.post(REG_URL, {
            'email': 'boom@example.com',
            'password1': 'sup3rsecret!', 'password2': 'sup3rsecret!',
            'date_of_birth': '2000-01-01',
        }, format='json')
        self.assertEqual(resp.status_code, 502, resp.content)
        # User exists, inactive, with an issued (unconsumed) code -> recoverable
        # via resend; no session granted.
        user = User.objects.get(email='boom@example.com')
        self.assertFalse(user.is_active)
        self.assertEqual(
            EmailVerification.objects.filter(user=user, consumed_at__isnull=True).count(),
            1,
        )
        self.assertNotIn('jokes-access-token', resp.cookies)


from django.core.mail.backends.base import BaseEmailBackend


class BoomBackend(BaseEmailBackend):
    def send_messages(self, messages):
        raise RuntimeError('provider down')


@override_settings(EMAIL_VERIFICATION_REQUIRED=False)
class UngatedRegistrationTests(APITestCase):
    def test_register_keeps_legacy_behavior_active_user_with_cookies(self):
        resp = self.client.post(REG_URL, {
            'email': 'legacy@example.com',
            'password1': 'sup3rsecret!', 'password2': 'sup3rsecret!',
            'date_of_birth': '2000-01-01',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        user = User.objects.get(email='legacy@example.com')
        self.assertTrue(user.is_active)
        self.assertIn('jokes-access-token', resp.cookies)
