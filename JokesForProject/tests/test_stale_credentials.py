"""Deleted users and stale JWTs on the auth endpoints (JokesForProject/auth_views.py).

* Refreshing a signed, unexpired refresh token whose user was deleted used to
  raise ``User.DoesNotExist`` inside simplejwt and answer 500 on both the cookie
  and the native refresh endpoints. It is a 401 ``token_not_valid`` now.
* A stale access cookie (deleted user, expired, garbage) made the default
  ``JWTCookieAuthentication`` 401 the very endpoints that replace it, so a
  browser holding one could not log in again. Login, logout, registration and
  Google login treat it as anonymous; CSRF is still enforced when it is sent.
"""
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

ACCESS_COOKIE = 'jokes-access-token'
REFRESH_COOKIE = 'jokes-refresh-token'
PASSWORD = 'sup3rsecret!'


def _orphaned_tokens():
    """A refresh/access pair minted for a user who is then deleted."""
    ghost = User.objects.create_user(username='ghost@example.com', email='ghost@example.com', password=PASSWORD)
    refresh = RefreshToken.for_user(ghost)
    tokens = str(refresh), str(refresh.access_token)
    ghost.delete()
    return tokens


class DeletedUserRefreshTests(APITestCase):
    def test_cookie_refresh_for_a_deleted_user_is_401_not_500(self):
        refresh, _access = _orphaned_tokens()
        self.client.cookies[REFRESH_COOKIE] = refresh
        resp = self.client.post('/api/v1/auth/token/refresh/', {}, format='json')
        self.assertEqual(resp.status_code, 401, resp.content)
        self.assertEqual(resp.json()['code'], 'token_not_valid')
        self.assertNotIn(ACCESS_COOKIE, resp.cookies)

    def test_cookie_refresh_with_body_token_for_a_deleted_user_is_401(self):
        refresh, _access = _orphaned_tokens()
        resp = self.client.post('/api/v1/auth/token/refresh/', {'refresh': refresh}, format='json')
        self.assertEqual(resp.status_code, 401, resp.content)

    def test_native_refresh_for_a_deleted_user_is_401_not_500(self):
        refresh, _access = _orphaned_tokens()
        resp = self.client.post('/api/v1/auth/native/refresh/', {'refresh': refresh}, format='json')
        self.assertEqual(resp.status_code, 401, resp.content)
        self.assertEqual(resp.json()['code'], 'token_not_valid')

    def test_cookie_refresh_for_a_live_user_still_rotates(self):
        user = User.objects.create_user(username='live@example.com', email='live@example.com', password=PASSWORD)
        self.client.cookies[REFRESH_COOKIE] = str(RefreshToken.for_user(user))
        resp = self.client.post('/api/v1/auth/token/refresh/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn(ACCESS_COOKIE, resp.cookies)
        self.assertIn(REFRESH_COOKIE, resp.cookies)


class StaleCredentialDoesNotBlockSignInTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='back@example.com', email='back@example.com', password=PASSWORD)

    def _login(self, client=None):
        return (client or self.client).post(
            '/api/v1/auth/login/', {'email': 'back@example.com', 'password': PASSWORD}, format='json',
        )

    def test_login_with_a_deleted_users_access_cookie_succeeds(self):
        _refresh, access = _orphaned_tokens()
        self.client.cookies[ACCESS_COOKIE] = access
        resp = self._login()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['user']['email'], 'back@example.com')
        self.assertIn(ACCESS_COOKIE, resp.cookies)

    def test_login_with_a_garbage_access_cookie_succeeds(self):
        self.client.cookies[ACCESS_COOKIE] = 'not-a-jwt'
        self.assertEqual(self._login().status_code, 200)

    def test_login_with_a_stale_bearer_header_succeeds(self):
        _refresh, access = _orphaned_tokens()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        self.assertEqual(self._login().status_code, 200)

    def test_wrong_password_is_still_rejected(self):
        self.client.cookies[ACCESS_COOKIE] = 'not-a-jwt'
        resp = self.client.post(
            '/api/v1/auth/login/', {'email': 'back@example.com', 'password': 'wrong'}, format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_stale_cookie_on_login_is_still_csrf_checked(self):
        """Tolerating the token must not drop CSRF: the cookie path stays CSRF-enforced."""
        client = APIClient(enforce_csrf_checks=True)
        client.cookies[ACCESS_COOKIE] = 'not-a-jwt'
        self.assertEqual(self._login(client).status_code, 403)

    def test_logout_with_a_deleted_users_cookies_clears_them(self):
        refresh, access = _orphaned_tokens()
        self.client.cookies[ACCESS_COOKIE] = access
        self.client.cookies[REFRESH_COOKIE] = refresh
        resp = self.client.post('/api/v1/auth/logout/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.cookies[ACCESS_COOKIE].value, '')

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_VERIFICATION_REQUIRED=True,
    )
    def test_registration_with_a_deleted_users_access_cookie_succeeds(self):
        _refresh, access = _orphaned_tokens()
        self.client.cookies[ACCESS_COOKIE] = access
        resp = self.client.post('/api/v1/auth/registration/', {
            'email': 'fresh@example.com', 'password1': PASSWORD, 'password2': PASSWORD,
            'date_of_birth': '2000-01-01',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(len(mail.outbox), 1)

    def test_other_endpoints_still_reject_a_stale_cookie(self):
        _refresh, access = _orphaned_tokens()
        self.client.cookies[ACCESS_COOKIE] = access
        self.assertEqual(self.client.get('/api/v1/auth/user/').status_code, 401)
