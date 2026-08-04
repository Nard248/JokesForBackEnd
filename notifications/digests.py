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
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import F, Q
from django.utils import timezone

from jokes.models import Joke, JokeReaction
from jokes.recommendations import get_daily_editorial_joke

from .models import DigestRun, EmailMessageLog
from .service import EmailSendError, send_email
from .unsubscribe import unsubscribe_token

User = get_user_model()
logger = logging.getLogger(__name__)


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


def _list_unsubscribe_headers(unsubscribe_url):
    """RFC 2369 (List-Unsubscribe) + RFC 8058 (List-Unsubscribe-Post)
    headers so Gmail/Yahoo/Outlook.com render a native one-click
    "Unsubscribe" action next to the sender instead of relying on the
    recipient to find and click the in-body link. Per RFC 8058, when both
    headers are present the provider POSTs the literal body
    `List-Unsubscribe=One-Click` straight to this URL (token already in its
    query string) with no browser involved at all -- see
    notifications.views.EmailUnsubscribeView.post, which reads the token
    from the query string for exactly this path (the confirm-page's own
    form instead posts the token in the request body)."""
    return {
        'List-Unsubscribe': f'<{unsubscribe_url}>',
        'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
    }


def _send_daily_digest(user, joke):
    unsubscribe_url = _unsubscribe_url(user, 'digest')
    context = {
        'setup': _joke_teaser(joke),
        'reveal_url': f"{settings.FRONTEND_URL.rstrip('/')}/daily",
        'unsubscribe_url': unsubscribe_url,
    }
    send_email(
        user.email, 'daily_digest', context, user=user,
        headers=_list_unsubscribe_headers(unsubscribe_url),
    )


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
    unsubscribe_url = _unsubscribe_url(creator, 'milestone')
    context = {
        'new_reaction_count': new_reaction_count,
        'profile_url': f"{settings.FRONTEND_URL.rstrip('/')}/profile",
        'unsubscribe_url': unsubscribe_url,
    }
    send_email(
        creator.email, 'creator_milestone', context, user=creator,
        headers=_list_unsubscribe_headers(unsubscribe_url),
    )


def run_daily_digests(cap=None):
    """Run one bounded batch of daily-digest + creator-milestone sends.

    Returns {'digests_sent', 'milestones_sent', 'failed', 'skipped',
    'remaining', 'locked'}. `skipped` is True iff the daily-digest phase was
    skipped because no daily joke exists yet for today (milestones still
    run). `remaining` is the count of eligible sends (both types combined)
    left undone because `cap` ran out -- call again to keep draining it.
    `failed` is the count of individual sends that raised (bad address,
    transport error, provider outage) -- see the per-send try/except below;
    those recipients already have a 'failed' EmailMessageLog row (send_email
    writes it before the transport call), so a subsequent run's ledger
    lookup naturally skips them rather than retrying forever. `locked` is
    True iff this call bailed out immediately because another run already
    holds today's claim (see below) -- every other key is a no-op zero/False
    in that case.

    Concurrency: a pooling-safe compare-and-set claim on today's DigestRun
    row, NOT a Postgres advisory lock. This app's prod DB connection goes
    through Neon's `-pooler` endpoint, which is PgBouncer in TRANSACTION
    pooling mode (see JokesForProject/settings.py's `-pooler` handling,
    right above where DATABASES is built) -- under transaction pooling with
    Django's autocommit, each individual statement can be served by a
    *different* backend connection. A session-scoped `pg_advisory_lock`
    taken in one statement and released via `pg_advisory_unlock` in a later
    statement is therefore NOT safe here: the unlock can land on a different
    backend than the lock, return "not owner", and silently fail to release
    -- leaking the lock onto some idle pooled connection forever (no DISCARD
    between transactions in transaction-pooling mode). Every subsequent
    same-day call -- a manual re-run, or this very function's own
    cap-drain contract ("call `remaining` again to keep draining it") --
    would then block forever on `pg_advisory_lock` (it has no timeout),
    eventually hit gunicorn's worker timeout, and 500. In short: the first
    real run of the day would deadlock every run after it. A prior version
    of this function used exactly that advisory-lock approach; it passed
    every local test because the local/test DB is a single direct Postgres
    connection (session-scoped locks are trivially safe, and even re-entrant,
    on one session) -- the pooling failure mode has no way to manifest
    locally, so a green suite proved nothing about prod safety here.

    The claim below is safe under pooling because each operation is exactly
    one SQL statement, and Postgres serializes concurrent UPDATEs on the
    same row itself (the second racer's UPDATE blocks until the first
    commits, then re-evaluates its WHERE clause against the now-committed
    row and matches zero rows) -- no cross-statement session affinity is
    required at all:
      1. `get_or_create` the row for today (idempotent, already existed).
      2. ONE conditional `UPDATE ... WHERE claimed_until IS NULL OR
         claimed_until < now() SET claimed_until = now() + 10min`. Two
         overlapping callers both reach this after both having
         get_or_create'd the same row; only one UPDATE's WHERE clause still
         matches by the time Postgres serializes them, so only one caller
         sees `updated == 1` and proceeds -- the other sees `updated == 0`
         and returns immediately with `locked=True`, sending nothing.
      3. On the way out (`finally`), ONE unconditional `UPDATE ... SET
         claimed_until = NULL` releases the claim for the next legitimate
         call (including this function's own cap-drain continuations)
         without waiting for the window to expire. The 10-minute window
         itself only matters if the process is SIGKILLed mid-run and the
         `finally` never executes -- it's a self-heal ceiling, not the
         normal release path.
    """
    cap = settings.DIGEST_SEND_CAP if cap is None else cap
    today = timezone.now().date()

    DigestRun.objects.get_or_create(date=today, defaults={'started_at': timezone.now()})

    now = timezone.now()
    claimed = (
        DigestRun.objects.filter(date=today)
        .filter(Q(claimed_until__isnull=True) | Q(claimed_until__lt=now))
        .update(claimed_until=now + timedelta(minutes=10))
    )
    if not claimed:
        return {
            'digests_sent': 0, 'milestones_sent': 0, 'failed': 0,
            'skipped': False, 'remaining': 0, 'locked': True,
        }

    try:
        run = DigestRun.objects.get(date=today)

        budget = cap
        digests_sent = 0
        milestones_sent = 0
        failed = 0
        remaining = 0
        skipped = False

        daily_joke = get_daily_editorial_joke(today)
        if daily_joke is None:
            skipped = True
        else:
            eligible_users = _eligible_digest_users(today)
            to_send, leftover = eligible_users[:budget], eligible_users[budget:]
            for user in to_send:
                try:
                    _send_daily_digest(user, daily_joke)
                    digests_sent += 1
                except EmailSendError as exc:
                    failed += 1
                    logger.warning('daily_digest send failed for user_id=%s: %s', user.pk, exc)
                except Exception:
                    # Never let one bad recipient -- or an unexpected bug in
                    # the send path itself -- 500 the whole batch and skip
                    # the DigestRun counts update / the rest of the run.
                    failed += 1
                    logger.exception(
                        'daily_digest send raised unexpectedly for user_id=%s', user.pk
                    )
            budget -= digests_sent
            remaining += len(leftover)

        eligible_creators = _eligible_milestone_creators(today)
        to_send, leftover = eligible_creators[:max(budget, 0)], eligible_creators[max(budget, 0):]
        for creator, new_count in to_send:
            try:
                _send_creator_milestone(creator, new_count)
                milestones_sent += 1
            except EmailSendError as exc:
                failed += 1
                logger.warning('creator_milestone send failed for user_id=%s: %s', creator.pk, exc)
            except Exception:
                failed += 1
                logger.exception(
                    'creator_milestone send raised unexpectedly for user_id=%s', creator.pk
                )
        remaining += len(leftover)

        # F()-expression update, not a Python read-modify-write: the claim
        # above is what serializes concurrent runs now, but this stays an
        # F() update anyway (cheap, and correctness of sends themselves
        # never depends on this counter -- EmailMessageLog is the
        # idempotency ledger -- this is purely the observability total
        # staying accurate under any future path that touches this row
        # without going through the claim).
        DigestRun.objects.filter(pk=run.pk).update(
            digests_sent=F('digests_sent') + digests_sent,
            milestones_sent=F('milestones_sent') + milestones_sent,
            finished_at=timezone.now(),
        )

        return {
            'digests_sent': digests_sent,
            'milestones_sent': milestones_sent,
            'failed': failed,
            'skipped': skipped,
            'remaining': remaining,
            'locked': False,
        }
    finally:
        # Release the claim unconditionally, even if something above raised
        # past our own per-send guards (e.g. a DB error building the
        # eligible sets) -- one single-statement UPDATE, safe under
        # transaction pooling for the same reason the claim UPDATE is: no
        # cross-statement session affinity required. The 10-minute window
        # is the only thing standing in for this if the process is
        # SIGKILLed before `finally` runs.
        DigestRun.objects.filter(date=today).update(claimed_until=None)
