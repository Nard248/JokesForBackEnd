"""record_audit() — dual-sink audit helper.

Writes an AuditLog row (try-wrapped so a DB hiccup never breaks the request)
AND always emits a 'jokesfor.audit' structured log line as the fallback.

Import-safe: model import is at module level (fine once the app is installed).
"""
import hashlib
import logging

from JokesForProject.observability.context import get_log_fields
from JokesForProject.observability.redaction import mask_ip

logger = logging.getLogger('jokesfor.audit')


def _hash_email(email: str) -> str:
    """SHA-256 hex digest of the email (full 64 chars for audit storage)."""
    return hashlib.sha256(email.encode('utf-8')).hexdigest()


def _get_client_ip(request) -> str | None:
    """Extract and mask the client IP from XFF or REMOTE_ADDR."""
    if request is None:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    raw_ip = xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')
    if not raw_ip:
        return None
    try:
        return mask_ip(raw_ip)
    except Exception:
        return None


def record_audit(
    request,
    action: str,
    *,
    outcome: str = 'success',
    actor=None,
    target_type: str = '',
    target_id: str = '',
    metadata: dict | None = None,
) -> None:
    """Write one AuditLog row and emit a 'jokesfor.audit' log line.

    The DB write is wrapped in try/except so a transient Neon error never
    breaks the request. The log line is the always-on fallback for
    compliance evidence when the DB is unreachable.

    Args:
        request:      Django HttpRequest (may be None for signal-only callers).
        action:       Short snake_case action name (e.g. 'login', 'account_delete').
        outcome:      'success' | 'failure' | 'denied' (default 'success').
        actor:        User instance whose email will be hashed (not stored raw).
        target_type:  e.g. 'joke', 'user', 'content_report'.
        target_id:    String PK/identifier of the target object.
        metadata:     Non-PII supplementary dict (caller must redact before passing).
    """
    from audit.models import AuditLog

    # Request context from contextvars (set by RequestContextMiddleware)
    log_fields = get_log_fields()
    request_id = log_fields.get('request_id', '')
    if not request_id and request is not None:
        request_id = getattr(request, 'request_id', '')

    ip = _get_client_ip(request)
    ua = ''
    if request is not None:
        raw_ua = request.META.get('HTTP_USER_AGENT', '')
        ua = raw_ua[:256]

    actor_email_hash = ''
    if actor is not None and hasattr(actor, 'email') and actor.email:
        actor_email_hash = _hash_email(actor.email)

    # ── DB write (try-wrapped) ──────────────────────────────────────────────
    try:
        AuditLog.objects.create(
            actor=actor,
            actor_email_hash=actor_email_hash,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else '',
            ip=ip,
            request_id=request_id,
            user_agent=ua,
            outcome=outcome,
            metadata=metadata,
        )
    except Exception as exc:
        logger.exception('audit DB write failed for action=%s: %s', action, exc)

    # ── Structured log line (always emitted) ───────────────────────────────
    logger.info(
        'audit',
        extra={
            'event': 'audit',
            'action': action,
            'outcome': outcome,
            'actor_email_hash': actor_email_hash,
            'target_type': target_type,
            'target_id': str(target_id) if target_id else '',
            'request_id': request_id,
            'ip': ip,
        },
    )
