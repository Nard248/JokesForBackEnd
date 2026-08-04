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


def get_personalized_joke(user, exclude_joke_ids=None, allowed_tiers=frozenset({'tier_1'})):
    """
    Content-based filtering using UserPreference.
    Returns a joke matching user's preferences, avoiding recently shown.

    Algorithm:
    1. Build filter from user preferences (tones, contexts, age_rating, language)
    2. Exclude recently shown jokes (30-day window)
    3. Order by popularity (save count) with randomness for variety
    4. Fallback to any joke if preferences too restrictive

    allowed_tiers: frozenset of content_tier values the user is allowed to receive.
    Defaults to frozenset({'tier_1'}) as a fail-safe for any caller that omits it.
    """
    try:
        prefs = user.preference
    except AttributeError:
        # User has no preference record (shouldn't happen with signal, but defensive)
        prefs = None

    exclude_ids = exclude_joke_ids or []

    # Start with jokes in allowed tiers, excluding recently shown
    base_queryset = Joke.objects.exclude(id__in=exclude_ids).filter(
        content_tier__in=allowed_tiers
    )

    # Moderation: never serve a blocked user's jokes (removed jokes are already
    # excluded by the default manager).
    from jokes.moderation import hidden_user_ids
    hidden = hidden_user_ids(user)
    if hidden:
        base_queryset = base_queryset.exclude(creator_id__in=hidden)

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


def get_daily_editorial_joke(target_date=None):
    """Return the joke to feature as "today's joke" in the daily digest email.

    DailyJoke is per-user (personalized) — there's no single stored "joke of
    the day" row. For the digest, which needs ONE joke to feature for every
    recipient, we take the mode of today's DailyJoke rows: whichever joke the
    most authenticated users were personally served today, tie-broken by
    joke id for determinism. A since-removed joke is never eligible even if
    it was the day's most-delivered pick.

    Returns None if no DailyJoke exists yet for the date (nobody has opened
    the app today) — callers should treat that as "skip the daily digest",
    not generate one out of thin air for an email nobody triggered by using
    the app.
    """
    target_date = target_date or timezone.now().date()
    top = (
        DailyJoke.objects
        .filter(date=target_date, joke__is_removed=False)
        .values('joke_id')
        .annotate(n=Count('id'))
        .order_by('-n', 'joke_id')
        .first()
    )
    if not top:
        return None
    return Joke.objects.filter(pk=top['joke_id']).select_related(
        'format', 'age_rating', 'language'
    ).first()
