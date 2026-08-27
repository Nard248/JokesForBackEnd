import hmac

from dj_rest_auth.jwt_auth import set_jwt_cookies
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404, HttpResponse
from django.utils.html import escape
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from audit.services import record_audit

from . import verification
from .digests import run_daily_digests
from .serializers import ResendVerificationSerializer, VerifyEmailSerializer
from .throttles import ResendThrottle
from .unsubscribe import (
    KINDS,
    InvalidUnsubscribeToken,
    apply_unsubscribe,
    load_unsubscribe_token,
)

User = get_user_model()

# Maps verify_code() error strings to user-facing field errors. 'too_many_attempts'
# is handled separately (429), so it is not in this 400-field map.
_VERIFY_ERRORS = {
    'no_active_code': ('code', 'No active code. Request a new one.'),
    'expired': ('code', 'This code has expired. Request a new one.'),
    'incorrect': ('code', 'Incorrect code.'),
}


class VerifyEmailView(APIView):
    """POST /auth/verify-email/ {email, code} -> activate user + set JWT cookies."""

    permission_classes = [AllowAny]

    @extend_schema(
        description=(
            'Exchange the 6-digit emailed code for an activated account. On success the '
            'JWT access/refresh cookies are set on the response (the body carries no '
            'tokens). Anti-enumeration: an unknown email returns the same 400 as a wrong '
            'code. 400 bodies are DRF field-error maps ({"code": ["..."]} / '
            '{"email": ["..."]}) except the already-verified case, which returns {"detail"}.'
        ),
        # Declared inline, not as VerifyEmailSerializer: dj-rest-auth registers a
        # DIFFERENT serializer under the same "VerifyEmail" component name, and
        # two identically-named components produce a silently wrong schema.
        request={'application/json': {
            'type': 'object',
            'properties': {
                'email': {'type': 'string', 'format': 'email'},
                'code': {'type': 'string', 'pattern': r'^\d{6}$'},
            },
            'required': ['email', 'code'],
        }},
        responses={
            200: {'type': 'object', 'properties': {
                'user': {'type': 'object', 'properties': {
                    'id': {'type': 'integer'},
                    'email': {'type': 'string', 'format': 'email'},
                }},
            }},
            400: {'type': 'object', 'properties': {
                'code': {'type': 'array', 'items': {'type': 'string'}},
                'email': {'type': 'array', 'items': {'type': 'string'}},
                'detail': {'type': 'string'},
            }},
            429: {'type': 'object', 'properties': {'detail': {'type': 'string'}},
                  'description': 'Too many wrong-code attempts — request a new code.'},
        },
    )
    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        code = serializer.validated_data['code']

        # Uniform 400 on unknown email (anti-enumeration: same shape as wrong code).
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return Response({'code': ['Incorrect code.']},
                            status=status.HTTP_400_BAD_REQUEST)

        if user.is_active:
            return Response(
                {'detail': 'This email is already verified. Please log in.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ok, err = verification.verify_code(user, code)
        if not ok:
            if err == 'too_many_attempts':
                return Response(
                    {'detail': 'Too many attempts. Request a new code.'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            field, msg = _VERIFY_ERRORS[err]
            return Response({field: [msg]}, status=status.HTTP_400_BAD_REQUEST)

        # User was inactive (active users returned early above); activate now.
        user.is_active = True
        user.save(update_fields=['is_active'])

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        response = Response(
            {'user': {'id': user.id, 'email': user.email}},
            status=status.HTTP_200_OK,
        )
        set_jwt_cookies(response, access, refresh)
        return response


class ResendVerificationView(APIView):
    """POST /auth/resend-verification/ {email} -> new code if the account exists."""

    permission_classes = [AllowAny]
    throttle_classes = [ResendThrottle]

    @extend_schema(
        description=(
            'Re-send a verification code. Anti-enumeration: the 200 body is identical '
            'whether or not the email belongs to an existing unverified account — a code '
            'is only actually sent in the latter case. Rate limited.'
        ),
        request=ResendVerificationSerializer,
        responses={
            200: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            400: {'type': 'object', 'properties': {
                'email': {'type': 'array', 'items': {'type': 'string'}},
            }},
            429: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
    )
    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        # Only send for an existing, not-yet-active account. Always return the
        # same response (anti-enumeration).
        user = User.objects.filter(email__iexact=email, is_active=False).first()
        if user is not None:
            verification.issue_and_send(user)

        return Response(
            {'detail': 'If that email needs verification, a new code has been sent.'},
            status=status.HTTP_200_OK,
        )


def _html_page(heading, message):
    """Tiny standalone confirmation/error page for the unsubscribe link
    (opened directly from an email client, not the SPA — plain HTML, no JS).

    SECURITY: heading/message are interpolated directly into raw HTML with NO
    autoescaping (this is an f-string, not a Django template). Every call site
    in this module passes only hardcoded literal copy — never do so with
    user-supplied or request-derived text (query params, DB values, etc.),
    or this becomes a reflected-XSS sink.
    """
    return f"""<!DOCTYPE html>
<html>
  <body style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#f6f6f8;
               margin:0; padding:24px; display:flex; justify-content:center;">
    <div style="max-width:480px; background:#ffffff; border-radius:12px; padding:32px;
                text-align:center;">
      <div style="font-size:20px; font-weight:700; color:#6A1CF6; padding-bottom:16px;">Jokes For</div>
      <h1 style="font-size:17px; color:#222; margin:0 0 8px;">{heading}</h1>
      <p style="font-size:14px; color:#555; line-height:1.5; margin:0;">{message}</p>
    </div>
  </body>
</html>"""


def _confirm_page(label, token, action_url):
    """Confirm-then-POST page rendered for the unsubscribe GET link.

    SECURITY: unlike `_html_page`'s heading/message (always hardcoded
    literal copy at every call site), `token` here is request-derived --
    an attacker controls the querystring. It's interpolated into an HTML
    attribute, so it MUST be escaped (django.core.signing's own output is
    URL-safe base64 + ':' separators with no HTML metacharacters, but
    escaping doesn't depend on that holding forever, or on this token
    having actually passed signature validation the way it does today).
    `label` is always one of the two hardcoded notifications.unsubscribe.
    KINDS labels, never user input, so no escaping is required there.
    """
    return f"""<!DOCTYPE html>
<html>
  <body style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#f6f6f8;
               margin:0; padding:24px; display:flex; justify-content:center;">
    <div style="max-width:480px; background:#ffffff; border-radius:12px; padding:32px;
                text-align:center;">
      <div style="font-size:20px; font-weight:700; color:#6A1CF6; padding-bottom:16px;">Jokes For</div>
      <h1 style="font-size:17px; color:#222; margin:0 0 8px;">Unsubscribe from {label}?</h1>
      <p style="font-size:14px; color:#555; line-height:1.5; margin:0 0 20px;">
        Click below to confirm. You can always turn this back on later from your account settings.
      </p>
      <form method="POST" action="{escape(action_url)}">
        <input type="hidden" name="token" value="{escape(token)}">
        <button type="submit" style="background:#6A1CF6; color:#fff; border:none; border-radius:8px;
                padding:10px 24px; font-size:14px; font-weight:600; cursor:pointer;">Unsubscribe</button>
      </form>
    </div>
  </body>
</html>"""


class EmailUnsubscribeView(APIView):
    """/api/v1/email/unsubscribe/?token=<signed> — CAN-SPAM one-click
    unsubscribe, no login required.

    GET renders a confirm page and NEVER mutates state: link
    scanners/prefetchers (Outlook SafeLinks, some corporate mail proxies)
    fetch every URL in an email body, and a mutating GET would let a scan
    silently unsubscribe someone who never clicked anything themselves. The
    actual flip only happens on POST -- either the confirm page's own form
    submit (token in the request body), or a mail provider's RFC 8058
    List-Unsubscribe-Post one-click POST straight to this same URL (token
    already in the query string, no page render, no browser involved --
    see notifications.digests._list_unsubscribe_headers). Any bad/tampered/
    expired token gets the same clean friendly error page on either method,
    never a 500.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        description=(
            'NOT part of the client-facing API surface — this is the link target in '
            'outbound emails and renders a standalone HTML page, not JSON. GET never '
            'mutates state: it only renders a confirm form (so link scanners cannot '
            'unsubscribe someone). A bad/expired token renders a friendly error page '
            'with status 400.'
        ),
        parameters=[
            OpenApiParameter(name='token', type=str, required=True, description='Signed unsubscribe token.'),
        ],
        responses={
            (200, 'text/html'): OpenApiTypes.STR,
            (400, 'text/html'): OpenApiTypes.STR,
        },
    )
    def get(self, request):
        token = request.query_params.get('token', '')
        try:
            data = load_unsubscribe_token(token)
        except InvalidUnsubscribeToken:
            return self._error_page()

        _, label = KINDS[data['type']]
        return HttpResponse(
            _confirm_page(label, token, request.path),
            content_type='text/html',
        )

    @extend_schema(
        description=(
            'NOT part of the client-facing API surface. Performs the actual unsubscribe '
            'and renders a standalone HTML confirmation page. Reached either by the '
            'confirm page\'s form submit (token in the body) or by a mail provider\'s '
            'RFC 8058 List-Unsubscribe-Post one-click POST (token in the query string). '
            'A bad/expired token renders the error page with status 400.'
        ),
        parameters=[
            OpenApiParameter(name='token', type=str, description='Signed token (RFC 8058 one-click form).'),
        ],
        request={'application/x-www-form-urlencoded': {
            'type': 'object',
            'properties': {'token': {'type': 'string'}},
        }},
        responses={
            (200, 'text/html'): OpenApiTypes.STR,
            (400, 'text/html'): OpenApiTypes.STR,
        },
    )
    def post(self, request):
        # Confirm-page form submit puts the token in the POST body; a mail
        # provider's RFC 8058 one-click POST instead hits the header URL
        # verbatim, so the token is only in the query string there.
        token = request.data.get('token') or request.query_params.get('token', '')
        try:
            label = apply_unsubscribe(token)
        except InvalidUnsubscribeToken:
            return self._error_page()

        return HttpResponse(
            _html_page(
                "You're unsubscribed",
                f"You won't receive {label} anymore. You can re-enable this "
                "anytime from your account settings.",
            ),
            content_type='text/html',
        )

    @staticmethod
    def _error_page():
        return HttpResponse(
            _html_page(
                "This link isn't working",
                "It may be expired or invalid. You can manage your email "
                "preferences from your account settings instead.",
            ),
            content_type='text/html',
            status=status.HTTP_400_BAD_REQUEST,
        )


class RunDigestsView(APIView):
    """POST — internal Cloud Scheduler trigger for the daily digest batch.

    Not part of the public API: excluded from the OpenAPI schema below, and
    deliberately undocumented here too (see notifications/views.py comments
    on `post()` and Docs/superpowers/specs/2026-07-24-email-digest-design.md
    §Risks for the auth mechanism) — a leaked docstring would defeat the
    "don't advertise this endpoint" design as surely as a leaked schema entry.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(exclude=True)
    def post(self, request):
        # Guarded solely by a shared-secret `X-Digest-Token` header, compared
        # constant-time (hmac.compare_digest — NEVER `==`, which leaks timing
        # on how many leading bytes match) against settings.DIGEST_CRON_TOKEN.
        # Every failure mode -- missing header, wrong token, or an unset/empty
        # server-side secret -- returns the SAME 404, never 401/403: a 401/403
        # would confirm to anyone probing the URL that something real lives
        # there, while 404 is indistinguishable from a path that doesn't
        # exist. Empty DIGEST_CRON_TOKEN means dormant: reject every caller
        # until the owner sets a real secret in the deploy env (same pattern
        # as the Stripe/SafeSearch empty-by-default dormant gates).
        #
        # Both sides are stripped of incidental whitespace (a scheduler
        # header shouldn't fail on that) and encoded to bytes before the
        # compare: hmac.compare_digest requires ASCII-only input when given
        # str objects and raises TypeError otherwise, which would 500 an
        # attacker's non-ASCII probe instead of 404ing it -- encoding first
        # (with surrogateescape on the untrusted side, so even a header that
        # decoded to a lone surrogate can't raise) removes that restriction
        # entirely and keeps every failure path on the same 404.
        supplied = request.META.get('HTTP_X_DIGEST_TOKEN', '').strip()
        expected = settings.DIGEST_CRON_TOKEN

        if not expected or not supplied or not hmac.compare_digest(
            supplied.encode('utf-8', 'surrogateescape'), expected.encode('utf-8')
        ):
            raise Http404()

        summary = run_daily_digests()
        record_audit(
            request, 'digest_run', outcome='success', actor=None,
            target_type='digest_run', metadata=summary,
        )
        return Response(summary, status=status.HTTP_200_OK)
