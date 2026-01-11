from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta

from .models import Joke, DailyJoke


def get_recently_shown_joke_ids(user, days=30):
    """
    Get joke IDs shown to user in the last N days.
    Uses recency window to prevent exhaustion of small dataset.
    """
    cutoff_date = timezone.now().date() - timedelta(days=days)
    return list(
        DailyJoke.objects.filter(
            user=user,
            date__gte=cutoff_date
        ).values_list('joke_id', flat=True)
    )


def get_personalized_joke(user, exclude_joke_ids=None):
    """
    Content-based filtering using UserPreference.
    Returns a joke matching user's preferences, avoiding recently shown.

    Algorithm:
    1. Build filter from user preferences (tones, contexts, age_rating, language)
    2. Exclude recently shown jokes (30-day window)
    3. Order by popularity (save count) with randomness for variety
    4. Fallback to any joke if preferences too restrictive
    """
    try:
        prefs = user.preference
    except AttributeError:
        # User has no preference record (shouldn't happen with signal, but defensive)
        prefs = None

    exclude_ids = exclude_joke_ids or []

    # Start with all jokes, excluding recently shown
    base_queryset = Joke.objects.exclude(id__in=exclude_ids)

    if not base_queryset.exists():
        # All jokes exhausted - return None (caller should handle reset)
        return None

    # Build preference-based filter
    if prefs:
        filters = Q()

        if prefs.preferred_tones.exists():
            filters &= Q(tones__in=prefs.preferred_tones.all())

        if prefs.preferred_contexts.exists():
            filters &= Q(context_tags__in=prefs.preferred_contexts.all())

        if prefs.preferred_age_rating:
            filters &= Q(age_rating=prefs.preferred_age_rating)

        if prefs.preferred_language:
            filters &= Q(language=prefs.preferred_language)

        # Apply preference filter if any preferences set
        if filters:
            preference_matches = base_queryset.filter(filters).distinct()
            if preference_matches.exists():
                base_queryset = preference_matches
            # If no preference matches, fall back to base_queryset (any joke)

    # Order by popularity (save count) with randomness
    # This balances quality (popular jokes) with variety (randomness)
    return base_queryset.annotate(
        save_count=Count('saved_by')
    ).order_by('-save_count', '?').first()
