"""Achievement unlocking — the engine the seeded badges were always missing.

Twelve `Achievement` rows ship with `criteria_type`/`criteria_value` set, and
the profile UI renders them, but nothing ever wrote a `UserAchievement`. The
badges were decorative: permanently `unlocked: false` regardless of what the
reader did.

Design constraints this follows:

* **Request-triggered.** The project runs as a single Cloud Run service with no
  Celery, no cron and no workers, so evaluation happens inline when the user's
  achievements are read. It is cheap (one aggregate query per distinct metric
  actually in use) and runs only for the requesting user.
* **Idempotent.** `get_or_create` keyed on (user, achievement) means repeated
  reads never duplicate an award.
* **Monotonic.** Awards are never revoked. Un-saving a joke does not take back a
  badge that was legitimately earned — the achievement records that the user
  *reached* the threshold, not that they still sit above it.
"""
from .models import Achievement, UserAchievement


def _metric_counts(user, metric_types):
    """Resolve only the metrics actually referenced by the seeded achievements."""
    counts = {}

    if 'save_count' in metric_types:
        counts['save_count'] = user.saved_jokes.count()

    if 'favorite_count' in metric_types:
        counts['favorite_count'] = user.favorites.count()

    if 'share_count' in metric_types:
        from .models import ShareEvent
        counts['share_count'] = ShareEvent.objects.filter(user=user).count()

    if 'rating_count' in metric_types:
        from .models import JokeRating
        counts['rating_count'] = JokeRating.objects.filter(user=user).count()

    if 'submission_count' in metric_types:
        from .models import JokeSubmission
        counts['submission_count'] = JokeSubmission.objects.filter(user=user).count()

    if 'published_count' in metric_types:
        from .models import Joke
        counts['published_count'] = Joke.objects.filter(creator=user).count()

    if 'streak_days' in metric_types:
        streak = getattr(user, 'streak', None)
        # Longest ever, not current: a badge for a 7-day streak should survive
        # the day the streak breaks.
        counts['streak_days'] = max(
            getattr(streak, 'longest_count', 0) or 0,
            getattr(streak, 'current_count', 0) or 0,
        ) if streak else 0

    return counts


def evaluate_for(user):
    """Award every achievement whose threshold `user` has reached.

    Returns the list of newly-created `UserAchievement` rows (empty on the
    common no-op path). Safe to call on every read.
    """
    achievements = list(Achievement.objects.all())
    if not achievements:
        return []

    already = set(
        UserAchievement.objects.filter(user=user)
        .values_list('achievement_id', flat=True)
    )
    pending = [a for a in achievements if a.id not in already]
    if not pending:
        return []

    counts = _metric_counts(user, {a.criteria_type for a in pending})

    newly = []
    for ach in pending:
        reached = counts.get(ach.criteria_type)
        if reached is None:
            # Unknown criteria_type: never award, never crash. A typo in a seed
            # row must not hand out badges or 500 the profile page.
            continue
        if reached >= ach.criteria_value:
            obj, created = UserAchievement.objects.get_or_create(
                user=user, achievement=ach,
            )
            if created:
                newly.append(obj)
    return newly
