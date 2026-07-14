"""Freemium daily-read paywall — the single per-request choke-point.

Mirrors ``jokes/serving.allowed_tiers``: resolve the paywall decision ONCE per
request, stash it in the serializer context, and let ``JokeSerializer`` read it
uniformly across every serving path (list/retrieve/trending/random/pack/
collection). Field-stripping happens only in the serializer.

Product spec:
  - Free tier = ``free_joke_reads_per_day`` DISTINCT joke reveals per day
    (default 10). Paid tiers = unlimited (limit resolves to None).
  - What locks past the cap: the PUNCHLINE (server-side), not the teaser.
  - The per-user/per-day ledger IS the existing ``JokeView`` table: one distinct
    ``joke_id`` per (user, ``viewed_date``) == one consumed read.
  - Reset boundary: midnight UTC (``JokeView.viewed_date`` is UTC;
    settings.TIME_ZONE == 'UTC').

Anonymous users are OUT OF SCOPE: they have no JokeView ledger, so this helper
returns a never-locked state and leaves anon serving unchanged. See the TODO.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from typing import Optional

from django.utils import timezone

from billing import entitlements

# Canonical registry key + safe free-tier fallback for the daily read cap.
FREE_READS_KEY = 'free_joke_reads_per_day'
FREE_READS_DEFAULT = 10


@dataclass(frozen=True)
class PaywallState:
    """Resolved free-read paywall decision for ONE request. Computed once.

    ``limit``/``remaining`` are None for unlimited (paid) tiers. ``over`` is
    always False for paid/unlimited and for anonymous requests.
    """
    over: bool
    used: int
    limit: Optional[int]        # None => unlimited (paid tiers)
    remaining: Optional[int]    # None => unlimited
    consumed_ids: frozenset     # joke_ids already opened today (stay unlocked)
    reset_at: str               # ISO 8601 next midnight UTC


def _next_midnight_utc_iso() -> str:
    """ISO 8601 timestamp for the next midnight UTC (when the cap resets)."""
    tomorrow = (timezone.now() + timedelta(days=1)).date()
    return datetime.combine(tomorrow, time.min, tzinfo=dt_timezone.utc).isoformat()


def _unlimited_state() -> PaywallState:
    return PaywallState(
        over=False, used=0, limit=None, remaining=None,
        consumed_ids=frozenset(), reset_at=_next_midnight_utc_iso(),
    )


def paywall_state(request) -> PaywallState:
    """Resolve the free-read paywall state for this request. Compute ONCE.

    Authenticated FREE user (limit not None):
      used         = COUNT(DISTINCT joke_id) in JokeView for (user, today-UTC)
      consumed_ids = those joke_ids (already-opened jokes stay unlocked)
      over         = used >= limit
    Paid / unlimited user (limit None): never over; the ledger is not queried.
    """
    user = getattr(request, 'user', None)

    # TODO(paywall): anonymous users have no per-user JokeView ledger, so they
    # are never locked here. Decide anon policy later (session/IP cap or a hard
    # gate) — until then anon serving is unchanged.
    if user is None or not getattr(user, 'is_authenticated', False):
        return _unlimited_state()

    limit = entitlements.get_limit(user, FREE_READS_KEY, FREE_READS_DEFAULT)
    if limit is None:
        return _unlimited_state()

    from jokes.models import JokeView

    today = timezone.now().date()
    consumed_ids = frozenset(
        JokeView.objects.filter(user=user, viewed_date=today)
        .values_list('joke_id', flat=True)
        .distinct()
    )
    used = len(consumed_ids)
    return PaywallState(
        over=used >= limit,
        used=used,
        limit=limit,
        remaining=max(0, limit - used),
        consumed_ids=consumed_ids,
        reset_at=_next_midnight_utc_iso(),
    )
