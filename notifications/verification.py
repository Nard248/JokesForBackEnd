"""6-digit registration code lifecycle: issue, verify, invalidate.

The code is short-lived and attempt-limited, so we use a fast constant-time
SHA-256 digest (not a slow KDF). Security comes from expiry + attempt cap +
resend throttling, not from hash slowness. Plaintext is never stored.
"""
import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import EmailVerification
from .service import send_email

_metrics = logging.getLogger('jokesfor.metrics')


def _hash(code):
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


def _generate_code():
    # 6 digits, zero-padded, cryptographically random
    return f'{secrets.randbelow(1_000_000):06d}'


def invalidate_codes(user):
    """Mark all of the user's unconsumed codes as consumed (dead)."""
    EmailVerification.objects.filter(
        user=user, consumed_at__isnull=True
    ).update(consumed_at=timezone.now())


def issue_code(user):
    """Invalidate prior codes, create a fresh one, return the plaintext code."""
    invalidate_codes(user)
    code = _generate_code()
    ttl = settings.EMAIL_VERIFICATION_CODE_TTL_MINUTES
    EmailVerification.objects.create(
        user=user,
        code_hash=_hash(code),
        expires_at=timezone.now() + timedelta(minutes=ttl),
    )
    return code


def issue_and_send(user):
    """Issue a code and email it. Returns the EmailMessageLog row."""
    code = issue_code(user)
    return send_email(
        user.email, 'verification_code',
        {'code': code, 'ttl_minutes': settings.EMAIL_VERIFICATION_CODE_TTL_MINUTES},
        user=user,
    )


def verify_code(user, code):
    """Validate a submitted code.

    Returns (ok: bool, error: str|None). Error is one of:
    'no_active_code', 'expired', 'too_many_attempts', 'incorrect'.
    """
    ev = (
        EmailVerification.objects
        .filter(user=user, consumed_at__isnull=True)
        .order_by('-created_at')
        .first()
    )
    if ev is None:
        _metrics.info('metric', extra={'event': 'verification_attempt', 'result': 'no_active_code'})
        return False, 'no_active_code'
    if ev.is_expired:
        _metrics.info('metric', extra={'event': 'verification_attempt', 'result': 'expired'})
        return False, 'expired'
    # MAX_ATTEMPTS wrong guesses are allowed; the next call is blocked.
    # e.g. MAX=5 -> 5 incorrect tries permitted, the 6th returns too_many_attempts.
    if ev.attempts >= settings.EMAIL_VERIFICATION_MAX_ATTEMPTS:
        _metrics.info('metric', extra={'event': 'verification_attempt', 'result': 'too_many_attempts'})
        return False, 'too_many_attempts'

    if not hmac.compare_digest(ev.code_hash, _hash(code)):
        ev.attempts += 1
        ev.save(update_fields=['attempts'])
        _metrics.info('metric', extra={'event': 'verification_attempt', 'result': 'incorrect'})
        return False, 'incorrect'

    # Atomically consume: a conditional UPDATE so two concurrent verifies of the
    # same code can't both succeed (only the row still unconsumed flips). If the
    # update affects 0 rows, another request already consumed it.
    consumed = EmailVerification.objects.filter(
        pk=ev.pk, consumed_at__isnull=True
    ).update(consumed_at=timezone.now())
    if not consumed:
        _metrics.info('metric', extra={'event': 'verification_attempt', 'result': 'no_active_code'})
        return False, 'no_active_code'
    _metrics.info('metric', extra={'event': 'verification_attempt', 'result': 'ok'})
    return True, None
