from celery import shared_task
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import DailyJoke
from .recommendations import get_personalized_joke, get_recently_shown_joke_ids


@shared_task(name='jokes.generate_daily_jokes')
def generate_daily_jokes():
    """
    Generate personalized daily jokes for all eligible users.

    Run this task daily (e.g., 00:01 UTC) via Celery Beat schedule.
    Creates DailyJoke records for users who have completed onboarding.

    Returns dict with generation stats for monitoring.
    """
    User = get_user_model()
    today = timezone.now().date()

    stats = {
        'date': str(today),
        'processed': 0,
        'created': 0,
        'skipped_existing': 0,
        'skipped_no_joke': 0,
    }

    # Only generate for users who completed onboarding
    eligible_users = User.objects.filter(
        preference__onboarding_completed=True
    ).select_related('preference')

    for user in eligible_users:
        stats['processed'] += 1

        # Skip if already has today's joke
        if DailyJoke.objects.filter(user=user, date=today).exists():
            stats['skipped_existing'] += 1
            continue

        # Get recently shown jokes (30-day window)
        exclude_ids = get_recently_shown_joke_ids(user, days=30)

        # Get personalized joke
        joke = get_personalized_joke(user, exclude_joke_ids=exclude_ids)

        if joke:
            DailyJoke.objects.create(
                user=user,
                joke=joke,
                date=today
            )
            stats['created'] += 1
        else:
            # No joke available (dataset exhausted)
            stats['skipped_no_joke'] += 1

    return stats


@shared_task(name='jokes.generate_daily_joke_for_user')
def generate_daily_joke_for_user(user_id):
    """
    Generate daily joke for a specific user.
    Used for on-demand generation when user first accesses daily joke.

    Returns joke_id if created, None if already exists or no joke available.
    """
    User = get_user_model()
    today = timezone.now().date()

    try:
        user = User.objects.select_related('preference').get(id=user_id)
    except User.DoesNotExist:
        return None

    # Skip if already has today's joke
    existing = DailyJoke.objects.filter(user=user, date=today).first()
    if existing:
        return existing.joke_id

    # Get recently shown jokes (30-day window)
    exclude_ids = get_recently_shown_joke_ids(user, days=30)

    # Get personalized joke
    joke = get_personalized_joke(user, exclude_joke_ids=exclude_ids)

    if joke:
        daily = DailyJoke.objects.create(
            user=user,
            joke=joke,
            date=today
        )
        return daily.joke_id

    return None
