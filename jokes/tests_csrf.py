"""CSRF enforcement for the cookie-JWT auth (fix/csrf-enforcement).

The only authenticator is dj_rest_auth's ``JWTCookieAuthentication`` and the JWT
cookies are sent ``SameSite=None`` (cross-site SPA). Without CSRF enforcement any
external page could ride a logged-in victim's cookie to issue authenticated,
state-changing requests. Turning on ``REST_AUTH['JWT_AUTH_COOKIE_USE_CSRF']``
makes ``enforce_csrf`` run on exactly the cookie-auth path.

These tests pin the contract:

* GET /api/v1/auth/csrf/ issues the CSRF cookie and returns the token VALUE (the
  cross-origin SPA can't read the cookie via JS, so it needs the value).
* A cookie-authenticated mutation is 403 WITHOUT ``X-CSRFToken`` and succeeds
  WITH a valid token + matching cookie.
* Unauthenticated bootstrap (login) still works with NO token — no JWT cookie is
  present yet, so ``enforce_csrf`` never triggers.
* The Stripe webhook stays CSRF-exempt.

Two things are load-bearing for the setup:

* ``APIClient(enforce_csrf_checks=True)`` — ``enforce_csrf`` runs Django's
  ``CSRFCheck`` directly, and the default test client sets
  ``_dont_enforce_csrf_checks`` which would silently bypass it.
* Real cookie auth (mint a JWT and set the cookie), NOT ``force_authenticate`` —
  ``force_authenticate`` short-circuits the authenticator so ``enforce_csrf``
  would never run. Setting the ``jokes-access-token`` cookie is exactly what a
  real login does, so it drives the identical code path.
"""
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

CSRF_URL = '/api/v1/auth/csrf/'
LOGIN_URL = '/api/v1/auth/login/'
USER_URL = '/api/v1/auth/user/'          # authenticated PATCH → representative mutation
WEBHOOK_URL = '/api/v1/billing/webhook'
ACCESS_COOKIE = 'jokes-access-token'


def _login_via_cookie(client, user):
    """Put a valid JWT access cookie on the client, mirroring a real login.

    This is what makes JWTCookieAuthentication.authenticate() (and therefore
    enforce_csrf) run on subsequent requests.
    """
    access = str(RefreshToken.for_user(user).access_token)
    client.cookies[ACCESS_COOKIE] = access
    return access


class CsrfTokenEndpointTests(APITestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)

    def test_endpoint_returns_token_and_sets_cookie(self):
        resp = self.client.get(CSRF_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertIn('csrfToken', body)
        self.assertTrue(body['csrfToken'], 'csrfToken must be a non-empty value')
        # The double-submit partner cookie must be set on the response.
        self.assertIn('csrftoken', resp.cookies)
        self.assertTrue(resp.cookies['csrftoken'].value)

    def test_endpoint_is_reachable_without_any_token(self):
        # Bootstrap: the SPA calls this before it has a token; must not 403.
        resp = self.client.get(CSRF_URL)
        self.assertEqual(resp.status_code, 200, resp.content)


class CsrfMutationEnforcementTests(APITestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.user = User.objects.create_user(
            username='csrf-user', email='csrf@example.com', password='pw',
        )

    def test_cookie_auth_mutation_without_token_is_forbidden(self):
        _login_via_cookie(self.client, self.user)
        resp = self.client.patch(USER_URL, {'first_name': 'Nope'}, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertIn('CSRF', resp.content.decode())

    def test_cookie_auth_mutation_with_valid_token_succeeds(self):
        # 1) Obtain the CSRF cookie + token value (as the SPA does on init).
        csrf = self.client.get(CSRF_URL).json()['csrfToken']
        # 2) Authenticate via the JWT cookie (as a real login would).
        _login_via_cookie(self.client, self.user)
        # 3) The mutation now carries JWT cookie + CSRF cookie + X-CSRFToken.
        resp = self.client.patch(
            USER_URL, {'first_name': 'Csrf'}, format='json', HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_stale_token_value_is_rejected(self):
        # A cookie present but a garbage header token must still fail closed.
        self.client.get(CSRF_URL)  # sets a real csrf cookie in the jar
        _login_via_cookie(self.client, self.user)
        resp = self.client.patch(
            USER_URL, {'first_name': 'X'}, format='json',
            HTTP_X_CSRFTOKEN='not-a-valid-token',
        )
        self.assertEqual(resp.status_code, 403, resp.content)


class CsrfBootstrapExemptionTests(APITestCase):
    """Unauthenticated / signature-verified endpoints must NOT require a token."""

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)

    def test_login_succeeds_without_csrf_token(self):
        user = User.objects.create_user(
            username='login-user', email='login@example.com', password='StrongPass123!',
        )
        EmailAddress.objects.create(
            user=user, email='login@example.com', primary=True, verified=True,
        )
        resp = self.client.post(
            LOGIN_URL,
            {'email': 'login@example.com', 'password': 'StrongPass123!'},
            format='json',
        )
        # No JWT cookie is present at login time → enforce_csrf never triggers,
        # so login must work with no token (and definitely not 403-CSRF).
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn(ACCESS_COOKIE, resp.cookies)

    def test_stripe_webhook_works_without_csrf_token(self):
        # authentication_classes=[] + csrf_exempt → no CSRF check. The webhook
        # must reach its own handler with no token: either 200 (billing dormant)
        # or 400 (billing enabled → invalid/absent Stripe signature). Both prove
        # the request got PAST auth+CSRF. It must never be a 403 CSRF failure.
        resp = self.client.post(WEBHOOK_URL, {}, format='json')
        self.assertNotEqual(resp.status_code, 403, resp.content)
        self.assertIn(resp.status_code, (200, 400), resp.content)
        self.assertNotIn('CSRF', resp.content.decode())
