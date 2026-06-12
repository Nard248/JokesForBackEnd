from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from notifications import verification

User = get_user_model()

RESEND_URL = '/api/v1/auth/resend-verification/'
VERIFY_URL = '/api/v1/auth/verify-email/'


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_REQUIRED=True,
)
class ResendThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()  # throttle state lives in the cache; isolate per test
        self.user = User.objects.create_user(
            username='t@example.com', email='t@example.com', password='pw',
            is_active=False,
        )

    def tearDown(self):
        cache.clear()

    def test_fourth_resend_in_window_is_throttled(self):
        # scope verification_resend = 3/15min
        for i in range(3):
            r = self.client.post(RESEND_URL, {'email': self.user.email}, format='json')
            self.assertEqual(r.status_code, 200, f'resend {i + 1}: {r.content}')
        r4 = self.client.post(RESEND_URL, {'email': self.user.email}, format='json')
        self.assertEqual(r4.status_code, 429, r4.content)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_REQUIRED=True,
    EMAIL_VERIFICATION_MAX_ATTEMPTS=5,
)
class VerifyErrorResponseTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='a@example.com', email='a@example.com', password='pw',
            is_active=False,
        )

    def tearDown(self):
        cache.clear()

    def test_too_many_attempts_returns_429_with_detail(self):
        verification.issue_code(self.user)
        for _ in range(5):
            self.client.post(
                VERIFY_URL, {'email': self.user.email, 'code': '000000'}, format='json'
            )
        resp = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': '000000'}, format='json'
        )
        self.assertEqual(resp.status_code, 429, resp.content)
        self.assertIn('detail', resp.json())

    def test_already_verified_user_gets_clear_message(self):
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        resp = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': '123456'}, format='json'
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('already verified', resp.json()['detail'].lower())
