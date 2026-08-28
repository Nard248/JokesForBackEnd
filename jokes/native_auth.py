"""Token endpoints for native clients (iOS).

The web client is cookie-authenticated. ``JWT_AUTH_HTTPONLY=True`` deliberately
blanks ``refresh`` in response bodies so an XSS cannot lift a long-lived
credential — the rotating token exists only in the ``jokes-refresh-token``
Set-Cookie header. That is the right posture for a browser and nothing here
changes it.

A native app has no such threat model and no way to use that contract. With
``ROTATE_REFRESH_TOKENS`` + ``BLACKLIST_AFTER_ROTATION``, a body-reading client
gets ``refresh: ""`` at login and refreshes exactly once before every call 401s.

These two endpoints serve that client instead: tokens in the body, **no cookies
set**, and a refresh lifetime measured in weeks rather than a day.

Three deliberate choices
------------------------
**Validation is delegated, not reimplemented.** Login reuses dj-rest-auth's
configured ``LoginSerializer``, so the email lookup, the password check and the
``is_active`` gate (which *is* the email-verification gate) behave exactly as
they do on the web path. A second, subtly different login implementation is how
an auth bypass gets written.

**Only the refresh lifetime is extended.** The access token stays at 15 minutes.
Widening that would enlarge the blast radius of a leaked token for no gain; the
retention problem is entirely about the refresh window.

**Rotation and blacklisting still apply.** A 30-day token makes replay
protection more important, not less, so the rotated token is blacklisted exactly
as on the web path — the native client simply receives its replacement.
"""
from datetime import timedelta

from dj_rest_auth.app_settings import api_settings as rest_auth_settings
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenViewBase

#: How long a native refresh token lives. The web default is 1 day, which in a
#: daily-ritual product logs out anyone who skips a single day — a retention
#: bug wearing a security costume. Overridable so it can be tightened without a
#: code change if abuse ever warrants it.
NATIVE_REFRESH_LIFETIME = timedelta(
    days=int(getattr(settings, 'NATIVE_REFRESH_TOKEN_DAYS', 30)),
)


def issue_native_tokens(user):
    """Mint an access/refresh pair carrying the extended native refresh window.

    ``set_exp`` is applied to the refresh token *before* ``access_token`` is
    read so both are derived from the same, already-adjusted payload.
    """
    refresh = RefreshToken.for_user(user)
    refresh.set_exp(lifetime=NATIVE_REFRESH_LIFETIME)
    access = refresh.access_token
    return {
        'access': str(access),
        'refresh': str(refresh),
        'access_expires_in': int(
            settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds()
        ),
        'refresh_expires_in': int(NATIVE_REFRESH_LIFETIME.total_seconds()),
    }


class NativeTokenPairSerializer(serializers.Serializer):
    """Response shape. Declared so the endpoints appear in the OpenAPI schema
    rather than tripping drf-spectacular's `unable to guess serializer`."""

    access = serializers.CharField()
    refresh = serializers.CharField()
    access_expires_in = serializers.IntegerField()
    refresh_expires_in = serializers.IntegerField()


class NativeLoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(style={'input_type': 'password'})


class NativeLoginView(APIView):
    """``POST /api/v1/auth/native/login/`` — email + password, tokens in the body.

    Sets no cookies. A native client that silently acquires a cookie jar is the
    exact failure this endpoint exists to prevent: one request carrying the
    cookie without an ``Authorization`` header lands on the CSRF-enforced path
    and 403s every mutation, intermittently and miserably.
    """

    permission_classes = [AllowAny]
    authentication_classes = ()
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'native_login'
    serializer_class = NativeLoginRequestSerializer

    @extend_schema(
        request=NativeLoginRequestSerializer,
        responses={200: NativeTokenPairSerializer},
        summary='Native login (tokens in body, no cookies)',
    )
    def post(self, request):
        # Delegate to the same serializer the web login uses so the is_active
        # verification gate and the email lookup cannot drift between paths.
        serializer = rest_auth_settings.LOGIN_SERIALIZER(
            data=request.data, context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        payload = issue_native_tokens(user)
        payload['user'] = rest_auth_settings.USER_DETAILS_SERIALIZER(
            user, context={'request': request},
        ).data
        return Response(payload, status=status.HTTP_200_OK)


class NativeTokenRefreshSerializer(TokenRefreshSerializer):
    """simplejwt's refresh, with the native lifetime re-applied on rotation.

    Without the ``set_exp`` below, the rotated token would silently fall back to
    the global 1-day ``REFRESH_TOKEN_LIFETIME`` — so the 30-day window would
    evaporate on the first refresh instead of the thirtieth day, which is the
    kind of bug that only shows up in retention numbers.
    """

    def validate(self, attrs):
        data = super().validate(attrs)

        if 'refresh' in data:
            rotated = RefreshToken(data['refresh'])
            rotated.set_exp(lifetime=NATIVE_REFRESH_LIFETIME)
            data['refresh'] = str(rotated)

        data['access_expires_in'] = int(
            settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds()
        )
        data['refresh_expires_in'] = int(NATIVE_REFRESH_LIFETIME.total_seconds())
        return data


class NativeTokenRefreshView(TokenViewBase):
    """``POST /api/v1/auth/native/refresh/`` — rotate, and return both tokens.

    dj-rest-auth's cookie-aware refresh view deletes ``refresh`` from the
    response body by design. This one does not, which is the entire point.
    Rotation and blacklisting are unchanged: replaying a spent token still 401s.
    """

    permission_classes = [AllowAny]
    authentication_classes = ()
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'native_refresh'
    serializer_class = NativeTokenRefreshSerializer
    _serializer_class = 'jokes.native_auth.NativeTokenRefreshSerializer'

    @extend_schema(
        responses={200: NativeTokenPairSerializer},
        summary='Native token refresh (rotated token returned in body)',
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            # A spent, malformed or wrong-type token is an authentication
            # failure (401), not a validation error (400).
            raise InvalidToken(exc.args[0]) from exc
        return Response(serializer.validated_data, status=status.HTTP_200_OK)
