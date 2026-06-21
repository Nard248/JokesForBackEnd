"""Moderation visibility enforcement (Wave 2).

Two concerns, two scopes:
  * Takedowns (Joke.is_removed) are viewer-independent — gone for everyone.
  * Blocks are per-viewer and symmetric — if A blocks B, neither sees the
    other's jokes/profile.

Applied per read path (consistent with the content-tier lock `allowed_tiers`),
NOT via a manager-wide get_queryset override (too broad to retrofit safely).
"""
from django.db.models import Q

from jokes.models import UserBlock


def is_blocked_between(user_a, user_b):
    """True if either user has blocked the other (symmetric)."""
    return UserBlock.objects.filter(
        Q(blocker=user_a, blocked=user_b) | Q(blocker=user_b, blocked=user_a)
    ).exists()


def hidden_user_ids(user):
    """User ids the viewer must not see content from: anyone on either side of a
    block with `user`. Empty set for anonymous/None users."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return set()
    blocked = UserBlock.objects.filter(blocker=user).values_list('blocked_id', flat=True)
    blocked_by = UserBlock.objects.filter(blocked=user).values_list('blocker_id', flat=True)
    return set(blocked) | set(blocked_by)


def visible_jokes(qs, request):
    """Apply moderation visibility to a Joke queryset for the given request:
    drop removed jokes, and (for authenticated viewers) jokes by blocked users."""
    qs = qs.filter(is_removed=False)
    user = getattr(request, 'user', None)
    hidden = hidden_user_ids(user)
    if hidden:
        qs = qs.exclude(creator_id__in=hidden)
    return qs
