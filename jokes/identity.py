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
    """Public @handle: chosen handle → opaque @user<pk>. Never email."""
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
