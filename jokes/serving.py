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
from django.core.exceptions import ObjectDoesNotExist

TIER_1 = 'tier_1'
TIER_2 = 'tier_2'
BASE_TIERS = frozenset({TIER_1})


def allowed_tiers(request):
    """
    Resolve the frozenset of content tiers the requester may receive.

    Fail-safe: returns BASE_TIERS ({tier_1}) on any uncertainty.
    """
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        return BASE_TIERS

    try:
        profile = user.profile
        pref = user.preference
    except (AttributeError, ObjectDoesNotExist):
        return BASE_TIERS

    if profile.is_adult and getattr(pref, 'show_mature', False):
        return frozenset({TIER_1, TIER_2})

    return BASE_TIERS
