"""Entitlement resolver — the single choke-point for billing gates.

All feature/limit checks go through here. Reads the user's effective Plan
(active/trialing Subscription's plan, else the is_default FREE plan) and
resolves against the KNOWN_* registry which supplies safe free-tier defaults.

Fail open: users with no Subscription (and anon users) resolve to FREE.
"""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.db.models import F

# Registry: canonical list of gateable capabilities + their FREE defaults.
# Editing this dict is the ONLY place a developer needs to touch to add a gate.
KNOWN_FEATURES: dict[str, bool] = {
    # Creator analytics is free for all creators (matches the Free-plan card +
    # original design — don't lock existing creators out of their own insights).
    'creator_analytics': True,
    'daily_joke_preview': False,
    'mature_content_addon': False,
}

KNOWN_LIMITS: dict[str, int | None] = {
    'mystery_box_rolls_per_day': 3,
    'submissions_per_day': 5,
    'daily_jokes_per_day': 1,
    'daily_joke_history_days': 30,
    # Freemium punchline paywall: DISTINCT joke reveals/day before the punchline
    # is withheld server-side. Free=10; paid tiers set None (unlimited).
    'free_joke_reads_per_day': 10,
}


@dataclass
class QuotaResult:
    allowed: bool
    limit: int | None
    used: int
    remaining: int
    reset_at: str  # ISO date string for next period (e.g. "2026-07-01")


def effective_plan(user):
    """Return the Plan for user's active subscription, else the is_default FREE plan.

    Fails open: if no default plan exists (misconfiguration), returns None and
    callers should fall back to KNOWN_* defaults.
    """
    from billing.models import Plan, Subscription

    if user is None or not getattr(user, 'is_authenticated', False):
        try:
            return Plan.objects.get(is_default=True)
        except Plan.DoesNotExist:
            return None

    try:
        sub = user.subscription
        if sub.is_entitled():
            return sub.plan
        # Canceled/past_due/etc — fall through to free plan
    except Subscription.DoesNotExist:
        pass

    try:
        return Plan.objects.get(is_default=True)
    except Plan.DoesNotExist:
        return None


def has_feature(user, key: str) -> bool:
    """Return True if user's effective plan has the named feature enabled."""
    plan = effective_plan(user)
    free_default = KNOWN_FEATURES.get(key, False)
    if plan is None:
        return free_default
    return plan.features.get(key, free_default)


def get_limit(user, key: str, default: int | None = None) -> int | None:
    """Return the numeric limit for user's effective plan.

    None means unlimited. ``default`` overrides the KNOWN_LIMITS registry
    value when provided (used so callers can pass model constants as fallback).
    """
    plan = effective_plan(user)
    registry_default = KNOWN_LIMITS.get(key, default)
    if plan is None:
        return registry_default if default is None else default
    return plan.limits.get(key, registry_default if default is None else default)


def _period_key(period: str) -> str:
    """Derive the current period bucket string from now().

    period='day'   -> 'YYYY-MM-DD'
    period='month' -> 'YYYY-MM'
    """
    today = date.today()
    if period == 'day':
        return today.strftime('%Y-%m-%d')
    return today.strftime('%Y-%m')


def _reset_at(period: str) -> str:
    """Return ISO date string for start of next period."""
    today = date.today()
    if period == 'day':
        from datetime import timedelta
        return (today + timedelta(days=1)).isoformat()
    # next month
    if today.month == 12:
        return date(today.year + 1, 1, 1).isoformat()
    return date(today.year, today.month + 1, 1).isoformat()


def get_usage(user, key: str, period: str = 'day') -> int:
    """Return current usage count from UsageCounter for the current period."""
    from billing.models import UsageCounter

    if user is None or not getattr(user, 'is_authenticated', False):
        return 0
    pk = _period_key(period)
    try:
        return UsageCounter.objects.get(user=user, key=key, period_key=pk).count
    except UsageCounter.DoesNotExist:
        return 0


@transaction.atomic
def check_and_consume_quota(
    user,
    key: str,
    period: str = 'day',
    amount: int = 1,
) -> QuotaResult:
    """Atomically check and consume one unit of quota.

    Uses get_or_create on the current period_key for lazy period reset —
    no cron required. On period rollover, the old row is simply ignored and a
    new row starts at 0.

    Returns QuotaResult(allowed=False) without incrementing if over limit.
    """
    from billing.models import UsageCounter

    limit = get_limit(user, key)
    pk = _period_key(period)
    reset = _reset_at(period)

    if not getattr(user, 'is_authenticated', False):
        return QuotaResult(allowed=False, limit=limit, used=0, remaining=0, reset_at=reset)

    if limit is None:
        # Unlimited
        counter, _ = UsageCounter.objects.select_for_update().get_or_create(
            user=user, key=key, period_key=pk
        )
        counter.count = F('count') + amount
        counter.save(update_fields=['count'])
        counter.refresh_from_db()
        return QuotaResult(allowed=True, limit=None, used=counter.count, remaining=-1, reset_at=reset)

    counter, _ = UsageCounter.objects.select_for_update().get_or_create(
        user=user, key=key, period_key=pk
    )

    if counter.count + amount > limit:
        return QuotaResult(
            allowed=False, limit=limit, used=counter.count,
            remaining=max(0, limit - counter.count), reset_at=reset,
        )

    counter.count = F('count') + amount
    counter.save(update_fields=['count'])
    counter.refresh_from_db()

    return QuotaResult(
        allowed=True, limit=limit, used=counter.count,
        remaining=max(0, limit - counter.count), reset_at=reset,
    )


def check_quota_by_count(
    user,
    key: str,
    count_callable: Callable[[], int],
    period: str = 'day',
) -> QuotaResult:
    """Check quota against a live row count (no UsageCounter write).

    For row-derivable caps (e.g. MysteryBoxRoll.objects.filter(...).count()).
    No write — purely informational / gate check.
    """
    limit = get_limit(user, key)
    reset = _reset_at(period)
    used = count_callable()

    if limit is None:
        return QuotaResult(allowed=True, limit=None, used=used, remaining=-1, reset_at=reset)

    allowed = used < limit
    return QuotaResult(
        allowed=allowed, limit=limit, used=used,
        remaining=max(0, limit - used), reset_at=reset,
    )
