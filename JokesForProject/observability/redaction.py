"""PII and secret masking helpers for structured logs and Sentry events.

Used by the access-log middleware and Sentry before_send to ensure that
passwords, JWT cookies, verification codes, and other secrets never appear
in log output or error-tracking payloads.
"""
import hashlib

# Keys whose values must always be replaced with '[REDACTED]'.
# Case-insensitive matching applied in redact_mapping().
_DENYLIST: frozenset = frozenset({
    'password',
    'password1',
    'password2',
    'token',
    'access',
    'refresh',
    'authorization',
    'secret',
    'api_key',
    'resend_api_key',
    'code',
    'code_hash',
    'set-cookie',
    'cookie',
    # JWT cookie names used by this app (REST_AUTH settings)
    'jokes-access-token',
    'jokes-refresh-token',
    # Email-Digest-Wave internal trigger shared secret (notifications.views.
    # RunDigestsView) -- both header-name spellings, since Sentry's request
    # headers dict uses the hyphenated HTTP form while other consumers may
    # key off the underscored META-derived form.
    'x-digest-token',
    'x_digest_token',
})

_REDACTED = '[REDACTED]'


def mask_email(email: str) -> str:
    """Return a masked version: first char of local part + *** + @domain.

    Example: 'alice@example.com' -> 'a***@example.com'
    """
    try:
        local, domain = email.split('@', 1)
        return f'{local[0]}***@{domain}'
    except (ValueError, IndexError):
        return '***'


def hash_email(email: str) -> str:
    """Return the first 12 hex chars of the SHA-256 digest of the email.

    Used for audit-log correlation without storing reversible PII.
    Consistent with the SHA-256 convention in notifications/verification.py.
    """
    return hashlib.sha256(email.encode('utf-8')).hexdigest()[:12]


def mask_ip(ip: str) -> str:
    """Return a GDPR-safe coarse IP: zero the last IPv4 octet / truncate IPv6 to /48."""
    ip = (ip or '').strip()
    if ':' in ip:
        # IPv6 — keep the first 3 hextets (24 bits of /48), discard the rest
        parts = ip.split(':')
        return ':'.join(parts[:3]) + '::'
    parts = ip.split('.')
    if len(parts) == 4:
        return f'{parts[0]}.{parts[1]}.{parts[2]}.0'
    return ip


def redact_mapping(obj, _seen: set | None = None):
    """Recursively replace denylist-keyed values with '[REDACTED]'.

    Handles nested dicts and lists. Returns a new structure; does not mutate
    the input. Keys are matched case-insensitively.
    """
    if _seen is None:
        _seen = set()

    if isinstance(obj, dict):
        obj_id = id(obj)
        if obj_id in _seen:
            return obj
        _seen.add(obj_id)
        return {
            k: _REDACTED if k.lower() in _DENYLIST else redact_mapping(v, _seen)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_mapping(item, _seen) for item in obj]
    return obj
