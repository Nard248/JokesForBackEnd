"""Credential edge cases on the web (cookie) auth endpoints.

Two failures this module closes:

**Refreshing a token whose user no longer exists returned 500.** simplejwt's
``TokenRefreshSerializer.validate`` looks the user up with ``.objects.get()``
and lets ``DoesNotExist`` escape. A deleted account (GDPR delete, admin
cleanup, an E2E database reset) still holding a signed, unexpired refresh
token is an authentication failure, so it answers 401 ``token_not_valid``
like any other unusable token. :class:`OrphanSafeRefreshMixin` is shared with
the native refresh serializer (``jokes.native_auth``).

**A stale credential blocked the endpoints used to replace it.** dj-rest-auth's
login/logout and our registration / Google login views run the default
``JWTCookieAuthentication``. With an access cookie that is expired, malformed
or belongs to a deleted user, authentication raises before the view runs, so
``POST /auth/login/`` answered 401 and the browser could never sign in again
until the cookie aged out. :class:`StaleTolerantJWTCookieAuthentication` treats
such a credential as anonymous on those endpoints only. CSRF enforcement is
untouched: a request that carries the JWT cookie is still CSRF-checked before
the token is examined, and that ``PermissionDenied`` is not swallowed.
"""
from dj_rest_auth.jwt_auth import (
    CookieTokenRefreshSerializer,
    JWTCookieAuthentication,
    get_refresh_view,
)
from dj_rest_auth.views import LoginView, LogoutView
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken


class OrphanSafeRefreshMixin:
    """Turn simplejwt's unhandled ``User.DoesNotExist`` into a 401."""

    def validate(self, attrs):
        try:
            return super().validate(attrs)
        except ObjectDoesNotExist as exc:
            raise InvalidToken('User not found') from exc


class OrphanSafeCookieTokenRefreshSerializer(OrphanSafeRefreshMixin, CookieTokenRefreshSerializer):
    pass


class CookieTokenRefreshView(get_refresh_view()):
    """``POST /api/v1/auth/token/refresh/`` — dj-rest-auth's cookie refresh, 401 for a deleted user."""

    serializer_class = OrphanSafeCookieTokenRefreshSerializer


class StaleTolerantJWTCookieAuthentication(JWTCookieAuthentication):
    """An unusable JWT is anonymous here instead of a 401 (CSRF failures still raise)."""

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except AuthenticationFailed:
            # InvalidToken (expired / malformed / blacklisted) and
            # user_not_found / user_inactive are all AuthenticationFailed.
            return None


#: For views whose job is to issue or clear credentials.
CREDENTIAL_ENDPOINT_AUTHENTICATION = [StaleTolerantJWTCookieAuthentication]


class StaleTolerantLoginView(LoginView):
    authentication_classes = CREDENTIAL_ENDPOINT_AUTHENTICATION


class StaleTolerantLogoutView(LogoutView):
    authentication_classes = CREDENTIAL_ENDPOINT_AUTHENTICATION
