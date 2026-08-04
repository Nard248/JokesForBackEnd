"""Signed one-click unsubscribe for digest emails.

Token is a django.core.signing payload over the user id + preference kind
only (no PII in the URL beyond the opaque signed blob). Loading it validates
the signature and age, then the view flips the matching UserProfile flag.
"""
from django.contrib.auth import get_user_model
from django.core import signing

SALT = 'email.unsubscribe'
MAX_AGE_SECONDS = 60 * 60 * 24 * 90  # 90 days — generous, digest links are long-lived in inboxes

# kind -> (UserProfile boolean field, human label for the confirmation copy)
KINDS = {
    'digest': ('email_digest_opt_in', 'the daily joke digest'),
    'milestone': ('creator_milestone_opt_in', 'creator milestone emails'),
}


class InvalidUnsubscribeToken(Exception):
    """Raised for any unusable token: bad signature, expired, unknown kind,
    or a uid that no longer resolves to a user. The view renders one clean
    error page for all of these — no need to distinguish reasons to the user."""


def unsubscribe_token(user, kind):
    """Build the signed token embedded in digest emails for this user+kind."""
    if kind not in KINDS:
        raise ValueError(f'unknown unsubscribe kind: {kind!r}')
    return signing.dumps({'uid': user.pk, 'type': kind}, salt=SALT)


def load_unsubscribe_token(token):
    """Validate + decode a token. Returns {'uid': int, 'type': str}.

    Raises InvalidUnsubscribeToken on any tampering, expiry, or malformed
    payload — callers should render a friendly error, never a 500.
    """
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE_SECONDS)
    except signing.BadSignature as exc:
        raise InvalidUnsubscribeToken('bad signature') from exc
    if not isinstance(data, dict) or 'uid' not in data or data.get('type') not in KINDS:
        raise InvalidUnsubscribeToken('malformed payload')
    return data


def apply_unsubscribe(token):
    """Validate the token and flip the matching flag to False (idempotent).

    Returns the human label for the kind unsubscribed from, for the
    confirmation page copy. Raises InvalidUnsubscribeToken on any failure.
    """
    data = load_unsubscribe_token(token)
    field, label = KINDS[data['type']]

    User = get_user_model()
    user = User.objects.filter(pk=data['uid']).first()
    if user is None:
        raise InvalidUnsubscribeToken('unknown user')

    profile = getattr(user, 'profile', None)
    if profile is None:
        raise InvalidUnsubscribeToken('no profile')

    if getattr(profile, field):
        setattr(profile, field, False)
        profile.save(update_fields=[field])
    return label
