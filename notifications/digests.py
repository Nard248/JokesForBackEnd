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
import hashlib
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import F
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


def _advisory_lock_key(today):
    """Deterministic pg advisory-lock key for one calendar date's digest
    run, derived from a fixed 'digest-run' namespace + the ISO date so two
    overlapping run_daily_digests() calls for the same day contend on the
    same key (and different days never collide). pg_advisory_lock takes a
    signed bigint; truncating the sha256 hex digest to 15 hex chars (60
    bits) keeps the value comfortably inside that range."""
    digest = hashlib.sha256(f'digest-run:{today.isoformat()}'.encode()).hexdigest()
    return int(digest[:15], 16)


def run_daily_digests(cap=None):
    """Run one bounded batch of daily-digest + creator-milestone sends.

    Returns {'digests_sent', 'milestones_sent', 'failed', 'skipped',
    'remaining'}. `skipped` is True iff the daily-digest phase was skipped
    because no daily joke exists yet for today (milestones still run).
    `remaining` is the count of eligible sends (both types combined) left
    undone because `cap` ran out -- call again to keep draining it. `failed`
    is the count of individual sends that raised (bad address, transport
    error, provider outage) -- see the per-send try/except below; those
    recipients already have a 'failed' EmailMessageLog row (send_email
    writes it before the transport call), so a subsequent run's ledger
    lookup naturally skips them rather than retrying forever.

    Concurrency: wrapped in a session-scoped pg advisory lock (see
    _advisory_lock_key) keyed on 'today', so two overlapping invocations for
    the same date -- a scheduler retry racing a manual re-run, or two Cloud
    Run instances both firing -- serialize instead of both reading the same
    "not sent yet" user/creator sets and double-sending (EmailMessageLog has
    no (user, template, day) DB-level uniqueness backing the ledger, only
    this read-then-send convention). Deliberately session-scoped rather than
    a transaction-scoped `pg_advisory_xact_lock` wrapping the whole run in
    one `transaction.atomic()`: each send below still autocommits its own
    EmailMessageLog row immediately, exactly as before this fix. Sending a
    real email is an irreversible external side effect -- if the entire run
    (all the sends' DB writes included) sat inside one transaction and a
    later, unrelated exception rolled it back, the ledger rows for emails
    that had already gone out over the wire would vanish too, and the next
    run would re-send them. The per-send try/except immediately below is
    exactly what makes that "later, unrelated exception" a real
    possibility to guard against, not a theoretical one -- the two fixes
    have to compose safely together.
    """
    cap = settings.DIGEST_SEND_CAP if cap is None else cap
    today = timezone.now().date()
    lock_key = _advisory_lock_key(today)

    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_lock(%s)', [lock_key])
    try:
        run, _created = DigestRun.objects.get_or_create(
            date=today, defaults={'started_at': timezone.now()}
        )

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

        # F()-expression update, not a Python read-modify-write: two
        # sequential holders of the advisory lock above still shouldn't
        # clobber each other's increment on the (unlikely but cheap-to-guard)
        # chance this statement itself races something else touching the
        # same row. Correctness of sends themselves never depends on this
        # counter -- EmailMessageLog is the idempotency ledger -- this is
        # purely the observability total staying accurate.
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
        }
    finally:
        # Always release, even if something above raised past our own
        # per-send guards (e.g. a DB error building the eligible sets) --
        # pg would also auto-release on connection loss, but an explicit
        # unlock keeps the lock's lifetime tied to this call under normal
        # operation instead of the whole DB connection's lifetime (which,
        # under connection pooling/persistent connections, can outlive any
        # single request by a lot).
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [lock_key])
