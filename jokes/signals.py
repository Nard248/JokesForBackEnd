from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_preference(sender, instance, created, **kwargs):
    """Auto-create UserPreference when a new User is created."""
    if created:
        from .models import UserPreference
        UserPreference.objects.create(user=instance)


# =============================================================================
# Streak (P6 of Pivot Plan) — sync the streak when a user views a joke
# =============================================================================

def _ensure_streak(user):
    """Get-or-create the user's Streak row."""
    from .models import Streak
    streak, _ = Streak.objects.get_or_create(user=user)
    return streak


def _refresh_freezes_if_new_month(streak):
    """Lazily reset freeze pool on first interaction of a new calendar month."""
    from .models import Streak as _S
    from django.utils import timezone
    current = timezone.now().strftime('%Y-%m')
    if streak.last_freeze_refresh_month != current:
        streak.freeze_days_available = _S.FREEZES_PER_MONTH
        streak.last_freeze_refresh_month = current


def _walk_gap(streak, until_date):
    """Walk every day from last_active_date+1 up to (but excluding) until_date.

    For each day with no StreakDay row:
      - if freezes available → mark frozen, decrement freezes
      - else → mark missed, reset current_count to 0

    Mutates the streak in place; caller is responsible for .save().
    """
    from .models import StreakDay
    from datetime import timedelta

    if not streak.last_active_date:
        return
    cursor = streak.last_active_date + timedelta(days=1)
    while cursor < until_date:
        if StreakDay.objects.filter(user=streak.user, date=cursor).exists():
            cursor += timedelta(days=1)
            continue
        if streak.freeze_days_available > 0:
            StreakDay.objects.create(
                user=streak.user, date=cursor, status=StreakDay.STATUS_FROZEN
            )
            streak.freeze_days_available -= 1
            streak.freezes_used_total += 1
        else:
            StreakDay.objects.create(
                user=streak.user, date=cursor, status=StreakDay.STATUS_MISSED
            )
            streak.current_count = 0
        cursor += timedelta(days=1)


@receiver(post_save, sender='jokes.JokeView')
def update_streak_on_view(sender, instance, created, **kwargs):
    """Synchronously update streak when a user views a joke.

    Order matters:
      1. Refresh monthly freezes if month rolled over
      2. Walk the gap (last_active_date+1 → today-1) burning freezes / missing
      3. Mark today as 'read'
      4. Bump current_count by 1 (if today wasn't already counted)
    """
    if not created:
        return  # only the first JokeView in a (user, joke) pair counts

    from .models import StreakDay
    from django.utils import timezone

    today = instance.viewed_date or timezone.now().date()
    streak = _ensure_streak(instance.user)
    _refresh_freezes_if_new_month(streak)

    # Idempotent: if today already counted as read, just save and exit
    if streak.last_active_date == today:
        StreakDay.objects.update_or_create(
            user=instance.user, date=today,
            defaults={'status': StreakDay.STATUS_READ},
        )
        streak.save()
        return

    # Walk the gap up to (excl.) today before recording today's read
    _walk_gap(streak, today)

    # Record today
    StreakDay.objects.update_or_create(
        user=instance.user, date=today,
        defaults={'status': StreakDay.STATUS_READ},
    )

    # Increment streak. After _walk_gap, current_count is either preserved
    # (gap covered by freezes) or reset to 0 (gap uncovered). Either way we
    # add 1 for today.
    streak.current_count += 1
    streak.longest_count = max(streak.longest_count, streak.current_count)
    streak.last_active_date = today
    if streak.started_at is None:
        streak.started_at = today
    streak.save()


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    """Auto-create UserProfile when a new User is created."""
    if created:
        from .models import UserProfile
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_default_collection(sender, instance, created, **kwargs):
    """Auto-create default 'Favorites' collection when a new User is created."""
    if created:
        from .models import Collection
        Collection.objects.create(
            user=instance,
            name='Favorites',
            is_default=True
        )


# =============================================================================
# Appeals wave — statement of reasons on submission rejection
# =============================================================================

@receiver(pre_save, sender='jokes.JokeSubmission')
def stash_submission_status(sender, instance, **kwargs):
    """Stash the DB status before save so post_save can detect the transition
    into 'rejected' (queryset .update() bypasses signals; the admin's manual
    change-form save and full .save() calls go through here)."""
    if instance.pk:
        instance._pre_save_status = (
            sender.objects.filter(pk=instance.pk).values_list('status', flat=True).first()
        )
    else:
        instance._pre_save_status = None


@receiver(post_save, sender='jokes.JokeSubmission')
def notify_submission_rejected(sender, instance, created, **kwargs):
    """Notify the author exactly once when their submission transitions to
    'rejected', carrying the rejection_reason (DSA statement of reasons).
    Re-saves while already rejected and other transitions fire nothing."""
    if created:
        return
    old_status = getattr(instance, '_pre_save_status', None)
    if instance.status == 'rejected' and old_status != 'rejected':
        from inbox.services import notify
        notify(instance.user, 'joke_rejected', rejection_reason=instance.rejection_reason)
