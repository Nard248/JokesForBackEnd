"""
Creator Audience Intelligence — service layer.

Single public entry point: build_creator_insights(creator, period) -> dict.

All aggregation is on-read (no caching, no counters, no Celery).
Owner-scoped: resolve_creator_jokes() intentionally bypasses the content-tier
serving lock so a creator always sees all of their own content.
"""
from datetime import timedelta

from django.db.models import Avg, Count, Exists, F, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, ExtractHour
from django.utils import timezone

from creator_insights.privacy import eligible_analytics_users, since_latest_opt_in
from follows.models import Follow
from jokes.identity import public_display_name, public_handle
from jokes.models import (
    Favorite,
    Joke,
    JokeDwell,
    JokeImpression,
    JokeMedia,
    JokeReaction,
    JokeView,
    JokeWatch,
    SavedJoke,
    ShareEvent,
)
from jokes.serving import BASE_TIERS

# A dwell sample meets the duration threshold at four seconds. This is an
# observation threshold, not proof the viewer read or understood the content.
READ_THRESHOLD_MS = 4000
# A supplied scroll percentage at/above this meets the depth threshold.
COMPLETION_SCROLL_PCT = 90
# A supplied playback percentage at/above this meets the completion threshold.
WATCH_COMPLETION_PCT = 90
MIN_AUDIENCE_SIZE = 20


# When each counted event happened, for the consent cutoff and raw retention.
EVENT_TIMESTAMPS = {
    JokeView: 'viewed_at', JokeImpression: 'created_at', JokeDwell: 'created_at',
    JokeWatch: 'watched_at', JokeReaction: 'created_at', Favorite: 'created_at',
    SavedJoke: 'created_at', ShareEvent: 'created_at',
}
RAW_TELEMETRY = (JokeImpression, JokeDwell, JokeWatch)


def _eligible_events(model):
    """Currently consenting adults' events since their latest opt-in, minus creator previews.

    The eligible-user subquery and the opt-in cutoff are evaluated by
    PostgreSQL with the aggregate, so withdrawal takes effect on the next
    request without a user-ID cache, and activity from before an opt-in never
    counts (the same rule as community aggregates).
    """
    timestamp = EVENT_TIMESTAMPS[model]
    events = since_latest_opt_in(model.objects.filter(user__in=eligible_analytics_users()), timestamp)
    # The raw retention window applies immediately, including while bounded
    # physical cleanup is catching up. Operational reading/action history has
    # a separate purpose and is deliberately not aged out here.
    if model in RAW_TELEMETRY:
        from jokes.telemetry import RETENTION_DAYS
        events = events.filter(**{f'{timestamp}__gte': timezone.now() - timedelta(days=RETENTION_DAYS)})
    return events.exclude(
        joke__creator__isnull=False, user_id=F('joke__creator_id'),
    ).exclude(
        joke__creator__isnull=True, joke__submission__isnull=False,
        joke__submission__status='published', user_id=F('joke__submission__user_id'),
    )


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def resolve_creator_jokes(creator):
    """Return published jokes attributed by creator FK or legacy submission.

    Owner metrics may include tier_2 material even when its text is unavailable
    to the current account. Callers that serve content must separately apply
    allowed_tiers or redact inaccessible text. Tier_3 and removed rows are
    excluded even from this owner scope.
    """
    return Joke.objects.filter(
        Q(creator=creator) |
        Q(creator__isnull=True, submission__user=creator, submission__status='published')
    ).exclude(content_tier='tier_3').distinct()


def window_since(period):
    """Return the start date for the requested analytics period, or None for 'all'.

    Mirrors TasteProfileView's period logic exactly so UX and backend stay in sync.
    """
    today = timezone.now().date()
    if period == 'week':
        return today - timedelta(days=6)
    elif period == 'all':
        return None
    else:
        # Thirty inclusive UTC dates, including today.
        return today - timedelta(days=29)


# ---------------------------------------------------------------------------
# Section builders — all accept a QuerySet of jokes + an optional since date
# ---------------------------------------------------------------------------

def _overview(jokes, since):
    """Compute the headline KPI block."""
    # Count of published jokes (independent of period)
    published_jokes = jokes.count()

    # Base view queryset scoped to creator's jokes
    view_qs = _eligible_events(JokeView).filter(joke__in=jokes)
    if since:
        view_qs = view_qs.filter(viewed_date__gte=since)

    total_views = view_qs.count()
    reach = view_qs.values('user').distinct().count()
    revealed_views = view_qs.filter(revealed_punchline=True).count()
    payoff_rate = (revealed_views / total_views) if total_views else None

    # Impression / reach signal (audience telemetry, Phase 1).
    impression_qs = _eligible_events(JokeImpression).filter(joke__in=jokes)
    if since:
        impression_qs = impression_qs.filter(created_date__gte=since)
    impressions = impression_qs.count()
    unique_reach = impression_qs.values('user').distinct().count()
    # Count each impression identity once if a same-user/joke/day view exists.
    # This is an observed same-day match, not proof the impression caused a read.
    matched_views = view_qs.filter(
        user_id=OuterRef('user_id'), joke_id=OuterRef('joke_id'),
        viewed_date=OuterRef('created_date'),
    )
    matched_impressions = impression_qs.filter(Exists(matched_views)).count()
    open_rate = matched_impressions / impressions if impressions else None

    # Dwell / read-time signal (audience telemetry, Phase 2).
    dwell_qs = _eligible_events(JokeDwell).filter(joke__in=jokes)
    if since:
        dwell_qs = dwell_qs.filter(created_date__gte=since)
    dwell_total = dwell_qs.count()
    if dwell_total:
        avg_ms = dwell_qs.aggregate(a=Avg('dwell_ms'))['a']
        avg_read_seconds = round(avg_ms / 1000, 2) if avg_ms is not None else None
        reads = dwell_qs.filter(dwell_ms__gte=READ_THRESHOLD_MS).count()
        read_rate = round(reads / dwell_total, 4)
    else:
        avg_read_seconds = None
        read_rate = None
    # completion_rate is only defined over dwell rows that carry scroll_pct.
    scroll_total = dwell_qs.filter(scroll_pct__isnull=False).count()
    if scroll_total:
        completed = dwell_qs.filter(scroll_pct__gte=COMPLETION_SCROLL_PCT).count()
        completion_rate = round(completed / scroll_total, 4)
    else:
        completion_rate = None

    reaction_qs = _eligible_events(JokeReaction).filter(joke__in=jokes)
    if since:
        reaction_qs = reaction_qs.filter(created_at__date__gte=since)
    reactions = reaction_qs.count()

    fav_qs = _eligible_events(Favorite).filter(joke__in=jokes)
    if since:
        fav_qs = fav_qs.filter(created_at__date__gte=since)
    favorites = fav_qs.count()

    save_qs = _eligible_events(SavedJoke).filter(joke__in=jokes)
    if since:
        save_qs = save_qs.filter(created_at__date__gte=since)
    saves = save_qs.count()

    share_qs = _eligible_events(ShareEvent).filter(joke__in=jokes)
    if since:
        share_qs = share_qs.filter(created_at__date__gte=since)
    shares = share_qs.count()

    # Peak read hour (ExtractHour technique from TasteProfileView)
    peak = (
        view_qs.annotate(h=ExtractHour('viewed_at'))
        .values('h').annotate(n=Count('id')).order_by('-n').first()
    )
    peak_read_hour = peak['h'] if peak else None

    # Full 28-date series, independent of the selected headline period.
    today = timezone.now().date()
    start = today - timedelta(days=27)
    daily_counts = (
        _eligible_events(JokeView).filter(
            joke__in=jokes, viewed_date__gte=start, viewed_date__lte=today,
        ).values('viewed_date').annotate(views=Count('id'), reach=Count('user_id', distinct=True))
    )
    sparkline_map = {row['viewed_date']: row for row in daily_counts}
    daily_reach_28d = [sparkline_map.get(start + timedelta(days=i), {}).get('reach', 0) for i in range(28)]
    daily_views_28d = [sparkline_map.get(start + timedelta(days=i), {}).get('views', 0) for i in range(28)]

    return {
        'published_jokes': published_jokes,
        'reach': reach,
        'views': total_views,
        'impressions': impressions,
        'unique_reach': unique_reach,
        'open_rate': open_rate,
        'payoff_rate': payoff_rate,
        'avg_read_seconds': avg_read_seconds,
        'read_rate': read_rate,
        'completion_rate': completion_rate,
        'reactions': reactions,
        'favorites': favorites,
        'saves': saves,
        'shares': shares,
        'peak_read_hour': peak_read_hour,
        'daily_reach_28d': daily_reach_28d,
        'daily_views_28d': daily_views_28d,
        'dwell_samples': dwell_total,
    }


def _breakdowns(jokes, since):
    """Compute reactions, shares, and source breakdowns."""
    view_qs = _eligible_events(JokeView).filter(joke__in=jokes)
    if since:
        view_qs = view_qs.filter(viewed_date__gte=since)

    reaction_qs = _eligible_events(JokeReaction).filter(joke__in=jokes)
    if since:
        reaction_qs = reaction_qs.filter(created_at__date__gte=since)
    reactions_breakdown = list(
        reaction_qs.values('reaction').annotate(count=Count('id')).order_by('-count')
    )
    # Rename key to match API shape
    reactions_breakdown = [{'reaction': r['reaction'], 'count': r['count']} for r in reactions_breakdown]

    share_qs = _eligible_events(ShareEvent).filter(joke__in=jokes)
    if since:
        share_qs = share_qs.filter(created_at__date__gte=since)
    shares_breakdown = list(
        share_qs.values('platform').annotate(count=Count('id')).order_by('-count')
    )
    shares_breakdown = [{'platform': r['platform'], 'count': r['count']} for r in shares_breakdown]

    source_mix = list(
        view_qs.values('source').annotate(count=Count('id')).order_by('-count')
    )
    source_mix = [{'source': r['source'], 'count': r['count']} for r in source_mix]

    return reactions_breakdown, shares_breakdown, source_mix


def _joke_count_subquery(model, since_q=None, extra_q=None):
    """Correlated subquery: number of ``model`` rows attached to the OuterRef joke.

    Each metric is computed as its own scalar subquery so the top-jokes query
    NEVER LEFT-JOINs several relations at once. Stacking multiple
    ``Count(rel, distinct=True)`` over different relations in a single annotate()
    makes Postgres materialise the cartesian product of every joined relation
    per joke before DISTINCT de-dupes (cost ~ views×reactions×saves×shares×
    impressions) — a real timeout for a successful creator. Correlated subqueries
    keep each count independent, so the DB never builds that product.

    The value is identical to the old ``Count(rel, distinct=True)``: a single
    relation join has one row per related object, so a plain COUNT of that
    relation equals the DISTINCT count. Coalesce keeps the empty case at 0.
    """
    rows = _eligible_events(model).filter(joke=OuterRef('pk'))
    if extra_q is not None:
        rows = rows.filter(extra_q)
    if since_q is not None:
        rows = rows.filter(since_q)
    counted = rows.order_by().values('joke').annotate(c=Count('id')).values('c')
    return Coalesce(Subquery(counted, output_field=IntegerField()), 0)


def _annotated_top_jokes_qs(jokes, since):
    """Annotate the creator's jokes with per-joke count metrics via correlated
    subqueries (one scalar subquery per relation — no multi-relation JOIN
    fan-out), ordered by view count descending.

    Values match the previous ``Count(rel, distinct=True)`` annotate exactly and
    reaction/save/share/impression counts stay period-filtered when ``since`` is
    set (all-time when it is None).
    """
    return jokes.annotate(
        view_count=_joke_count_subquery(
            JokeView, since_q=Q(viewed_date__gte=since) if since else None,
        ),
        reaction_count=_joke_count_subquery(
            JokeReaction, since_q=Q(created_at__date__gte=since) if since else None,
        ),
        save_count=_joke_count_subquery(
            SavedJoke, since_q=Q(created_at__date__gte=since) if since else None,
        ),
        share_count=_joke_count_subquery(
            ShareEvent, since_q=Q(created_at__date__gte=since) if since else None,
        ),
        payoff_count=_joke_count_subquery(
            JokeView,
            since_q=Q(viewed_date__gte=since) if since else None,
            extra_q=Q(revealed_punchline=True),
        ),
        impression_count=_joke_count_subquery(
            JokeImpression, since_q=Q(created_date__gte=since) if since else None,
        ),
    ).order_by('-view_count')


def _top_jokes(jokes, since, *, allowed_content_tiers=None):
    """Top 10 owner metrics, withholding text outside requester content access."""
    if allowed_content_tiers is None:
        allowed_content_tiers = BASE_TIERS
    annotated = list(_annotated_top_jokes_qs(jokes, since)[:10])

    # Per-joke dwell metrics computed in a separate, dwell-only aggregation so the
    # multi-JOIN annotate above doesn't fan out / distort the averages.
    top_ids = [j.id for j in annotated]
    dwell_qs = _eligible_events(JokeDwell).filter(joke_id__in=top_ids)
    if since:
        dwell_qs = dwell_qs.filter(created_date__gte=since)
    dwell_by_joke = {
        row['joke_id']: row
        for row in dwell_qs.values('joke_id').annotate(
            avg_ms=Avg('dwell_ms'),
            total=Count('id'),
            reads=Count('id', filter=Q(dwell_ms__gte=READ_THRESHOLD_MS)),
        )
    }

    # Watch-time metrics (Wave 2 media telemetry), same separate-aggregation
    # style as dwell above. Only meaningful for jokes whose media includes a
    # video/audio asset — text/image jokes never accrue JokeWatch rows, so
    # this is provably a no-op for them.
    media_joke_ids = set(
        JokeMedia.objects.filter(
            joke_id__in=top_ids, asset__kind__in=('video', 'audio'),
        ).values_list('joke_id', flat=True).distinct()
    )
    watch_qs = _eligible_events(JokeWatch).filter(joke_id__in=top_ids)
    if since:
        watch_qs = watch_qs.filter(watched_at__date__gte=since)
    watch_by_joke = {
        row['joke_id']: row
        for row in watch_qs.values('joke_id').annotate(
            avg_ms=Avg('watch_ms'),
            total=Count('id'),
            pct_total=Count('id', filter=Q(watch_pct__isnull=False)),
            pct_completed=Count('id', filter=Q(watch_pct__gte=WATCH_COMPLETION_PCT)),
        )
    }

    result = []
    for j in annotated:
        vc = j.view_count
        pc = j.payoff_count
        d = dwell_by_joke.get(j.id)
        if d and d['total']:
            avg_read_seconds = round(d['avg_ms'] / 1000, 2) if d['avg_ms'] is not None else None
            read_rate = round(d['reads'] / d['total'], 4)
        else:
            avg_read_seconds = None
            read_rate = None

        w = watch_by_joke.get(j.id) if j.id in media_joke_ids else None
        if w and w['total']:
            avg_watch_seconds = round(w['avg_ms'] / 1000, 2) if w['avg_ms'] is not None else None
        else:
            avg_watch_seconds = None
        if w and w['pct_total']:
            watch_completion_rate = round(w['pct_completed'] / w['pct_total'], 4)
        else:
            watch_completion_rate = None

        result.append({
            'id': j.id,
            'text': j.text if j.content_tier in allowed_content_tiers else '',
            'content_available': j.content_tier in allowed_content_tiers,
            'views': vc,
            'impressions': j.impression_count,
            'reactions': j.reaction_count,
            'saves': j.save_count,
            'shares': j.share_count,
            'payoff_rate': round(pc / vc, 4) if vc else None,
            'avg_read_seconds': avg_read_seconds,
            'read_rate': read_rate,
            'avg_watch_seconds': avg_watch_seconds,
            'watch_completion_rate': watch_completion_rate,
        })
    return result


def _audience(jokes, since):
    """Viewed content composition; suppress each group under 20 distinct adults."""
    views = _eligible_events(JokeView).filter(joke__in=jokes)
    if since:
        views = views.filter(viewed_date__gte=since)
    sample_size = views.values('user_id').distinct().count()
    result = {
        'top_themes': [], 'top_categories': [], 'top_formats': [],
        'sample_size': sample_size, 'minimum_sample_size': MIN_AUDIENCE_SIZE,
        'suppressed': sample_size < MIN_AUDIENCE_SIZE,
    }
    if result['suppressed']:
        return result
    for key, relation, limit in (
        ('top_themes', 'joke__context_tags__name', 8),
        ('top_categories', 'joke__tones__name', 8),
        ('top_formats', 'joke__format__name', 5),
    ):
        rows = (views.values(relation).exclude(**{relation + '__isnull': True})
                .annotate(c=Count('id'), audience_size=Count('user_id', distinct=True))
                .filter(audience_size__gte=MIN_AUDIENCE_SIZE).order_by('-c', relation)[:limit])
        result[key] = [
            {'label': row[relation], 'count': row['c'], 'sample_size': row['audience_size']}
            for row in rows
        ]
    return result


def _suggestions(creator, jokes, since):
    """Descriptive observations with sample evidence, never growth guarantees."""
    views = _eligible_events(JokeView).filter(joke__in=jokes)
    reactions = _eligible_events(JokeReaction).filter(joke__in=jokes)
    if since:
        views = views.filter(viewed_date__gte=since)
        reactions = reactions.filter(created_at__date__gte=since)
    sample_size = views.values('user_id').distinct().count()
    enough = sample_size >= MIN_AUDIENCE_SIZE
    peak = (views.annotate(h=ExtractHour('viewed_at')).values('h')
            .annotate(n=Count('id')).order_by('-n', 'h').first()) if enough else None
    hour = peak['h'] if peak else None
    suggestions = [{
        'kind': 'peak_hour',
        'title': f'Most recorded views were near {hour}:00 UTC' if peak else 'More readers needed for timing suggestions',
        'detail': ('Try a post around this hour and compare future results; this describes past views, '
                   'not a proven best publishing time.') if peak else
                  'Timing observations need at least 20 distinct consenting adult readers.',
        'data': {'hour': hour, 'sample_size': sample_size, 'minimum_sample_size': MIN_AUDIENCE_SIZE,
                 'status': 'observed' if peak else 'insufficient_data'},
    }]
    tone_stats = []
    if enough:
        # Separate aggregates avoid materializing views × reactions per joke.
        reactions_by_tone = {
            row['joke__tones__name']: row['reactions']
            for row in reactions.values('joke__tones__name').annotate(reactions=Count('id'))
        }
        for row in (views.values('joke__tones__name').exclude(joke__tones__name__isnull=True)
                    .annotate(views=Count('id'), audience_size=Count('user_id', distinct=True))
                    .filter(audience_size__gte=MIN_AUDIENCE_SIZE).order_by('joke__tones__name')):
            row['reactions'] = reactions_by_tone.get(row['joke__tones__name'], 0)
            if row['reactions']:
                tone_stats.append(row)
    best = max(tone_stats, key=lambda row: row['reactions'] / row['views'], default=None)
    suggestions.append({
        'kind': 'what_resonates',
        'title': f"Your {best['joke__tones__name']} jokes have the strongest recorded reaction ratio" if best
                 else 'More evidence needed to compare styles',
        'detail': ('Consider another joke in this style. This compares retained reactions per recorded view; '
                   'it is a descriptive hypothesis, not a conversion rate or growth forecast.') if best else
                  'A style needs at least 20 distinct consenting adult readers and a reaction before comparison.',
        'data': {'top_tone': best['joke__tones__name'] if best else None,
                 'reactions_per_view': round(best['reactions'] / best['views'], 4) if best else None,
                 'sample_size': best['audience_size'] if best else sample_size,
                 'minimum_sample_size': MIN_AUDIENCE_SIZE,
                 'views': best['views'] if best else None,
                 'reactions': best['reactions'] if best else None,
                 'status': 'observed' if best else 'insufficient_data'},
    })
    latest = jokes.order_by('-created_at', '-pk').values_list('created_at', flat=True).first()
    days_since = (timezone.now().date() - latest.date()).days if latest else None
    suggestions.append({
        'kind': 'consistency',
        'title': f'Latest published content was added {days_since} days ago' if latest else 'Publish your first joke',
        'detail': 'Choose a posting schedule you can maintain. Publication timing alone does not establish audience growth.',
        'data': {'days_since': days_since, 'status': 'observed' if latest else 'insufficient_data'},
    })
    return suggestions


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_creator_insights(creator, period, *, allowed_content_tiers=None):
    """Build the full creator insights dict for the given creator and period.

    Returns a plain dict (no DRF coupling); the view serialises it to Response.
    Text defaults to the safe tier_1 scope unless requester tiers are supplied.
    """
    normalised_period = period if period in ('week', 'month', 'all') else 'month'
    since = window_since(normalised_period)
    jokes = resolve_creator_jokes(creator)

    overview = _overview(jokes, since)
    reactions_breakdown, shares_breakdown, source_mix = _breakdowns(jokes, since)
    top_jokes = _top_jokes(jokes, since, allowed_content_tiers=allowed_content_tiers)
    audience = _audience(jokes, since)
    suggestions = _suggestions(creator, jokes, since)

    # Follower stats (injected after _overview so the function signature stays stable)
    today = timezone.now().date()
    bf_start = today - timedelta(days=27)
    follows = since_latest_opt_in(
        Follow.objects.filter(creator=creator, follower__in=eligible_analytics_users().exclude(pk=creator.pk)),
        'created_at', user_field='follower_id',
    )
    overview['followers'] = follows.count()
    follow_counts = (
        follows.filter(created_at__date__gte=bf_start, created_at__date__lte=today)
        .values('created_at__date').annotate(c=Count('id'))
    )
    follow_map = {row['created_at__date']: row['c'] for row in follow_counts}
    overview['follower_growth_28d'] = [
        follow_map.get(bf_start + timedelta(days=i), 0) for i in range(28)
    ]

    return {
        'period': normalised_period,
        'is_creator': True,
        'overview': overview,
        'reactions_breakdown': reactions_breakdown,
        'shares_breakdown': shares_breakdown,
        'source_mix': source_mix,
        'top_jokes': top_jokes,
        'audience': audience,
        'suggestions': suggestions,
        'sample_coverage': {
            'eligible_viewers': overview['reach'],
            'impression_viewers': overview['unique_reach'],
            'dwell_samples': overview['dwell_samples'],
            'audience_minimum': MIN_AUDIENCE_SIZE,
        },
        'measurement_notes': {
            'population': ('Currently consenting adults only, counting only activity recorded at or after each '
                           "person's latest analytics opt-in; creator self-interactions excluded. This is not total audience."),
            'views': ('Recorded opens/reveals since each reader\'s latest analytics opt-in; repeats may count after the '
                      'debounce window.'),
            'open_rate': 'Fraction of daily user/joke impressions with a same-user/joke/day open or reveal, not an attributed causal conversion.',
            'attention': 'Optional client dwell/playback samples, not proof of attention. Averages are per sample/segment, not per reader or session. Coverage varies by client; native completeness is not established. Missing playback/scroll completion is unknown, not zero.',
            'retention': 'Optional impressions, dwell and playback cover the most recent 90 days. Operational opens and surviving engagement edges have separate history; longer periods do not imply equal coverage.',
            'anonymous': 'Anonymous readers and shares are excluded; no anonymous audience identifier is collected.',
            'engagement': ('Reactions, favorites and saves are surviving edges created in the window and after the '
                           "person's latest opt-in; removals rewrite historical totals."),
            'followers': ('Consenting adult followers who followed after their latest opt-in. Growth series counts '
                          'surviving follows by creation date, not gains or net growth.'),
            'shares': 'Recorded share initiations, not confirmed downstream consumption.',
            'audience': 'Viewed content tags, not demographic or cross-creator preferences; groups below 20 readers are suppressed.',
            'time_zone': 'UTC; week is 7 inclusive dates, month is 30, daily series always spans 28 dates.',
        },
    }


def resolve_creator_published_jokes_for_viewer(creator, tiers):
    """Return the creator's published jokes visible to a viewer with the given tiers.

    Public surface: re-applies the content-tier serving lock (the explicit inverse
    of owner-scoped resolve_creator_jokes). Uses the Joke.creator FK with the same
    submission-join fallback for null-creator (legacy) rows. Ordered newest-first.
    """
    return Joke.objects.filter(
        Q(creator=creator) |
        Q(creator__isnull=True, submission__user=creator, submission__status='published')
    ).filter(content_tier__in=tiers).distinct().order_by('-created_at')


def build_creator_profile(creator, viewer, tiers):
    """Build the public creator profile dict (identity + counts + is_following).

    Args:
        creator: the User whose profile is being viewed
        viewer: the requesting User (or None for anonymous)
        tiers: frozenset of allowed content_tier values for the viewer

    Returns a plain dict and the visible-jokes queryset as (data, jokes_qs).
    The caller 404s if data is None. The jokes_qs is tier-filtered for the viewer
    and meant to be serialized + paginated by the view.
    """
    jokes = resolve_creator_published_jokes_for_viewer(creator, tiers)

    total_published = jokes.count()
    if total_published == 0:
        return None, None

    follower_count = Follow.objects.filter(creator=creator).count()

    is_following = None
    if viewer and viewer.is_authenticated and viewer.pk != creator.pk:
        is_following = Follow.objects.filter(follower=viewer, creator=creator).exists()

    # Public identity via the shared helper (chosen handle/name, never email).
    display_name = public_display_name(creator)
    handle = public_handle(creator)

    data = {
        'id': creator.pk,
        'display_name': display_name,
        'handle': handle,
        'published_jokes': total_published,
        'follower_count': follower_count,
        'is_following': is_following,
    }
    return data, jokes
