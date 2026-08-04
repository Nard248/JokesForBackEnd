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

Anonymous users have no JokeView row to key off of, so their ledger is a
signed cookie (``jf_anon_reads``) that stands in for that table: same 10/day
cap and midnight-UTC reset as free accounts, but scoped to the browser
instead of an account. It is a deliberately SOFT wall — clearing cookies
evades it — because the goal is conversion (drive registration), not
airtight enforcement. See ``record_anon_read`` / ``_read_anon_ledger`` below.
"""
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from django.conf import settings
from django.core import signing
from django.utils import timezone

from billing import entitlements

# Canonical registry key + safe free-tier fallback for the daily read cap.
FREE_READS_KEY = 'free_joke_reads_per_day'
FREE_READS_DEFAULT = 10

# Anonymous ledger (spec §8): a signed cookie stands in for the JokeView
# table. Deliberately a SOFT wall — clearing cookies evades it; the goal is
# conversion (drive registration), not enforcement.
ANON_COOKIE_NAME = 'jf_anon_reads'
ANON_COOKIE_SALT = 'jokes.paywall.anon'
ANON_COOKIE_MAX_AGE = 60 * 60 * 48   # 2 days; the date check does the real reset


@dataclass(frozen=True)
class PaywallState:
    """Resolved free-read paywall decision for ONE request. Computed once.

    ``limit``/``remaining`` are None for unlimited (paid) tiers. ``over`` is
    always False for paid/unlimited tiers; anonymous requests use the same
    10/day cap as free accounts (via the signed cookie ledger) and so CAN
    be ``over``.
    """
    over: bool
    used: int
    limit: int | None        # None => unlimited (paid tiers)
    remaining: int | None    # None => unlimited
    consumed_ids: frozenset     # joke_ids already opened today (stay unlocked)
    reset_at: str               # ISO 8601 next midnight UTC


def _next_midnight_utc_iso() -> str:
    """ISO 8601 timestamp for the next midnight UTC (when the cap resets)."""
    tomorrow = (timezone.now() + timedelta(days=1)).date()
    return datetime.combine(tomorrow, time.min, tzinfo=UTC).isoformat()


def _unlimited_state() -> PaywallState:
    return PaywallState(
        over=False, used=0, limit=None, remaining=None,
        consumed_ids=frozenset(), reset_at=_next_midnight_utc_iso(),
    )


def _read_anon_ledger(request) -> frozenset:
    """Today's consumed joke_ids from the signed anon cookie. Tampered,
    expired, or stale-dated cookies yield a fresh (empty) ledger."""
    raw = request.COOKIES.get(ANON_COOKIE_NAME)
    if not raw:
        return frozenset()
    try:
        payload = signing.loads(
            raw, salt=ANON_COOKIE_SALT, max_age=ANON_COOKIE_MAX_AGE,
        )
    except signing.BadSignature:
        return frozenset()
    if payload.get('date') != timezone.now().date().isoformat():
        return frozenset()
    ids = payload.get('ids') or []
    return frozenset(
        i for i in ids[:FREE_READS_DEFAULT] if isinstance(i, int)
    )


def record_anon_read(response, request, joke_id) -> None:
    """Append joke_id to the anon ledger and set the re-signed cookie on the
    response. No-op when already consumed or over the cap."""
    consumed = set(_read_anon_ledger(request))
    if joke_id in consumed or len(consumed) >= FREE_READS_DEFAULT:
        return
    consumed.add(joke_id)
    payload = {
        'date': timezone.now().date().isoformat(),
        'ids': sorted(consumed),
    }
    response.set_cookie(
        ANON_COOKIE_NAME,
        signing.dumps(payload, salt=ANON_COOKIE_SALT),
        max_age=ANON_COOKIE_MAX_AGE,
        secure=not settings.DEBUG,
        httponly=True,
        samesite=getattr(settings, 'CSRF_COOKIE_SAMESITE', None) or 'Lax',
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

    if user is None or not getattr(user, 'is_authenticated', False):
        # Anonymous ledger: signed cookie, same 10/day semantics as free
        # accounts (spec §8). Soft wall by design.
        consumed_ids = _read_anon_ledger(request)
        used = len(consumed_ids)
        return PaywallState(
            over=used >= FREE_READS_DEFAULT,
            used=used,
            limit=FREE_READS_DEFAULT,
            remaining=max(0, FREE_READS_DEFAULT - used),
            consumed_ids=consumed_ids,
            reset_at=_next_midnight_utc_iso(),
        )

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
