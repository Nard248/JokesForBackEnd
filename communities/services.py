"""Community formation over real engagement, with privacy-preserving outputs.

Population rules (the line that must hold):

* Aggregates (member counts, activity, bridges, creator reach) only use people
  who are eligible for audience analytics: adults with ``share_analytics`` on
  (``creator_insights.privacy.eligible_analytics_users``). An adult's explicit
  join also counts as a member, but never toward activation.
* A person's own affinity is shown only to that person and is computed from
  their own activity, whether or not they share analytics.
* No output ever names, samples or links individual audience members. Counts
  below ``MIN_DISPLAY`` are returned as ``null``.
* Signals come only from tier_1, non-removed jokes, so mature or taken-down
  content can never form a community.

Single-service constraint: everything is request-triggered. The aggregate is
computed from a bounded 90-day signal window and cached; engagement writes
invalidate it (see ``signals.py``). At scale this becomes an incremental
per-(user, community) materialization — the engine's inputs do not change.
"""
import time
import uuid
from collections import Counter, defaultdict
from datetime import timedelta
from itertools import combinations

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Max, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from communities import engine
from communities.models import Community, CommunityMembership
from creator_insights.privacy import eligible_analytics_users
from jokes.identity import public_display_name, public_handle
from jokes.models import AnalyticsConsentRecord, Favorite, Joke, JokeReaction, SavedJoke, ShareEvent

WINDOW_DAYS = 90
MIN_DISPLAY = engine.MINIMUM_MEMBERS
CACHE_KEY = 'communities:aggregate:v2'
VERSION_KEY = 'communities:aggregate:version'
LOCK_KEY = 'communities:aggregate:lock'
POSITIVE_REACTIONS = (JokeReaction.REACTION_LOL, JokeReaction.REACTION_CRYING)

METHODOLOGY = {
    'half_life_days': engine.HALF_LIFE_DAYS,
    'membership_threshold': engine.MEMBERSHIP_THRESHOLD,
    'minimum_content': engine.MINIMUM_CONTENT,
    'minimum_members': engine.MINIMUM_MEMBERS,
    'content_cap': engine.CONTENT_CAP,
    'weights': {k: v for k, v in engine.WEIGHTS.items() if v},
    'window_days': WINDOW_DAYS,
    'minimum_display': MIN_DISPLAY,
    'description': (
        'Each positive signal — a laugh reaction, favorite, save or share — counts once per joke, '
        'at most 4 points, and fades with a seven-day half-life. Six points across at least two '
        'jokes on a theme makes you part of that theme\'s community. A community becomes active '
        'when five people get there independently. Joining by hand never activates a community, '
        'and leaving always overrides inference. Only adults who share audience analytics are '
        'counted; counts under five are hidden and no individual is ever shown.'
    ),
}


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


def _adult_cutoff():
    return timezone.now().date() - relativedelta(years=18)


def _status(engaged, previous):
    if engaged >= engine.MINIMUM_MEMBERS:
        return 'active'
    if previous >= engine.MINIMUM_MEMBERS:
        return 'cooling'
    return 'forming'


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


def _version():
    version = cache.get(VERSION_KEY)
    if version is None:
        cache.add(VERSION_KEY, 1, None)
        version = cache.get(VERSION_KEY, 1)
    return version


def aggregate():
    """Serve the cached aggregate; recompute when it is stale, at most every
    ``COMMUNITIES_MIN_REFRESH_SECONDS``, and by one request at a time.

    Engagement writes only bump a version, so a burst of reactions (or someone
    toggling one in a loop) cannot force a recompute on every read.
    """
    version = _version()
    entry = cache.get(CACHE_KEY)
    now = time.time()
    min_refresh = getattr(settings, 'COMMUNITIES_MIN_REFRESH_SECONDS', 10)
    if entry is not None and (entry['version'] == version or now - entry['computed'] < min_refresh):
        return entry['data']
    token = uuid.uuid4().hex
    owns_lock = cache.add(LOCK_KEY, token, 30)
    if not owns_lock and entry is not None:
        return entry['data']  # another request is recomputing; serve the previous state
    try:
        data = compute_aggregate()
        if owns_lock:
            # No TTL: freshness comes from the version and the refresh floor.
            cache.set(CACHE_KEY, {'data': data, 'version': version, 'computed': now}, None)
    finally:
        if owns_lock and cache.get(LOCK_KEY) == token:
            cache.delete(LOCK_KEY)
    return data


def invalidate():
    try:
        cache.incr(VERSION_KEY)
    except ValueError:
        cache.set(VERSION_KEY, 2, None)


def _shown(count):
    return count if count >= MIN_DISPLAY else None


def viewer_states(user, communities):
    """The signed-in person's own affinity per community. Never aggregated."""
    if not (user and user.is_authenticated):
        return {}
    now = timezone.now()
    tag_to_community = {c.tag_id: c.pk for c in communities}
    events = to_engine_events(
        collect_signals(now - timedelta(days=WINDOW_DAYS), users=[user.pk]), tag_to_community,
    )
    overrides = [
        {'actor_id': user.pk, 'subject_id': cid, 'state': state}
        for cid, state in CommunityMembership.objects.filter(user=user).values_list('community_id', 'state')
    ]
    results = engine.affinities(events, now, overrides)
    return {cid: results.get((user.pk, cid)) for cid in tag_to_community.values()}


def viewer_context(user):
    if not (user and user.is_authenticated):
        return None
    counted = eligible_analytics_users().filter(pk=user.pk).exists()
    return {'counted': counted}


def _explanation(community, status, engaged, viewer, counted):
    name = community.tag.name
    if status == 'active':
        text = (f'{engaged} people each enjoyed at least {engine.MINIMUM_CONTENT} {name} jokes recently.'
                if engaged >= MIN_DISPLAY else f'People are regularly enjoying {name} jokes together.')
    elif status == 'cooling':
        text = f'Engagement around {name} has cooled. Fresh laughs bring this community back.'
    else:
        text = (f'Forming. It activates when {engine.MINIMUM_MEMBERS} people each enjoy '
                f'{engine.MINIMUM_CONTENT}+ {name} jokes.')
    if viewer:
        if viewer.get('explicit') == 'left':
            text += ' You left — we won\'t add you back automatically.'
        elif viewer.get('inferred'):
            text += ' Your laughs made you part of it.' if counted else (
                ' Your taste matches — turn on audience analytics to be counted.')
        elif viewer.get('explicit') == 'joined':
            text += ' You joined by choice.'
        elif viewer.get('content_count'):
            text += f' You\'ve enjoyed {viewer["content_count"]} so far.'
    return text


def community_row(community, data, viewer=None, viewer_ctx=None):
    row = data['rows'].get(community.pk) or {
        'members': [], 'engaged': 0, 'previous': 0, 'contributors': 0, 'score': 0, 'activity': [0] * 7,
        'joke_count': 0,
    }
    status = _status(row['engaged'], row['previous'])
    # Activity and score describe individuals when few people contribute.
    visible_activity = row['contributors'] >= MIN_DISPLAY
    counted = bool(viewer_ctx and viewer_ctx['counted'])
    payload = {
        'slug': community.tag.slug,
        'name': community.tag.name,
        'description': community.tagline or community.tag.description,
        'emoji': community.emoji,
        'color': community.color,
        'status': status,
        'members': _shown(len(row['members'])),
        'engaged_members': _shown(row['engaged']),
        'growth': row['engaged'] - row['previous'] if status == 'active' and row['previous'] >= MIN_DISPLAY else None,
        'score': row['score'] if visible_activity else None,
        'joke_count': row['joke_count'],
        'activity': row['activity'] if visible_activity else None,
        'explanation': _explanation(community, status, row['engaged'], viewer, counted),
        'viewer': None,
    }
    if viewer_ctx is not None:
        viewer = viewer or {}
        payload['viewer'] = {
            'affinity': round(viewer.get('score', 0), 2),
            'content_count': viewer.get('content_count', 0),
            'inferred': bool(viewer.get('inferred')),
            'member': bool(viewer.get('member')),
            'explicit': viewer.get('explicit'),
            'progress': min(1.0, round(viewer.get('score', 0) / engine.MEMBERSHIP_THRESHOLD, 2)),
        }
    return payload


def directory(user):
    communities = listed_communities()
    data = aggregate()
    ctx = viewer_context(user)
    states = viewer_states(user, communities) if ctx else {}
    rows = [community_row(c, data, states.get(c.pk), ctx) for c in communities]
    rows.sort(key=lambda r: ({'active': 0, 'forming': 1, 'cooling': 2}[r['status']], -(r['score'] or 0), r['name']))
    slug_by_id = {c.pk: c.tag.slug for c in communities}
    bridges = sorted(
        ({'source': min(slug_by_id[a], slug_by_id[b]), 'target': max(slug_by_id[a], slug_by_id[b]), 'members': n}
         for a, b, n in data['bridges'] if n >= MIN_DISPLAY and a in slug_by_id and b in slug_by_id),
        key=lambda bridge: (bridge['source'], bridge['target']),
    )
    return {
        'generated_at': data['generated_at'],
        'stats': {
            'active_communities': sum(r['status'] == 'active' for r in rows),
            'forming_communities': sum(r['status'] == 'forming' for r in rows),
            'members': _shown(data['member_total']),
            'multi_community_members': _shown(data['multi_community']),
            'signals_7d': sum(sum(r['activity']) for r in rows if r['activity']),
        },
        'viewer': ctx and {**ctx, 'communities': [r['slug'] for r in rows if r['viewer'] and r['viewer']['member']]},
        'communities': rows,
        'bridges': bridges,
        'methodology': METHODOLOGY,
    }


def _windowed_count(model, stamp, since, **filters):
    """Correlated per-joke count inside the window (no cross-table join fan-out)."""
    counted = (model.objects.filter(joke=OuterRef('pk'), **{f'{stamp}__gte': since}, **filters)
               .order_by().values('joke').annotate(n=Count('pk')).values('n'))
    return Coalesce(Subquery(counted), Value(0))


def _scored_jokes(queryset, since):
    """Rank by recent positive engagement. Anonymous shares are excluded: they
    are unauthenticated, undeduplicated and never count toward communities."""
    return queryset.annotate(
        community_score=(
            _windowed_count(JokeReaction, 'updated_at', since, reaction__in=POSITIVE_REACTIONS)
            + _windowed_count(Favorite, 'created_at', since)
            + _windowed_count(SavedJoke, 'created_at', since)
            + 2 * _windowed_count(ShareEvent, 'created_at', since, user__isnull=False)
        )
    )


def community_jokes(community, base_queryset, limit=6):
    """Trending and newest viewer-visible jokes on the community's theme."""
    since = timezone.now() - timedelta(days=30)
    themed = base_queryset.filter(context_tags=community.tag).distinct()
    trending = list(_scored_jokes(themed, since).order_by('-community_score', '-created_at')[:limit])
    newest = list(themed.order_by('-created_at')[:4])
    return trending, newest


def community_creators(community, base_queryset, limit=6):
    """Public creators publishing on this theme. Creators are public by design."""
    counts = (base_queryset.filter(context_tags=community.tag, creator__isnull=False, creator__is_active=True,
                                   creator__profile__public_profile=True)
              .values('creator').annotate(n=Count('id', distinct=True)).order_by('-n', 'creator')[:limit])
    from django.contrib.auth import get_user_model
    users = get_user_model().objects.select_related('profile').in_bulk([row['creator'] for row in counts])
    return [
        {'id': row['creator'], 'display_name': public_display_name(users[row['creator']]),
         'handle': public_handle(users[row['creator']]), 'joke_count': row['n']}
        for row in counts if row['creator'] in users
    ]


def community_bridges(community, data):
    by_id = {c.pk: c for c in listed_communities()}
    out = []
    for a, b, n in data['bridges']:
        if community.pk not in (a, b) or n < MIN_DISPLAY:
            continue
        other = by_id.get(b if a == community.pk else a)
        if other:
            out.append({'slug': other.tag.slug, 'name': other.tag.name, 'emoji': other.emoji,
                        'color': other.color, 'members': n})
    return sorted(out, key=lambda r: -r['members'])


def export_memberships(user):
    """Explicit join/leave choices for the GDPR export. Inferred affinity is not
    stored; it is recomputed from the reactions/saves/shares already exported."""
    return [
        {'community': slug, 'state': state, 'updated_at': updated.isoformat()}
        for slug, state, updated in CommunityMembership.objects.filter(user=user)
        .order_by('community__tag__slug').values_list('community__tag__slug', 'state', 'updated_at')
    ]


def set_membership(user, community, action):
    state = CommunityMembership.STATE_JOINED if action == 'join' else CommunityMembership.STATE_LEFT
    CommunityMembership.objects.update_or_create(user=user, community=community, defaults={'state': state})
    invalidate()


# ---------------------------------------------------------------- creator tools

def creator_reach(user):
    """Which communities a creator's consenting audience belongs to, plus openings.

    Descriptive evidence only; never a promise of growth. Members who reached
    the creator are counted, not identified, and suppressed under MIN_DISPLAY.
    """
    from creator_insights.services import resolve_creator_jokes

    now = timezone.now()
    day = now.date().isoformat()
    key = f'communities:creator-reach:{user.pk}:{day}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    communities = listed_communities()
    data = daily_aggregate(day)
    creator_jokes = resolve_creator_jokes(user).filter(content_tier='tier_1')
    audience = {
        person for person, _, _, _ in eligible_signals(
            now - timedelta(days=WINDOW_DAYS), jokes=creator_jokes.values('pk'), exclude_user=user,
        )
    }
    your_jokes = dict(
        Joke.context_tags.through.objects.filter(
            joke_id__in=creator_jokes.values('pk'), contexttag_id__in=[c.tag_id for c in communities],
        ).values_list('contexttag_id').annotate(n=Count('joke_id', distinct=True))
    )
    rows = []
    for community in communities:
        base = community_row(community, data)
        # A creator is also a reader; their own membership never inflates their reach.
        members = set(data['rows'].get(community.pk, {}).get('members', ())) - {user.pk}
        reached = len(members & audience)
        shown_reached = _coarse_floor(reached)
        rows.append({
            **{k: base[k] for k in ('slug', 'name', 'emoji', 'color', 'status', 'joke_count')},
            'members': _coarse_round(len(members)),
            'reached_members': shown_reached,
            'reach_rate': int(100 * reached / len(members)) // 5 * 5 if shown_reached is not None else None,
            'your_jokes': your_jokes.get(community.tag_id, 0),
        })
    rows.sort(key=lambda r: (-(r['reached_members'] or 0), -(r['your_jokes']), r['name']))
    result = {
        'window_days': WINDOW_DAYS,
        'snapshot_date': day,
        'audience': {'size': _coarse_floor(len(audience)), 'minimum': MIN_DISPLAY},
        'communities': rows,
        'opportunities': _opportunities(rows, data, communities),
        'measurement_notes': [
            f'Audience = adults sharing analytics who laughed at, favorited, saved or shared one of your '
            f'jokes in the last {WINDOW_DAYS} days. Your own activity is excluded.',
            f'Counts are approximate (rounded to multiples of {MIN_DISPLAY}) and counts under {MIN_DISPLAY} '
            'are hidden, so no individual reader can be singled out.',
            'Refreshed once a day (UTC). Communities form from reader behaviour across all creators.',
            'Opportunities describe current evidence; they do not predict or guarantee reach.',
        ],
    }
    cache.set(key, result, 26 * 3600)
    return result


def daily_aggregate(day):
    """One aggregate per UTC day for creator-facing numbers, so a single new
    reader can't be matched to a same-day change in a creator's reach."""
    key = f'communities:daily:{day}'
    data = cache.get(key)
    if data is None:
        data = compute_aggregate()
        cache.set(key, data, 26 * 3600)
    return data


def _coarse_floor(count):
    return count // MIN_DISPLAY * MIN_DISPLAY if count >= MIN_DISPLAY else None


def _coarse_round(count):
    if count < MIN_DISPLAY:
        return None
    return max(MIN_DISPLAY, int(count / MIN_DISPLAY + 0.5) * MIN_DISPLAY)


def _opportunities(rows, data, communities, limit=4):
    by_slug = {c.tag.slug: c for c in communities}
    picks = []
    strongest = next((r for r in rows if r['reached_members'] and r['reach_rate']), None)
    if strongest:
        picks.append({
            'kind': 'stronghold', 'slug': strongest['slug'], 'name': strongest['name'], 'emoji': strongest['emoji'],
            'evidence': (f'About {strongest["reached_members"]} of {strongest["members"]} {strongest["name"]} members '
                         f'({strongest["reach_rate"]}%) engaged with your jokes.'),
            'action': f'Group your {strongest["name"]} material into a series or set list and keep it coming.',
        })
    # Warmest gaps first: active communities whose members already enjoy this creator.
    gaps = [r for r in rows if r['status'] == 'active' and r['your_jokes'] == 0]
    gaps.sort(key=lambda r: (-(r['reached_members'] or 0), -(r['members'] or 0)))
    for row in gaps[:2]:
        warm = (f' About {row["reached_members"]} of them already enjoy your jokes,'
                if row['reached_members'] else '')
        picks.append({
            'kind': 'untapped', 'slug': row['slug'], 'name': row['name'], 'emoji': row['emoji'],
            'evidence': (f'About {row["members"] or "several"} readers form an active {row["name"]} community.'
                         f'{warm} but you have not published for this theme yet.').replace('. but', ', but'),
            'action': f'Try one {row["name"]} joke and tag it with the theme so this audience can find it.',
        })
    forming = [r for r in rows if r['status'] == 'forming' and r['your_jokes'] <= 1]
    forming.sort(key=lambda r: -data['rows'].get(by_slug[r['slug']].pk, {}).get('score', 0))
    for row in forming[:1]:
        picks.append({
            'kind': 'emerging', 'slug': row['slug'], 'name': row['name'], 'emoji': row['emoji'],
            'evidence': f'A {row["name"]} community is forming but has not reached {MIN_DISPLAY} engaged readers.',
            'action': f'Early {row["name"]} jokes help it form — and you will be among its first voices.',
        })
    return picks[:limit]
