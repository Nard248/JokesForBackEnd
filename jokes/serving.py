"""
Single choke-point for content-tier access control (COPPA compliance).

allowed_tiers(request) -> frozenset
  Returns the set of content_tier values the requester is allowed to receive.

Rules:
  - Default (fail-safe): {tier_1}
  - Add tier_2 ONLY when: user is authenticated AND profile.is_adult (age >= 18)
    AND preference.show_mature is True.
  - tier_3 is NEVER returned to API callers.
  - Any error accessing profile or preference falls through to {tier_1}.
"""
import logging

from django.core.exceptions import ObjectDoesNotExist

TIER_1 = 'tier_1'
TIER_2 = 'tier_2'
BASE_TIERS = frozenset({TIER_1})

_metrics = logging.getLogger('jokesfor.metrics')


def allowed_tiers(request):
    """
    Resolve the frozenset of content tiers the requester may receive.

    Fail-safe: returns BASE_TIERS ({tier_1}) on any uncertainty.
    Emits a 'jokesfor.metrics' event=content_tier_decision log line for
    every call so Cloud Logging log-based metrics can track age-gate behavior.
    """
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        _metrics.info('metric', extra={
            'event': 'content_tier_decision',
            'tiers_granted': 'tier_1',
            'reason': 'anon',
        })
        return BASE_TIERS

    try:
        profile = user.profile
        pref = user.preference
    except (AttributeError, ObjectDoesNotExist):
        _metrics.info('metric', extra={
            'event': 'content_tier_decision',
            'tiers_granted': 'tier_1',
            'reason': 'no_profile',
        })
        return BASE_TIERS

    if not profile.is_adult:
        _metrics.info('metric', extra={
            'event': 'content_tier_decision',
            'tiers_granted': 'tier_1',
            'reason': 'minor',
        })
        return BASE_TIERS

    if getattr(pref, 'show_mature', False):
        _metrics.info('metric', extra={
            'event': 'content_tier_decision',
            'tiers_granted': 'tier_1+tier_2',
            'reason': 'adult_mature',
        })
        return frozenset({TIER_1, TIER_2})

    # Authenticated adult who has not enabled mature content
    _metrics.info('metric', extra={
        'event': 'content_tier_decision',
        'tiers_granted': 'tier_1',
        'reason': 'adult_no_mature',
    })
    _metrics.info('metric', extra={
        'event': 'age_gate_block',
        'user_id': user.pk,
    })
    return BASE_TIERS
