"""Django auth signal receivers for audit logging.

Anti-enumeration: login_failed records only the hashed attempted identifier
and NEVER queries the user table to determine whether the email exists.
"""
import hashlib
import logging

logger = logging.getLogger('jokesfor.audit')


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def on_user_logged_in(sender, request, user, **kwargs):
    from audit.services import record_audit
    record_audit(request, 'login', outcome='success', actor=user)


def on_user_logged_out(sender, request, user, **kwargs):
    from audit.services import record_audit
    record_audit(request, 'logout', outcome='success', actor=user)


def on_user_login_failed(sender, credentials, request, **kwargs):
    """Record a login failure without leaking whether the email exists.

    'request' may be None (some callers of the signal don't pass one).
    We never query the user table here to avoid being an enumeration oracle.
    """
    from audit.services import record_audit

    # Hash any attempted identifier from credentials (email/username)
    identifier = (
        credentials.get('email')
        or credentials.get('username')
        or ''
    )
    hashed = _hash_identifier(identifier) if identifier else ''

    # Metadata carries ONLY the hashed identifier — no 'user_exists' flag.
    record_audit(
        request,
        'login',
        outcome='failure',
        actor=None,
        metadata={'attempted_identifier_hash': hashed} if hashed else None,
    )


def register_receivers():
    from django.contrib.auth.signals import (
        user_logged_in,
        user_logged_out,
        user_login_failed,
    )
    user_logged_in.connect(on_user_logged_in, dispatch_uid='audit_login')
    user_logged_out.connect(on_user_logged_out, dispatch_uid='audit_logout')
    user_login_failed.connect(on_user_login_failed, dispatch_uid='audit_login_failed')
