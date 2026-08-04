"""Daily digest + creator milestone batch engine (Email-Digest-Wave Task 2).

Called by the (Task 3) internal `POST /api/v1/internal/run-digests/` trigger
on a Cloud Scheduler cadence. Bounded, synchronous, safe to call repeatedly:
EmailMessageLog doubles as the per-day send ledger, so re-running for a date
already processed sends nothing new for the users/creators already touched —
a scheduler double-fire, retry, or manual re-run is a no-op past what's left.

Two email types, one run:
- Daily digest: today's featured joke (jokes.recommendations.
  get_daily_editorial_joke) to every verified+active+opted-in reader who
  hasn't already gotten one today. Skipped entirely if no joke exists yet
  for today (nobody has opened the app -- see get_daily_editorial_joke).
- Creator milestone: one summary email per creator whose published jokes
  picked up >= DIGEST_MILESTONE_THRESHOLD new reactions since their last
  milestone email (or ever, if this is their first).

Both phases share a single `cap` send budget for the call (DIGEST_SEND_CAP
default) -- digest first, then milestones with whatever's left. Eligible
work beyond the budget is reported back as `remaining` so the caller/operator
knows another call will keep draining it.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count
from django.utils import timezone

from jokes.models import Joke, JokeReaction
from jokes.recommendations import get_daily_editorial_joke

from .models import DigestRun, EmailMessageLog
from .service import send_email
from .unsubscribe import unsubscribe_token

User = get_user_model()


def _unsubscribe_url(user, kind):
    """Absolute link to the backend's own unsubscribe view (not the SPA --
    this is a plain Django view, see notifications.views.EmailUnsubscribeView)."""
    base = settings.BACKEND_URL.rstrip('/')
    token = unsubscribe_token(user, kind)
    return f'{base}/api/v1/email/unsubscribe/?token={token}'


def _already_sent_today_user_ids(template_name, today):
    """User ids with an EmailMessageLog(template_name=...) created today --
    the idempotency ledger. Any attempt (sent or failed) counts as touched,
    so a same-day re-run never double-attempts the same recipient."""
    return set(
        EmailMessageLog.objects
        .filter(template_name=template_name, created_at__date=today, user_id__isnull=False)
        .values_list('user_id', flat=True)
    )


def _eligible_digest_users(today):
    """Active (== verified, this app has no separate verified flag -- see
    notifications.views.VerifyEmailView) users opted into the daily digest,
    excluding anyone already sent one today."""
    already_sent = _already_sent_today_user_ids('daily_digest', today)
    return list(
        User.objects.filter(is_active=True, profile__email_digest_opt_in=True)
        .exclude(pk__in=already_sent)
        .order_by('pk')
    )


def _joke_teaser(joke):
    """Setup-only teaser -- the punchline is never emailed (mirrors the
    freemium paywall's server-side payoff withholding; reveal happens
    in-app only). One-liner formats have no distinct setup, so fall back
    to the full joke text."""
    return joke.setup or joke.text


def _send_daily_digest(user, joke):
    context = {
        'setup': _joke_teaser(joke),
        'reveal_url': f"{settings.FRONTEND_URL.rstrip('/')}/daily",
        'unsubscribe_url': _unsubscribe_url(user, 'digest'),
    }
    send_email(user.email, 'daily_digest', context, user=user)


def _eligible_milestone_creators(today):
    """[(creator_user, new_reaction_count), ...] for every creator whose
    published (live, non-removed) jokes gained >= DIGEST_MILESTONE_THRESHOLD
    reactions since their last creator_milestone email -- or ever, if none.

    A reaction can only exist after its joke was published, so "since last
    email, or since publish if none" collapses to one baseline per creator:
    the sent_at of their most recent successful creator_milestone send (None
    counts everything, which is exactly "since publish" for every joke that
    predates any milestone email).
    """
    threshold = settings.DIGEST_MILESTONE_THRESHOLD
    already_sent = _already_sent_today_user_ids('creator_milestone', today)

    creator_ids = (
        Joke.objects.filter(creator__isnull=False)
        .exclude(creator_id__in=already_sent)
        .values_list('creator_id', flat=True).distinct()
    )
    creators = (
        User.objects.filter(pk__in=creator_ids, is_active=True, profile__creator_milestone_opt_in=True)
        .order_by('pk')
    )

    results = []
    for creator in creators:
        baseline = (
            EmailMessageLog.objects
            .filter(user=creator, template_name='creator_milestone', status='sent')
            .order_by('-sent_at')
            .values_list('sent_at', flat=True)
            .first()
        )
        reactions = JokeReaction.objects.filter(joke__creator=creator, joke__is_removed=False)
        if baseline:
            reactions = reactions.filter(created_at__gt=baseline)
        new_count = reactions.count()
        if new_count >= threshold:
            results.append((creator, new_count))
    return results


def _send_creator_milestone(creator, new_reaction_count):
    context = {
        'new_reaction_count': new_reaction_count,
        'profile_url': f"{settings.FRONTEND_URL.rstrip('/')}/profile",
        'unsubscribe_url': _unsubscribe_url(creator, 'milestone'),
    }
    send_email(creator.email, 'creator_milestone', context, user=creator)


def run_daily_digests(cap=None):
    """Run one bounded batch of daily-digest + creator-milestone sends.

    Returns {'digests_sent', 'milestones_sent', 'skipped', 'remaining'}.
    `skipped` is True iff the daily-digest phase was skipped because no
    daily joke exists yet for today (milestones still run). `remaining` is
    the count of eligible sends (both types combined) left undone because
    `cap` ran out -- call again to keep draining it.
    """
    cap = settings.DIGEST_SEND_CAP if cap is None else cap
    today = timezone.now().date()

    run, _created = DigestRun.objects.get_or_create(
        date=today, defaults={'started_at': timezone.now()}
    )

    budget = cap
    digests_sent = 0
    milestones_sent = 0
    remaining = 0
    skipped = False

    daily_joke = get_daily_editorial_joke(today)
    if daily_joke is None:
        skipped = True
    else:
        eligible_users = _eligible_digest_users(today)
        to_send, leftover = eligible_users[:budget], eligible_users[budget:]
        for user in to_send:
            _send_daily_digest(user, daily_joke)
            digests_sent += 1
        budget -= digests_sent
        remaining += len(leftover)

    eligible_creators = _eligible_milestone_creators(today)
    to_send, leftover = eligible_creators[:max(budget, 0)], eligible_creators[max(budget, 0):]
    for creator, new_count in to_send:
        _send_creator_milestone(creator, new_count)
        milestones_sent += 1
    remaining += len(leftover)

    run.digests_sent += digests_sent
    run.milestones_sent += milestones_sent
    run.finished_at = timezone.now()
    run.save(update_fields=['digests_sent', 'milestones_sent', 'finished_at'])

    return {
        'digests_sent': digests_sent,
        'milestones_sent': milestones_sent,
        'skipped': skipped,
        'remaining': remaining,
    }
