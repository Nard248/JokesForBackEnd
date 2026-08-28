"""Signup must finish with a usable session on the native path.

The web flow ends verification by setting httpOnly cookies, which is right for
a browser. A native client reading the body gets `{"user": {...}}` and no
credentials at all, so it has to turn around and POST the password again to
`/auth/native/login/` — a second round trip, a password held in memory longer
than it needs to be, and a window where a user who verified successfully is
nonetheless signed out if that second call fails.

`POST /auth/native/verify-email/` closes it: same verification, same 6-digit
code, same lockout, but the response carries the token pair. It completes the
pattern `native/login` and `native/refresh` already establish.
"""
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from notifications import verification

User = get_user_model()

VERIFY_URL = '/api/v1/auth/native/verify-email/'
LOGIN_URL = '/api/v1/auth/native/login/'
PASSWORD = 'sup3rsecret!'


@override_settings(EMAIL_VERIFICATION_REQUIRED=True)
class NativeVerifyEmailTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='pending@example.com', email='pending@example.com',
            password=PASSWORD, is_active=False,
        )
        self.code = verification.issue_code(self.user)

    def test_verifying_returns_a_usable_token_pair(self):
        resp = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': self.code}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()

        self.assertTrue(body.get('access'))
        self.assertTrue(
            body.get('refresh'),
            'signup finished without credentials — the client must log in again',
        )
        self.assertEqual(body['user']['email'], self.user.email)

    def test_it_sets_no_cookies(self):
        resp = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': self.code}, format='json',
        )
        for name in ('jokes-access-token', 'jokes-refresh-token'):
            self.assertNotIn(name, resp.cookies)

    def test_the_returned_token_authenticates_immediately(self):
        token = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': self.code}, format='json',
        ).json()['access']

        client = self.client_class()
        resp = client.get('/api/v1/auth/user/', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_verifying_activates_the_account(self):
        self.client.post(VERIFY_URL, {'email': self.user.email, 'code': self.code}, format='json')
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active, '`is_active` IS the verification gate')

    def test_a_wrong_code_is_refused_and_issues_no_tokens(self):
        resp = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': '000000'}, format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertNotIn('access', resp.json())
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_a_code_cannot_be_replayed(self):
        first = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': self.code}, format='json',
        )
        self.assertEqual(first.status_code, 200, first.content)

        replay = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': self.code}, format='json',
        )
        self.assertNotEqual(replay.status_code, 200, 'a spent code was accepted again')

    def test_an_unknown_email_does_not_confirm_whether_it_exists(self):
        """Enumeration guard: the response must not distinguish 'no such user'
        from 'wrong code'."""
        unknown = self.client.post(
            VERIFY_URL, {'email': 'nobody@example.com', 'code': '123456'}, format='json',
        )
        wrong = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': '000000'}, format='json',
        )
        self.assertEqual(unknown.status_code, wrong.status_code)
