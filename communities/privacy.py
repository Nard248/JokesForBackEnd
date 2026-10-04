"""Who may count toward community numbers, and how person-counts are released.

Two layers on top of the consent population
(``creator_insights.privacy.eligible_analytics_users``: active adults sharing
audience analytics):

**Established accounts (Sybil resistance).** Only accounts that are at least
``COMMUNITIES_ESTABLISHED_ACCOUNT_DAYS`` old (default 7) and have a positive
signal on at least ``COMMUNITIES_ESTABLISHED_MIN_JOKES`` distinct jokes
(default 3) count toward any aggregate: activation, member counts, bridges,
growth and creator reach. "Active" already implies a verified email whenever
``EMAIL_VERIFICATION_REQUIRED`` is on (unverified sign-ups stay inactive), and
Google sign-ups are verified by Google. A brand-new account — or an explicit
join by one — changes only its owner's view. Freshly minted sock accounts
therefore cannot activate a community or move a count for a week, and each
needs real-looking engagement first.

**Stable calibrated noise (differencing).** Every released person-count gets
two-sided geometric (discrete Laplace) noise for sensitivity 1 at
``COMMUNITIES_NOISE_EPSILON`` (default 1.0), then is rounded to the nearest 5
and suppressed when the noisy value is under 5. The noise is a keyed
pseudo-random function of (statistic, subject, UTC day) under an HMAC key
derived from ``SECRET_KEY``: asking again the same day returns the same draw, so
repeated queries cannot be averaged away, and nobody without the key can
predict or subtract it. Callers release from a once-a-day snapshot, so sock
accounts cannot probe the noise within a day either. ``COMMUNITIES_NOISE_EPSILON
= 0`` turns the noise off (tests that assert exact counts only).
"""
import math
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, OuterRef, Subquery
from django.utils import timezone
from django.utils.crypto import salted_hmac

from communities import engine
from communities.models import CommunitySignal
from creator_insights.privacy import eligible_analytics_users

STEP = engine.MINIMUM_MEMBERS
NOISE_SALT = 'communities.privacy.release-noise'


def established_users(now=None):
    """The population every community aggregate is computed over (a lazy queryset)."""
    users = eligible_analytics_users()
    days = settings.COMMUNITIES_ESTABLISHED_ACCOUNT_DAYS
    if days > 0:
        users = users.filter(date_joined__lte=(now or timezone.now()) - timedelta(days=days))
    minimum = settings.COMMUNITIES_ESTABLISHED_MIN_JOKES
    if minimum > 0:
        # Correlated per person (an index-only scan of their own signals) rather than
        # one GROUP BY over the whole table: the planner cannot turn it into a
        # repeated full scan when this queryset is nested in the aggregate's joins.
        distinct_jokes = (CommunitySignal.objects.filter(user=OuterRef('pk')).order_by()
                          .values('user').annotate(n=Count('joke', distinct=True)).values('n'))
        users = users.alias(signal_jokes=Subquery(distinct_jokes)).filter(signal_jokes__gte=minimum)
    return users


def is_established(user):
    return bool(user and user.is_authenticated) and established_users().filter(pk=user.pk).exists()


def _uniforms(stat, key, day):
    message = '|'.join(str(part) for part in (stat, *key, day))
    digest = salted_hmac(NOISE_SALT, message, algorithm='sha256').digest()
    # Two independent uniforms in (0, 1) from disjoint 64-bit halves.
    return [(int.from_bytes(digest[i:i + 8], 'big') + 0.5) / 2 ** 64 for i in (0, 8)]


def noise(stat, key, day):
    """Deterministic two-sided geometric noise: P(k) ∝ exp(-ε·|k|).

    The difference of two geometric variables with ratio ``exp(-ε)`` (each by
    inverse transform from a keyed uniform) is the discrete Laplace mechanism
    for a count with sensitivity 1.
    """
    epsilon = settings.COMMUNITIES_NOISE_EPSILON
    if epsilon <= 0:
        return 0
    first, second = _uniforms(stat, key, day)
    return math.floor(math.log(first) / -epsilon) - math.floor(math.log(second) / -epsilon)


def release(count, stat, *key, day):
    """A public person-count: noised, then ``None`` under 5, else the nearest multiple of 5."""
    noisy = count + noise(stat, key, day)
    if noisy < STEP:
        return None
    return int(noisy / STEP + 0.5) * STEP


def release_delta(delta, stat, *key, day):
    """A signed change (growth): noised and rounded to the nearest multiple of 5, never suppressed."""
    noisy = delta + noise(stat, key, day)
    return int(abs(noisy) / STEP + 0.5) * STEP * (1 if noisy >= 0 else -1)
