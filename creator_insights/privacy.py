"""The population eligible to contribute to creator analytics, and since when."""
from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef
from django.utils import timezone

from jokes.models import AnalyticsConsentRecord


def eligible_analytics_users():
    return get_user_model().objects.filter(
        is_active=True,
        profile__share_analytics=True,
        profile__date_of_birth__lte=timezone.now().date() - relativedelta(years=18),
    )


def analytics_allowed(user):
    if not user or not user.is_authenticated:
        return False
    return eligible_analytics_users().filter(pk=user.pk).exists()


def since_latest_opt_in(rows, at_field, user_field='user_id'):
    """Keep only ``rows`` recorded at or after their user's latest analytics opt-in.

    Consent is not applied backwards: activity from before someone (re-)enabled
    audience analytics never feeds a creator-visible or community number, and a
    person with no recorded opt-in (an ``AnalyticsConsentRecord`` with
    ``enabled=True``) contributes nothing. This is the time cutoff only; combine
    it with ``eligible_analytics_users()`` for *current* consent, age and
    account state. Creator Insights, the content workbench/export and every
    community aggregate share it.

    Phrased as a semi-join plus an anti-join on ``(user, recorded_at)`` so
    PostgreSQL can evaluate it set-wise (hash (anti-)joins) instead of once per
    row; ``OuterRef`` resolves against ``rows``, so it also nests inside the
    correlated per-joke count subqueries.
    """
    opt_ins = AnalyticsConsentRecord.objects.filter(user=OuterRef(user_field), enabled=True)
    return rows.filter(
        Exists(opt_ins.filter(recorded_at__lte=OuterRef(at_field))),
        ~Exists(opt_ins.filter(recorded_at__gt=OuterRef(at_field))),
    )
