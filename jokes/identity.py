"""Public identity helpers — the single source of truth for how a user is shown
publicly (creator profiles, follower lists, etc.).

Rule: NEVER derive a public identifier from the email address (PII / enumeration).
Use the user-chosen UserProfile.display_name / handle when set, otherwise fall
back to an opaque, non-reversible id (user_<pk>).
"""
import re

HANDLE_RE = re.compile(r'^[a-z0-9_]{3,30}$')


def _profile(user):
    """Safely fetch the related UserProfile (signal auto-creates it; be defensive)."""
    try:
        return user.profile
    except Exception:
        return None


def public_display_name(user):
    """Shown name: chosen display_name → real name → opaque user_<pk>. Never email."""
    profile = _profile(user)
    if profile and profile.display_name:
        return profile.display_name
    full = f'{user.first_name} {user.last_name}'.strip()
    return full or f'user_{user.pk}'


def public_handle(user):
    """Public @handle: chosen handle → opaque @user<pk>. Never email.

    Deliberately does NOT fall back to ``auth_user.username``. That looks
    tempting — the SPA used to write a user's chosen handle there — but it is
    wrong on three counts:

    * ``username`` is not a handle. Registration sets it to the full email
      address (``JokesForProject/serializers.py``), and allauth's social signup
      sets it to the email's LOCAL PART, which passes ``is_valid_handle``. So
      publishing it would derive a public identifier from an email — exactly
      what this module exists to prevent.
    * It is not unique in the handle namespace. The taken-check when setting a
      handle only queries ``UserProfile.handle``, so a username-derived handle
      is invisible to it and two accounts can render the same ``@handle``.
    * It was never moderated or validated as a public name.

    A handle the user picks belongs in ``UserProfile.handle``, set through
    ``PATCH /users/me/profile/``, which normalizes it and enforces uniqueness.
    """
    profile = _profile(user)
    if profile and profile.handle:
        return f'@{profile.handle}'
    return f'@user{user.pk}'


def normalize_handle(value):
    """Lower-case + strip a leading '@'. Returns '' for falsy input."""
    if not value:
        return ''
    return value.strip().lstrip('@').lower()


def is_valid_handle(value):
    """3–30 chars, lowercase alphanumeric + underscore (already normalized)."""
    return bool(HANDLE_RE.match(value or ''))
