"""The token contract a native (iOS) client depends on.

Why this exists
---------------
The web client authenticates with httpOnly cookies: ``JWT_AUTH_HTTPONLY=True``
blanks ``refresh`` in every response body, so the only copy of the rotating
refresh token lives in the ``jokes-refresh-token`` Set-Cookie header. That is
correct and deliberate for a browser — it is what keeps XSS from stealing a
long-lived credential.

It is unusable from a native app. With ``ROTATE_REFRESH_TOKENS`` and
``BLACKLIST_AFTER_ROTATION`` both on, a client that reads the body gets
``refresh: ""`` at login and no ``refresh`` key at all from the refresh
endpoint, so it can refresh exactly once before its token is blacklisted and
every subsequent call 401s.

A native client *could* lean on ``URLSession``'s implicit cookie jar, and that
happens to work — which is precisely the trap. It depends on undocumented
behaviour, it cannot be stored in the Keychain, and one request that carries the
cookie without an ``Authorization`` header silently falls into the CSRF-enforced
cookie path and 403s every mutation.

So the native path gets its own endpoints: tokens in the body, no cookies set,
and a refresh lifetime long enough that a daily-ritual app does not log people
out for skipping a day.

These tests pin all of that. The load-bearing one is
``test_refresh_twice_consecutively`` — a single refresh passing proves nothing,
because the first rotation always succeeds. Only the second one proves the
client kept a token it can actually use again.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

User = get_user_model()

LOGIN_URL = '/api/v1/auth/native/login/'
REFRESH_URL = '/api/v1/auth/native/refresh/'
ME_URL = '/api/v1/auth/user/'

PASSWORD = 'sup3rsecret!'

#: Cookie names the web flow sets. The native path must set none of them —
#: a native client that silently acquires a cookie jar is the failure this
#: whole module exists to prevent.
JWT_COOKIES = ('jokes-access-token', 'jokes-refresh-token')


class NativeLoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='native@example.com', email='native@example.com', password=PASSWORD,
        )

    def test_returns_a_usable_refresh_token_in_the_body(self):
        """The bug this endpoint exists for: the web login returns refresh: ""."""
        resp = self.client.post(
            LOGIN_URL, {'email': 'native@example.com', 'password': PASSWORD}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()

        self.assertTrue(body.get('refresh'), 'refresh token missing or empty in the body')
        self.assertTrue(body.get('access'))
        # Not merely present — actually parseable and not blacklisted.
        RefreshToken(body['refresh'])

    def test_sets_no_cookies_at_all(self):
        resp = self.client.post(
            LOGIN_URL, {'email': 'native@example.com', 'password': PASSWORD}, format='json',
        )
        for name in JWT_COOKIES:
            self.assertNotIn(name, resp.cookies)
        self.assertEqual(len(resp.cookies), 0, f'unexpected cookies: {list(resp.cookies)}')

    def test_returns_expiry_metadata_and_the_user(self):
        """A native client cannot read a cookie's Max-Age, so it needs the
        lifetimes in the body to schedule a pre-emptive refresh."""
        resp = self.client.post(
            LOGIN_URL, {'email': 'native@example.com', 'password': PASSWORD}, format='json',
        )
        body = resp.json()
        self.assertIn('access_expires_in', body)
        self.assertIn('refresh_expires_in', body)
        self.assertEqual(body['user']['email'], 'native@example.com')

    def test_refresh_lifetime_is_thirty_days_not_the_web_default(self):
        """A 1-day refresh logs out anyone who skips a day. In a product whose
        entire premise is a daily ritual, that is a retention bug, not a
        security posture."""
        resp = self.client.post(
            LOGIN_URL, {'email': 'native@example.com', 'password': PASSWORD}, format='json',
        )
        body = resp.json()
        self.assertGreater(body['refresh_expires_in'], timedelta(days=29).total_seconds())

    def test_access_token_authenticates_as_a_bearer_credential(self):
        body = self.client.post(
            LOGIN_URL, {'email': 'native@example.com', 'password': PASSWORD}, format='json',
        ).json()

        client = self.client_class()
        resp = client.get(ME_URL, HTTP_AUTHORIZATION=f"Bearer {body['access']}")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['email'], 'native@example.com')

    def test_rejects_a_wrong_password(self):
        resp = self.client.post(
            LOGIN_URL, {'email': 'native@example.com', 'password': 'wrong'}, format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_rejects_an_unverified_user(self):
        """`is_active` IS the email-verification gate. The native path must not
        become a way around it."""
        User.objects.create_user(
            username='pending@example.com', email='pending@example.com',
            password=PASSWORD, is_active=False,
        )
        resp = self.client.post(
            LOGIN_URL, {'email': 'pending@example.com', 'password': PASSWORD}, format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertNotIn('access', resp.json())


class NativeRefreshTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='rotate@example.com', email='rotate@example.com', password=PASSWORD,
        )
        self.tokens = self.client.post(
            LOGIN_URL, {'email': 'rotate@example.com', 'password': PASSWORD}, format='json',
        ).json()

    def test_returns_both_new_tokens_in_the_body(self):
        resp = self.client.post(
            REFRESH_URL, {'refresh': self.tokens['refresh']}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertTrue(body.get('access'))
        self.assertTrue(
            body.get('refresh'),
            'no rotated refresh token in the body — the client is now locked out',
        )
        self.assertNotEqual(body['refresh'], self.tokens['refresh'], 'token did not rotate')

    def test_refresh_twice_consecutively(self):
        """The exit criterion for the whole native-auth milestone.

        One refresh always succeeds — the token issued at login is valid by
        construction. The second refresh is what proves the client received a
        token it can *keep using*, which is exactly what the cookie-only
        contract fails to provide.
        """
        first = self.client.post(
            REFRESH_URL, {'refresh': self.tokens['refresh']}, format='json',
        )
        self.assertEqual(first.status_code, 200, first.content)

        second = self.client.post(
            REFRESH_URL, {'refresh': first.json()['refresh']}, format='json',
        )
        self.assertEqual(
            second.status_code, 200,
            f'second consecutive refresh failed — a native client gets exactly '
            f'one refresh and is then locked out: {second.content}',
        )
        self.assertTrue(second.json().get('access'))

    def test_rotated_token_survives_a_full_bearer_round_trip(self):
        refreshed = self.client.post(
            REFRESH_URL, {'refresh': self.tokens['refresh']}, format='json',
        ).json()

        client = self.client_class()
        resp = client.get(ME_URL, HTTP_AUTHORIZATION=f"Bearer {refreshed['access']}")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_sets_no_cookies(self):
        resp = self.client.post(
            REFRESH_URL, {'refresh': self.tokens['refresh']}, format='json',
        )
        self.assertEqual(len(resp.cookies), 0, f'unexpected cookies: {list(resp.cookies)}')

    def test_replaying_a_rotated_token_is_rejected(self):
        """Rotation must still blacklist. Long-lived native refresh tokens make
        replay protection more important, not less."""
        self.client.post(REFRESH_URL, {'refresh': self.tokens['refresh']}, format='json')

        replay = self.client.post(
            REFRESH_URL, {'refresh': self.tokens['refresh']}, format='json',
        )
        self.assertEqual(replay.status_code, 401, replay.content)

    def test_rejects_garbage(self):
        resp = self.client.post(REFRESH_URL, {'refresh': 'not-a-token'}, format='json')
        self.assertEqual(resp.status_code, 401, resp.content)

    def test_rejects_an_access_token_used_as_a_refresh_token(self):
        resp = self.client.post(
            REFRESH_URL, {'refresh': self.tokens['access']}, format='json',
        )
        self.assertEqual(resp.status_code, 401, resp.content)

    def test_rotated_refresh_keeps_the_thirty_day_lifetime(self):
        """If rotation silently fell back to the global 1-day lifetime, the
        30-day window would quietly evaporate after the first refresh."""
        body = self.client.post(
            REFRESH_URL, {'refresh': self.tokens['refresh']}, format='json',
        ).json()
        self.assertGreater(body['refresh_expires_in'], timedelta(days=29).total_seconds())


class NativeAuthIsolationTests(APITestCase):
    """The native endpoints must not weaken the web contract they sit beside."""

    def test_web_login_still_withholds_the_refresh_token(self):
        User.objects.create_user(
            username='web@example.com', email='web@example.com', password=PASSWORD,
        )
        resp = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'web@example.com', 'password': PASSWORD}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(
            resp.json().get('refresh'),
            'the web login body leaked a refresh token — httpOnly hardening regressed',
        )
        self.assertIn('jokes-refresh-token', resp.cookies)

    def test_access_token_lifetime_is_unchanged(self):
        """Only the *refresh* lifetime is extended for native. A long-lived
        access token would widen the blast radius of a stolen one."""
        user = User.objects.create_user(
            username='life@example.com', email='life@example.com', password=PASSWORD,
        )
        body = self.client.post(
            LOGIN_URL, {'email': 'life@example.com', 'password': PASSWORD}, format='json',
        ).json()
        self.assertLessEqual(body['access_expires_in'], timedelta(minutes=15).total_seconds())
        AccessToken(body['access'])  # parses, and is an access token
        # simplejwt serialises the claim as a string.
        self.assertEqual(str(AccessToken(body['access'])['user_id']), str(user.pk))
