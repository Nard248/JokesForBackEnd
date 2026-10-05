"""Detect communities that just formed and tell the people they formed around.

Request-triggered like everything else: whenever the aggregate is recomputed
(``services.aggregate`` / ``services.daily_aggregate``) its statuses are diffed
against the persisted ``CommunityState`` rows. A community that moves from
forming or cooling to active gets one in-app ``community_formed`` notification
per recipient (``inbox.Notification``; never email):

* ``role: member`` — the people counted as its members right now (established,
  consenting active adults, including explicit joins by such accounts);
* ``role: creator`` — active accounts with at least one published, non-removed
  tier_1 joke on the theme (by creator FK or a legacy published submission).
  Someone who is both gets the creator notice only.

Idempotency: the state rows are locked for the diff, so concurrent recomputes
serialize and only one of them sees the transition; an aggregate computed
before the state's last observation never overwrites it. The same activation
never notifies twice: a community that dips below five and comes back within
``REFORM_AFTER`` re-activates silently, and one that stayed inactive for at
least that long announces itself again. A community seen for the first time is
recorded as a baseline without notifying; one first seen cooling (active last
week) counts as having just gone inactive, so a quick rebound stays silent.

There is no in-app notification preference in the codebase (the inbox has no
opt-out for any verb; ``email_digest_opt_in`` / ``creator_milestone_opt_in`` /
``notification_*`` govern email and device pushes), so none is applied here.
The notice names no actor, so per-viewer blocks have nothing to act on;
deactivated accounts are excluded.
"""
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q

from communities.models import Community, CommunityState
from inbox.models import Notification
from jokes.models import Joke

VERB = 'community_formed'
REFORM_AFTER = timedelta(days=14)
ACTIVE = 'active'
COOLING = 'cooling'


def record_transitions(statuses, members, observed_at):
    """Persist ``statuses`` ({community_id: status}) and notify newly formed communities.

    ``members`` maps community id to the counted member ids of the same
    aggregate. Returns the ids of the communities that announced themselves.
    """
    if isinstance(observed_at, str):
        observed_at = datetime.fromisoformat(observed_at)
    formed = []
    with transaction.atomic():
        known = {state.community_id: state for state in
                 CommunityState.objects.select_for_update().filter(community_id__in=list(statuses))}
        CommunityState.objects.bulk_create(
            [_baseline(cid, status, observed_at) for cid, status in statuses.items() if cid not in known],
            ignore_conflicts=True,  # a concurrent first sight wrote the same baseline
        )
        observed = []
        for cid, state in known.items():
            status = statuses[cid]
            if observed_at < state.observed_at:
                continue  # an older computation finished late; the newer one already counted
            observed.append(state)
            state.observed_at = observed_at
            if status == ACTIVE and state.status != ACTIVE:
                announce = state.active_since is None or (
                    state.inactive_since is not None and observed_at - state.inactive_since >= REFORM_AFTER)
                state.active_since, state.inactive_since = observed_at, None
                if announce:
                    state.notified_at = observed_at
                    formed.append(cid)
            elif status != ACTIVE and state.status == ACTIVE:
                state.inactive_since = observed_at
            state.status = status
        CommunityState.objects.bulk_update(
            observed, ['status', 'observed_at', 'active_since', 'inactive_since', 'notified_at'])
        if formed:
            _notify(formed, members)
    return formed


def _baseline(community_id, status, observed_at):
    """First sight of a community: record it without announcing anything.

    ``cooling`` means the previous window had five or more members, i.e. the
    community was active about a week ago, so it is baselined as having just gone
    inactive: a rebound within ``REFORM_AFTER`` is silent, a later one announces.
    """
    state = CommunityState(community_id=community_id, status=status, observed_at=observed_at)
    if status in (ACTIVE, COOLING):
        state.active_since = observed_at
    if status == COOLING:
        state.inactive_since = observed_at
    return state


def _creator_ids(tag_id):
    # Joke.objects already applies the takedown and editorial-hold gate.
    jokes = Joke.objects.filter(context_tags=tag_id, content_tier='tier_1')
    direct = jokes.filter(creator__isnull=False).values_list('creator_id', flat=True)
    legacy = jokes.filter(Q(creator__isnull=True, submission__status='published')).values_list(
        'submission__user_id', flat=True)
    return {pk for pk in (*direct, *legacy) if pk is not None}


def _notify(community_ids, members):
    User = get_user_model()
    rows = []
    for community in Community.objects.filter(pk__in=community_ids).select_related('tag'):
        creators = _creator_ids(community.tag_id)
        candidates = creators | set(members.get(community.pk, ()))
        recipients = User.objects.filter(pk__in=candidates, is_active=True).values_list('pk', flat=True)
        payload = {'community': community.tag.slug, 'name': community.tag.name, 'emoji': community.emoji}
        rows.extend(
            Notification(recipient_id=pk, verb=VERB,
                         data={**payload, 'role': 'creator' if pk in creators else 'member'})
            for pk in sorted(recipients)
        )
    Notification.objects.bulk_create(rows, batch_size=500)
