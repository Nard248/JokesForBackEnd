"""Analytics opt-in fixtures.

Creator Insights and community aggregates count only activity recorded at or
after a person's latest ``AnalyticsConsentRecord`` opt-in, and nothing from a
person with no recorded opt-in. Setting ``profile.share_analytics`` alone is
therefore not enough for a metric fixture; record the opt-in too, dated before
any backdated activity the test creates.
"""
from datetime import UTC, datetime

from jokes.models import AnalyticsConsentRecord

#: Earlier than any backdated fixture row.
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def record_opt_in(user, at=LONG_AGO, enabled=True):
    return AnalyticsConsentRecord.objects.create(
        user=user, enabled=enabled, policy_version='test', provenance='preference', recorded_at=at,
    )
