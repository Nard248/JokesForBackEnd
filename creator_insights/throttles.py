"""
Throttles for the creator_insights app.

Uses the default UserRateThrottle via DRF settings ('user': '1000/hour').
Scope-based throttling is available for future fine-grained limits.
"""
from rest_framework.throttling import UserRateThrottle


class CreatorInsightsThrottle(UserRateThrottle):
    """Throttle for creator insights endpoint. Falls back to default 'user' rate."""
    scope = 'creator_insights'
