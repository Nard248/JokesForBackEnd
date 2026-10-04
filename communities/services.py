"""Community formation over real engagement, with privacy-preserving outputs.

Population rules (the line that must hold):

* Aggregates (member counts, activity, bridges, creator reach) only use
  *established* people who are eligible for audience analytics: active adults
  with ``share_analytics`` on whose account is old enough and has enjoyed enough
  distinct jokes (``communities.privacy.established_users``). Their explicit
  join also counts as a member, but never toward activation.
* A person's own affinity is shown only to that person and is computed from
  their own activity, whether or not they are counted.
* No output ever names, samples or links individual audience members. Released
  person-counts come from a once-a-day snapshot, carry keyed day-stable noise,
  are rounded to 5 and are ``null`` when the noisy value is under 5
  (``communities.privacy.release``).
* Signals come only from tier_1, non-removed jokes, so mature or taken-down
  content can never form a community.

Single-service constraint: everything is request-triggered. Engagement writes
maintain ``CommunitySignal`` synchronously (``materialize.py``); the aggregate
lets the database reduce it to per-(person, theme) totals inside the 90-day
window, applies the unchanged engine rules to those totals, and is cached;
engagement writes invalidate it (see ``signals.py``).
"""
import logging
import time
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from itertools import combinations

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import (
    Case,
    Count,
    DateTimeField,
    Exists,
    F,
    FloatField,
    Func,
    Max,
    OuterRef,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Cast, Coalesce, TruncDate
from django.utils import timezone

from communities import engine, formation, privacy
from communities.materialize import POSITIVE_REACTIONS, TREND_DAYS
from communities.models import Community, CommunityMembership, CommunitySignal
from creator_insights.privacy import analytics_allowed
from jokes.identity import public_display_name, public_handle
from jokes.models import AnalyticsConsentRecord, Favorite, Joke, JokeReaction, SavedJoke, ShareEvent

WINDOW_DAYS = 90
MIN_DISPLAY = engine.MINIMUM_MEMBERS
CACHE_KEY = 'communities:aggregate:v3'
DAILY_KEY = 'communities:daily:v2:{day}'
VERSION_KEY = 'communities:aggregate:version'
LOCK_KEY = 'communities:aggregate:lock'
# Backstop: even if every invalidation were lost, nothing is served older than this.
MAX_AGE_SECONDS = 3600

logger = logging.getLogger(__name__)

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
        'and leaving always overrides inference. Only adults who share audience analytics, whose '
        'account is at least a week old and who have enjoyed at least three jokes are counted. '
        'Counts are refreshed once a day, carry a little random noise that stays fixed for the '
        'day, are rounded to five and hidden under five; no individual is ever shown.'
    ),
}


def methodology():
    return {
        **METHODOLOGY,
        'established_account_days': settings.COMMUNITIES_ESTABLISHED_ACCOUNT_DAYS,
        'established_min_jokes': settings.COMMUNITIES_ESTABLISHED_MIN_JOKES,
        'noise_epsilon': settings.COMMUNITIES_NOISE_EPSILON,
    }


def signal_rows(since, until=None, users=None, jokes=None, eligible=False, exclude_user=None):
    """Materialized positive signals on tier_1, non-removed jokes, read from ``CommunitySignal``.

    With ``eligible`` the rows are limited to the established, consenting
    population (``privacy.established_users``), each inside its consent period. Consent is not applied backwards: reactions from
    before someone turned on audience analytics never feed a public or
    creator-visible number, and people with no recorded opt-in contribute
    nothing. Eligibility is evaluated here, at read time, so withdrawals,
    deletions, takedowns, tier changes and re-tags apply immediately.
    """
    rows = CommunitySignal.objects.filter(
        occurred_at__gte=since, joke__content_tier='tier_1', joke__is_removed=False,
    )
    if until is not None:
        rows = rows.filter(occurred_at__lte=until)
    if users is not None:
        rows = rows.filter(user__in=users)
    if jokes is not None:
        rows = rows.filter(joke__in=jokes)
    if eligible:
        population = privacy.established_users()
        if exclude_user is not None:
            population = population.exclude(pk=exclude_user.pk)
        # "At or after the latest opt-in", phrased as (anti-)semi-joins so the
        # database can evaluate it set-wise instead of once per signal.
        opt_ins = AnalyticsConsentRecord.objects.filter(user=OuterRef('user_id'), enabled=True)
        rows = rows.filter(
            Exists(opt_ins.filter(recorded_at__lte=OuterRef('occurred_at'))),
            ~Exists(opt_ins.filter(recorded_at__gt=OuterRef('occurred_at'))),
            user__in=population.values('pk'),
        )
    return rows


def _decayed_weight(moment):
    """SQL for ``min(CONTENT_CAP, WEIGHTS[kind]) * engine.decay(occurred_at, moment)``.

    The same IEEE double operations in the same order as ``engine.decay``, with
    the half-life applied at read time.
    """
    weight = Cast(Case(*[When(kind=kind, then=Value(float(min(engine.CONTENT_CAP, engine.WEIGHTS[kind]))))
                         for kind, _ in CommunitySignal.KIND_CHOICES]), FloatField())
    decay = Func(
        Value(moment, output_field=DateTimeField()), F('occurred_at'), arg_joiner=' - ',
        template=('POWER(2::float8, -GREATEST(0::float8, EXTRACT(EPOCH FROM (%(expressions)s))::float8) '
                  f'/ {86400 * engine.HALF_LIFE_DAYS}::float8)'),
        output_field=FloatField(),
    )
    return weight * decay


def _by_theme(inner, select, group_by, tag_ids):
    """Run ``select`` over ``inner`` (alias ``b``) fanned out to each joke's listed themes (alias ``t``)."""
    sql, params = inner.query.sql_with_params()
    through = Joke.context_tags.through._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT {select} FROM ({sql}) AS b JOIN {through} AS t ON t.joke_id = b.joke_id '
            f'WHERE t.contexttag_id = ANY(%s) GROUP BY {group_by}',
            [*params, list(tag_ids)],
        )
        return cursor.fetchall()


def affinities_at(rows, moment, tag_to_community, overrides=()):
    """Engine affinities at ``moment`` from materialized signal rows.

    The database takes each person's strongest decayed signal per joke and sums
    them per theme (with the number of jokes that contributed); the engine then
    applies the unchanged membership rules. Python handles one row per
    (person, community), not one per signal.
    """
    per_joke = (rows.filter(occurred_at__lte=moment).order_by()
                .values('user_id', 'joke_id').annotate(v=Max(_decayed_weight(moment))))
    totals = {
        (person, tag_to_community[tag]): (score, count)
        for person, tag, score, count in _by_theme(
            per_joke, 'b.user_id, t.contexttag_id, SUM(b.v), COUNT(*)', 'b.user_id, t.contexttag_id',
            tag_to_community,
        )
    }
    return engine.affinities_from_totals(totals, overrides)


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
    eligible = signal_rows(now - timedelta(days=WINDOW_DAYS), eligible=True)
    past_time = now - timedelta(days=TREND_DAYS)

    # Activity sparkline: every signal (not only the strongest) per UTC day, today included.
    first_day = now.date() - timedelta(days=TREND_DAYS - 1)
    recent = eligible.filter(
        occurred_at__gte=datetime.combine(first_day, datetime.min.time(), tzinfo=UTC),
        occurred_at__lt=datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
    ).order_by().values('user_id', 'joke_id', day=TruncDate('occurred_at', tzinfo=UTC))
    activity = defaultdict(lambda: [0] * TREND_DAYS)
    for tag, day, count in _by_theme(recent, 't.contexttag_id, b.day, COUNT(*)', 't.contexttag_id, b.day',
                                     tag_to_community):
        activity[tag_to_community[tag]][TREND_DAYS - 1 - (now.date() - day).days] += count
    contributors = {
        tag_to_community[tag]: count for tag, count in _by_theme(
            recent, 't.contexttag_id, COUNT(DISTINCT b.user_id)', 't.contexttag_id', tag_to_community)
    }

    # Consent and establishment gate every aggregate: an explicit join by someone
    # who does not share analytics, or by a brand-new account, changes only their
    # own view, never a public number.
    memberships = list(
        CommunityMembership.objects.filter(
            community_id__in=list(tag_to_community.values()),
            user__in=privacy.established_users().values('pk'),
        ).values('user_id', 'community_id', 'state', 'updated_at')
    )
    overrides = [{'actor_id': m['user_id'], 'subject_id': m['community_id'], 'state': m['state']}
                 for m in memberships]
    current = affinities_at(eligible, now, tag_to_community, overrides)
    past_overrides = [o for o, m in zip(overrides, memberships, strict=True) if m['updated_at'] <= past_time]
    previous = affinities_at(eligible, past_time, tag_to_community, past_overrides)

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
            # Ids stay server-side: released counts re-check them against who still counts.
            'engaged_ids': sorted(inferred[cid]),
            'previous_ids': sorted(before[cid]),
            'contributors': contributors.get(cid, 0),
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


def recompute(now=None):
    """``compute_aggregate`` plus formation detection: every live recompute diffs
    community statuses against the last persisted ones and notifies communities
    that just formed (``formation.record_transitions``)."""
    data = compute_aggregate(now)
    statuses = {cid: _status(row['engaged'], row['previous']) for cid, row in data['rows'].items()}
    members = {cid: row['members'] for cid, row in data['rows'].items()}
    try:
        formation.record_transitions(statuses, members, data['generated_at'])
    except Exception:  # a notification failure must never take the directory down
        logger.exception('community_formation_failed')
    return data


def _version():
    """Opaque, never-reused version. A culled key yields a fresh value, which
    forces a recompute instead of colliding with a cached entry."""
    version = cache.get(VERSION_KEY)
    if version is None:
        cache.add(VERSION_KEY, uuid.uuid4().hex, None)
        version = cache.get(VERSION_KEY) or uuid.uuid4().hex
    return version


def aggregate():
    """Serve the cached aggregate; recompute when it is stale, at most every
    ``COMMUNITIES_MIN_REFRESH_SECONDS``, and by one request at a time.

    Engagement writes only bump a version, so a burst of reactions (or someone
    toggling one in a loop) cannot force a recompute on every read. A new UTC
    day always recomputes, because released counts move to the new snapshot.
    """
    version = _version()
    entry = cache.get(CACHE_KEY)
    now = time.time()
    min_refresh = settings.COMMUNITIES_MIN_REFRESH_SECONDS
    age = now - entry['computed'] if entry is not None else None
    if (entry is not None and age < MAX_AGE_SECONDS and entry['day'] == _today()
            and (entry['version'] == version or age < min_refresh)):
        return entry['data']
    token = uuid.uuid4().hex
    owns_lock = cache.add(LOCK_KEY, token, 30)
    if not owns_lock and entry is not None:
        return entry['data']  # another request is recomputing; serve the previous state
    try:
        moment = timezone.now()
        day = moment.date().isoformat()
        data = recompute(moment)
        data['released'] = release_public(daily_aggregate(day, live=data), day)
        if owns_lock:
            # No TTL: freshness comes from the version, the refresh floor and the day.
            cache.set(CACHE_KEY, {'data': data, 'version': version, 'computed': now, 'day': day}, None)
    finally:
        if owns_lock and cache.get(LOCK_KEY) == token:
            cache.delete(LOCK_KEY)
    return data


def invalidate():
    cache.set(VERSION_KEY, uuid.uuid4().hex, None)


def _today():
    return timezone.now().date().isoformat()


def daily_aggregate(day, live=None):
    """One aggregate per UTC day, the only source of released person-counts.

    The first request of the day freezes it (``live`` reuses an aggregate the
    caller just computed). Freezing is what makes the day-stable noise safe: a
    count cannot move within the day, so sock accounts added or removed one at
    a time cannot locate the noise or a rounding boundary and then watch for a
    single real reader crossing it.
    """
    key = DAILY_KEY.format(day=day)
    data = cache.get(key)
    if data is None:
        fresh = live if live is not None else recompute()
        cache.add(key, fresh, 26 * 3600)
        data = cache.get(key) or fresh
    return data


def forget_daily_aggregate(day=None):
    """Drop a day's snapshot (local reseeding only; never needed in production)."""
    cache.delete(DAILY_KEY.format(day=day or _today()))


def release_public(snapshot, day, population=None):
    """Noisy public person-counts from the day's snapshot.

    The snapshot's id sets are re-checked against who counts *now*, so consent
    withdrawal or account deletion takes effect at the next recompute (counts
    can only fall within a day, never rise). Every count — including zero
    overlaps between communities — gets its own keyed noise before suppression,
    so a released bridge or member count proves nothing about one person.
    """
    if population is None:
        population = set(privacy.established_users().values_list('pk', flat=True))
    rows, topics = {}, defaultdict(set)
    for cid, row in snapshot['rows'].items():
        members = set(row['members']) & population
        for person in members:
            topics[person].add(cid)
        engaged = len(set(row['engaged_ids']) & population)
        previous = len(set(row['previous_ids']) & population)
        shown_members = privacy.release(len(members), 'members', cid, day=day)
        shown_engaged = privacy.release(engaged, 'engaged', cid, day=day)
        # Post-processing for consistency costs no privacy: engaged ⊆ members.
        shown_engaged = None if shown_members is None or shown_engaged is None else min(shown_engaged, shown_members)
        rows[cid] = {
            'members': shown_members,
            'engaged': shown_engaged,
            'growth': (privacy.release_delta(engaged - previous, 'growth', cid, day=day)
                       if shown_engaged is not None else None),
        }
    overlaps = Counter()
    for person_topics in topics.values():
        overlaps.update(combinations(sorted(person_topics), 2))
    bridges = []
    for a, b in combinations(sorted(snapshot['rows']), 2):
        shown = privacy.release(overlaps.get((a, b), 0), 'bridge', a, b, day=day)
        if shown is not None:
            bridges.append([a, b, shown])
    total = privacy.release(len(topics), 'member-total', day=day)
    multi = privacy.release(sum(len(t) > 1 for t in topics.values()), 'multi-community', day=day)
    return {
        'day': day,
        'rows': rows,
        'members': total,
        'multi_community': None if total is None or multi is None else min(multi, total),
        'bridges': bridges,
    }


def _released(data):
    return data.get('released') or {'day': None, 'rows': {}, 'members': None, 'multi_community': None,
                                     'bridges': []}


def viewer_states(user, communities):
    """The signed-in person's own affinity per community. Never aggregated."""
    if not (user and user.is_authenticated):
        return {}
    now = timezone.now()
    tag_to_community = {c.tag_id: c.pk for c in communities}
    overrides = [
        {'actor_id': user.pk, 'subject_id': cid, 'state': state}
        for cid, state in CommunityMembership.objects.filter(user=user).values_list('community_id', 'state')
    ]
    results = affinities_at(signal_rows(now - timedelta(days=WINDOW_DAYS), users=[user.pk]), now,
                            tag_to_community, overrides)
    return {cid: results.get((user.pk, cid)) for cid in tag_to_community.values()}


def viewer_context(user):
    if not (user and user.is_authenticated):
        return None
    return {'counted': privacy.is_established(user), 'shares_analytics': analytics_allowed(user)}


def _explanation(community, status, shown_engaged, viewer, viewer_ctx):
    name = community.tag.name
    if status == 'active':
        text = (f'About {shown_engaged} people each enjoyed at least {engine.MINIMUM_CONTENT} {name} jokes recently.'
                if shown_engaged is not None else f'People are regularly enjoying {name} jokes together.')
    elif status == 'cooling':
        text = f'Engagement around {name} has cooled. Fresh laughs bring this community back.'
    else:
        text = (f'Forming. It activates when {engine.MINIMUM_MEMBERS} people each enjoy '
                f'{engine.MINIMUM_CONTENT}+ {name} jokes.')
    if viewer:
        if viewer.get('explicit') == 'left':
            text += ' You left — we won\'t add you back automatically.'
        elif viewer.get('inferred'):
            if viewer_ctx and viewer_ctx['counted']:
                text += ' Your laughs made you part of it.'
            elif viewer_ctx and viewer_ctx['shares_analytics']:
                text += (f' Your taste matches — you\'ll be counted once your account is '
                         f'{settings.COMMUNITIES_ESTABLISHED_ACCOUNT_DAYS} days old and has enjoyed '
                         f'{settings.COMMUNITIES_ESTABLISHED_MIN_JOKES} jokes.')
            else:
                text += ' Your taste matches — turn on audience analytics to be counted.'
        elif viewer.get('explicit') == 'joined':
            text += ' You joined by choice.'
        elif viewer.get('content_count'):
            text += f' You\'ve enjoyed {viewer["content_count"]} so far.'
    return text


def community_row(community, data, viewer=None, viewer_ctx=None):
    """A community's public row. Status, activity and score are live; person-counts
    are released from the day's snapshot (``release_public``)."""
    row = data['rows'].get(community.pk) or {
        'members': [], 'engaged': 0, 'previous': 0, 'contributors': 0, 'score': 0, 'activity': [0] * 7,
        'joke_count': 0,
    }
    released = _released(data)['rows'].get(community.pk) or {'members': None, 'engaged': None, 'growth': None}
    status = _status(row['engaged'], row['previous'])
    # Activity and score describe individuals when few people contribute.
    visible_activity = row['contributors'] >= MIN_DISPLAY
    payload = {
        'slug': community.tag.slug,
        'name': community.tag.name,
        'description': community.tagline or community.tag.description,
        'emoji': community.emoji,
        'color': community.color,
        'status': status,
        'members': released['members'],
        'engaged_members': released['engaged'],
        'growth': released['growth'] if status == 'active' else None,
        'score': row['score'] if visible_activity else None,
        'joke_count': row['joke_count'],
        'activity': row['activity'] if visible_activity else None,
        'explanation': _explanation(community, status, released['engaged'], viewer, viewer_ctx),
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
    released = _released(data)
    ctx = viewer_context(user)
    states = viewer_states(user, communities) if ctx else {}
    rows = [community_row(c, data, states.get(c.pk), ctx) for c in communities]
    rows.sort(key=lambda r: ({'active': 0, 'forming': 1, 'cooling': 2}[r['status']], -(r['score'] or 0), r['name']))
    slug_by_id = {c.pk: c.tag.slug for c in communities}
    bridges = sorted(
        ({'source': min(slug_by_id[a], slug_by_id[b]), 'target': max(slug_by_id[a], slug_by_id[b]),
          'members': shown}
         for a, b, shown in released['bridges'] if a in slug_by_id and b in slug_by_id),
        key=lambda bridge: (bridge['source'], bridge['target']),
    )
    return {
        'generated_at': data['generated_at'],
        'counts_date': released['day'],
        'stats': {
            'active_communities': sum(r['status'] == 'active' for r in rows),
            'forming_communities': sum(r['status'] == 'forming' for r in rows),
            'members': released['members'],
            'multi_community_members': released['multi_community'],
            'signals_7d': sum(sum(r['activity']) for r in rows if r['activity']),
        },
        'viewer': ctx and {**ctx, 'communities': [r['slug'] for r in rows if r['viewer'] and r['viewer']['member']]},
        'communities': rows,
        'bridges': bridges,
        'methodology': methodology(),
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
    for a, b, shown in _released(data)['bridges']:
        if community.pk not in (a, b):
            continue
        other = by_id.get(b if a == community.pk else a)
        if other:
            out.append({'slug': other.tag.slug, 'name': other.tag.name, 'emoji': other.emoji,
                        'color': other.color, 'members': shown})
    return sorted(out, key=lambda r: -r['members'])


def export_memberships(user):
    """Explicit join/leave choices for the GDPR export. Inferred affinity is not
    stored; it is recomputed from the reactions/saves/shares already exported
    (``CommunitySignal`` only mirrors those rows and is deleted with the account)."""
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
    the creator are counted, not identified, and every count is released with
    the same day-stable noise, rounding and suppression as public counts.
    """
    from creator_insights.services import resolve_creator_jokes

    now = timezone.now()
    day = now.date().isoformat()
    communities = listed_communities()
    data = daily_aggregate(day)
    creator_jokes = resolve_creator_jokes(user).filter(content_tier='tier_1')
    key = f'communities:creator-audience:{user.pk}:{day}'
    audience = cache.get(key)
    if audience is None:
        audience = set(
            signal_rows(now - timedelta(days=WINDOW_DAYS), jokes=creator_jokes.values('pk'), eligible=True,
                        exclude_user=user)
            .order_by().values_list('user_id', flat=True).distinct()
        )
        cache.set(key, audience, 26 * 3600)
    # Snapshot membership, but *current* eligibility: a withdrawal or deletion takes
    # effect immediately (numbers can only fall within the day, never rise).
    still_counted = set(privacy.established_users().values_list('pk', flat=True))
    audience = audience & still_counted
    your_jokes = dict(
        Joke.context_tags.through.objects.filter(
            joke_id__in=creator_jokes.values('pk'), contexttag_id__in=[c.tag_id for c in communities],
        ).values_list('contexttag_id').annotate(n=Count('joke_id', distinct=True))
    )
    rows = []
    for community in communities:
        base = community_row(community, data)
        # A creator is also a reader; their own membership never inflates their reach.
        members = (set(data['rows'].get(community.pk, {}).get('members', ())) & still_counted) - {user.pk}
        # Community size shares the public statistic's noise (it differs from it only
        # by the creator's own membership), so extra creator accounts get no fresh draws.
        shown_members = privacy.release(len(members), 'members', community.pk, day=day)
        shown_reached = privacy.release(len(members & audience), 'creator-reached', user.pk, community.pk, day=day)
        if shown_members is None or shown_reached is None:
            shown_reached = None
        else:
            shown_reached = min(shown_reached, shown_members)
        rows.append({
            **{k: base[k] for k in ('slug', 'name', 'emoji', 'color', 'status', 'joke_count')},
            'members': shown_members,
            'reached_members': shown_reached,
            'reach_rate': int(100 * shown_reached / shown_members) // 5 * 5 if shown_reached is not None else None,
            'your_jokes': your_jokes.get(community.tag_id, 0),
        })
    rows.sort(key=lambda r: (-(r['reached_members'] or 0), -(r['your_jokes']), r['name']))
    result = {
        'window_days': WINDOW_DAYS,
        'snapshot_date': day,
        'audience': {'size': privacy.release(len(audience), 'creator-audience', user.pk, day=day),
                     'minimum': MIN_DISPLAY},
        'communities': rows,
        'opportunities': _opportunities(rows, data, communities),
        'measurement_notes': [
            f'Audience = adults sharing analytics who laughed at, favorited, saved or shared one of your '
            f'jokes in the last {WINDOW_DAYS} days. Your own activity is excluded.',
            f'Only established accounts count: at least {settings.COMMUNITIES_ESTABLISHED_ACCOUNT_DAYS} days '
            f'old with {settings.COMMUNITIES_ESTABLISHED_MIN_JOKES}+ jokes enjoyed, so new or throwaway '
            'accounts cannot inflate or probe these numbers.',
            f'Counts are approximate: each carries a little random noise that stays fixed for the day, is '
            f'rounded to a multiple of {MIN_DISPLAY} and is hidden under {MIN_DISPLAY}, so no individual '
            'reader can be singled out.',
            'Refreshed once a day (UTC). Communities form from reader behaviour across all creators.',
            'Opportunities describe current evidence; they do not predict or guarantee reach.',
        ],
    }
    return result


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
