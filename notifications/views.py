import hmac

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404, HttpResponse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from dj_rest_auth.jwt_auth import set_jwt_cookies

from audit.services import record_audit

from . import verification
from .digests import run_daily_digests
from .serializers import VerifyEmailSerializer, ResendVerificationSerializer
from .throttles import ResendThrottle
from .unsubscribe import apply_unsubscribe, InvalidUnsubscribeToken

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


class EmailUnsubscribeView(APIView):
    """GET /api/v1/email/unsubscribe/?token=<signed> — one-click CAN-SPAM
    unsubscribe, no login required. Flips the matching UserProfile flag and
    renders a tiny confirmation page. Any bad/tampered/expired token gets a
    clean friendly error page, never a 500."""

    permission_classes = [AllowAny]

    def get(self, request):
        token = request.query_params.get('token', '')
        try:
            label = apply_unsubscribe(token)
        except InvalidUnsubscribeToken:
            return HttpResponse(
                _html_page(
                    "This link isn't working",
                    "It may be expired or invalid. You can manage your email "
                    "preferences from your account settings instead.",
                ),
                content_type='text/html',
                status=status.HTTP_400_BAD_REQUEST,
            )

        return HttpResponse(
            _html_page(
                "You're unsubscribed",
                f"You won't receive {label} anymore. You can re-enable this "
                "anytime from your account settings.",
            ),
            content_type='text/html',
        )


class RunDigestsView(APIView):
    """POST /api/v1/internal/run-digests/ — Cloud Scheduler trigger for the
    daily digest + creator milestone batch (see notifications.digests).

    NOT a user endpoint: no session/JWT auth at all, and no permission check
    beyond the shared-secret header below. Guarded entirely by `X-Digest-Token`
    compared (constant-time, via hmac.compare_digest — NEVER `==`, which leaks
    timing on how many leading bytes match) against settings.DIGEST_CRON_TOKEN.

    Every failure mode — missing header, wrong token, or an unset/empty
    server-side secret — returns the SAME 404, never 401/403. A 401/403 would
    confirm to anyone probing the URL that something real lives there; 404
    makes it indistinguishable from a path that doesn't exist (see spec
    §Risks). An empty DIGEST_CRON_TOKEN means the endpoint is dormant for
    every caller until the owner sets a real secret in the deploy env — same
    pattern as the Stripe/SafeSearch empty-by-default dormant gates.

    Throttle-exempt (`throttle_classes = []`): the token + 404 shape IS the
    guard, and a legitimate scheduler shouldn't be rate-limited by its own
    caller. An unauthenticated flood still only costs one cheap constant-time
    compare + a 404 per request — no DB/email work happens before the token
    check.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request):
        supplied = request.META.get('HTTP_X_DIGEST_TOKEN', '')
        expected = settings.DIGEST_CRON_TOKEN

        # Reject up front (no compare at all) when the server-side secret is
        # unset/empty — dormant by default. Guards against hmac.compare_digest
        # trivially "matching" an equally-empty supplied header, which would
        # otherwise let an unconfigured deploy accept every caller.
        if not expected or not supplied or not hmac.compare_digest(supplied, expected):
            raise Http404()

        summary = run_daily_digests()
        record_audit(
            request, 'digest_run', outcome='success', actor=None,
            target_type='digest_run', metadata=summary,
        )
        return Response(summary, status=status.HTTP_200_OK)
