"""Compatibility contract for permanently free joke consumption.

Existing clients still receive is_locked/daily-read fields. They always resolve
to unlimited regardless of authentication, plan JSON, or legacy cookies. Reading
history remains in JokeView; content safety is enforced by jokes.serving and
jokes.moderation, independently of this former purchase gate.
"""
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from django.utils import timezone

# Retained names for callers and tests migrating from the retired cookie ledger.
# These constants no longer control content access or cause cookie writes.
FREE_READS_DEFAULT = 10
ANON_COOKIE_NAME = 'jf_anon_reads'


@dataclass(frozen=True)
class PaywallState:
    """Legacy purchase-quota shape; limit/remaining=None means unlimited."""
    over: bool
    used: int
    limit: int | None
    remaining: int | None
    consumed_ids: frozenset
    reset_at: str


def _next_midnight_utc_iso() -> str:
    tomorrow = (timezone.now() + timedelta(days=1)).date()
    return datetime.combine(tomorrow, time.min, tzinfo=UTC).isoformat()


def record_anon_read(response, request, joke_id) -> None:
    """Compatibility no-op: anonymous reading never writes a quota cookie."""


def paywall_state(request) -> PaywallState:
    """Always unlimited; ``used`` retains the legacy unlimited-plan value 0.

    This field is a retired quota counter, not an activity-history metric.
    Do not query billing or read the old anonymous ledger here.
    """
    return PaywallState(
        over=False, used=0, limit=None, remaining=None,
        consumed_ids=frozenset(), reset_at=_next_midnight_utc_iso(),
    )
