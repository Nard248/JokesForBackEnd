"""Frozen reference: the community aggregate as computed before materialization.

This is the ledger-scanning implementation that ``communities.services``
replaced (copied verbatim from origin/main at 7dcc5b5). It exists only so tests
can prove the materialized read path returns identical numbers. Do not use it
in application code.
"""
from collections import Counter, defaultdict
from datetime import timedelta
from itertools import combinations

from django.db.models import Count, Max
from django.utils import timezone

from communities import engine
from communities.models import Community, CommunityMembership
from creator_insights.privacy import eligible_analytics_users
from jokes.models import AnalyticsConsentRecord, Favorite, Joke, JokeReaction, SavedJoke, ShareEvent

WINDOW_DAYS = 90
POSITIVE_REACTIONS = (JokeReaction.REACTION_LOL, JokeReaction.REACTION_CRYING)


def _signal_specs():
    return (
        (JokeReaction.objects.filter(reaction__in=POSITIVE_REACTIONS), 'updated_at', 'like'),
        (Favorite.objects.all(), 'created_at', 'favorite'),
        (SavedJoke.objects.all(), 'created_at', 'save'),
        (ShareEvent.objects.filter(user__isnull=False), 'created_at', 'share'),
    )


def collect_signals(since, users=None, jokes=None):
    """Return ``(user_id, joke_id, kind, occurred_at)`` positive signals since ``since``."""
    rows = []
    for queryset, stamp, kind in _signal_specs():
        queryset = queryset.filter(
            **{f'{stamp}__gte': since}, joke__content_tier='tier_1', joke__is_removed=False,
        )
        if users is not None:
            queryset = queryset.filter(user__in=users)
        if jokes is not None:
            queryset = queryset.filter(joke__in=jokes)
        rows.extend(
            (user_id, joke_id, kind, at)
            for user_id, joke_id, at in queryset.values_list('user_id', 'joke_id', stamp).iterator()
        )
    return rows


def consent_starts(users):
    """When each currently-consenting person's latest opt-in was recorded.

    Consent is not applied backwards: reactions from before someone turned on
    audience analytics never feed a public or creator-visible number. People
    with no recorded opt-in contribute nothing.
    """
    return dict(
        AnalyticsConsentRecord.objects.filter(user__in=users, enabled=True)
        .values_list('user_id').annotate(start=Max('recorded_at'))
    )


def eligible_signals(since, jokes=None, exclude_user=None):
    """Positive signals from the eligible population, each inside its consent period."""
    users = eligible_analytics_users()
    if exclude_user is not None:
        users = users.exclude(pk=exclude_user.pk)
    starts = consent_starts(users.values('pk'))
    return [
        signal for signal in collect_signals(since, users=list(starts), jokes=jokes)
        if signal[3] >= starts[signal[0]]
    ]


def _tags_by_joke(joke_ids, tag_to_community):
    through = Joke.context_tags.through
    mapping = defaultdict(list)
    pairs = through.objects.filter(joke_id__in=joke_ids, contexttag_id__in=list(tag_to_community))
    for joke_id, tag_id in pairs.values_list('joke_id', 'contexttag_id'):
        mapping[joke_id].append(tag_to_community[tag_id])
    return mapping


def to_engine_events(signals, tag_to_community):
    tags = _tags_by_joke({joke for _, joke, _, _ in signals}, tag_to_community)
    return [
        {'actor_id': user, 'content_id': joke, 'subject_id': community, 'kind': kind, 'occurred_at': at}
        for user, joke, kind, at in signals
        for community in tags.get(joke, ())
    ]


def listed_communities():
    return list(Community.objects.filter(is_listed=True).select_related('tag').order_by('tag__name'))


def compute_aggregate(now=None):
    """Recompute community state for the whole eligible population (uncached)."""
    now = now or timezone.now()
    communities = listed_communities()
    tag_to_community = {c.tag_id: c.pk for c in communities}
    signals = eligible_signals(now - timedelta(days=WINDOW_DAYS))
    events = to_engine_events(signals, tag_to_community)

    # Consent gates every aggregate: an explicit join by someone who does not
    # share analytics changes only their own view, never a public number.
    memberships = list(
        CommunityMembership.objects.filter(
            community_id__in=list(tag_to_community.values()),
            user__in=eligible_analytics_users().values('pk'),
        ).values('user_id', 'community_id', 'state', 'updated_at')
    )
    overrides = [{'actor_id': m['user_id'], 'subject_id': m['community_id'], 'state': m['state']}
                 for m in memberships]
    current = engine.affinities(events, now, overrides)
    past_time = now - timedelta(days=7)
    past_overrides = [o for o, m in zip(overrides, memberships, strict=True) if m['updated_at'] <= past_time]
    previous = engine.affinities([e for e in events if e['occurred_at'] <= past_time], past_time, past_overrides)

    inferred, members, before = defaultdict(set), defaultdict(set), defaultdict(set)
    scores = Counter()
    topics = defaultdict(set)
    for (person, community), result in current.items():
        scores[community] += result['score']
        if result['inferred']:
            inferred[community].add(person)
        if result['member']:
            members[community].add(person)
            topics[person].add(community)
    for (person, community), result in previous.items():
        if result['inferred']:
            before[community].add(person)

    activity = defaultdict(lambda: [0] * 7)
    contributors = defaultdict(set)
    for event in events:
        days_ago = (now.date() - event['occurred_at'].date()).days
        if 0 <= days_ago <= 6:
            activity[event['subject_id']][6 - days_ago] += 1
            contributors[event['subject_id']].add(event['actor_id'])

    bridges = Counter()
    for person_topics in topics.values():
        bridges.update(combinations(sorted(person_topics), 2))

    joke_counts = dict(
        Joke.context_tags.through.objects.filter(
            joke__content_tier='tier_1', joke__is_removed=False, contexttag_id__in=list(tag_to_community),
        ).values_list('contexttag_id').annotate(n=Count('joke_id', distinct=True))
    )
    rows = {}
    for community in communities:
        cid = community.pk
        rows[cid] = {
            'id': cid,
            'members': sorted(members[cid]),
            'engaged': len(inferred[cid]),
            'previous': len(before[cid]),
            'contributors': len(contributors[cid]),
            'score': round(scores[cid], 2),
            'activity': activity[cid],
            'joke_count': joke_counts.get(community.tag_id, 0),
        }
    return {
        'generated_at': now.isoformat(),
        'rows': rows,
        'member_total': len(topics),
        'multi_community': sum(len(t) > 1 for t in topics.values()),
        'bridges': [[a, b, n] for (a, b), n in sorted(bridges.items())],
    }

