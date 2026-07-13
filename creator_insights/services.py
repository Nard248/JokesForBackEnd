"""
Creator Audience Intelligence — service layer.

Single public entry point: build_creator_insights(creator, period) -> dict.

All aggregation is on-read (no caching, no counters, no Celery).
Owner-scoped: resolve_creator_jokes() intentionally bypasses the content-tier
serving lock so a creator always sees all of their own content.
"""
from datetime import timedelta

from django.db.models import Avg, Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, ExtractHour
from django.utils import timezone

from jokes.models import (
    Joke, JokeView, JokeReaction, Favorite, SavedJoke, ShareEvent, JokeSubmission,
    JokeImpression, JokeDwell,
)
from follows.models import Follow
from jokes.identity import public_display_name, public_handle


# A dwell sample counts as a real "read" once it crosses this many milliseconds
# (vs. a brief glance). Used for read_rate / per-joke read_rate.
READ_THRESHOLD_MS = 4000
# A dwell sample with scroll_pct at/above this is treated as "completed"
# (read all the way through — most meaningful for story-format jokes).
COMPLETION_SCROLL_PCT = 90


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def resolve_creator_jokes(creator):
    """Return the creator's published jokes via the submission attribution join.

    Owner-scoped: the content-tier gate is intentionally bypassed so the creator
    can see all of their own jokes (including tier_2). Any future public/aggregate
    creator surface must restore allowed_tiers filtering.

    Isolating this in one function means swapping to a direct Joke.creator FK
    (slice 2) is a one-line change here.
    """
    return Joke.objects.filter(
        Q(creator=creator) |
        Q(creator__isnull=True, submission__user=creator, submission__status='published')
    ).distinct()


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
        # 'month' and any unrecognised value default to 29-day window.
        return today - timedelta(days=29)


# ---------------------------------------------------------------------------
# Section builders — all accept a QuerySet of jokes + an optional since date
# ---------------------------------------------------------------------------

def _overview(jokes, since):
    """Compute the headline KPI block."""
    # Count of published jokes (independent of period)
    published_jokes = jokes.count()

    # Base view queryset scoped to creator's jokes
    view_qs = JokeView.objects.filter(joke__in=jokes)
    if since:
        view_qs = view_qs.filter(viewed_date__gte=since)

    total_views = view_qs.count()
    reach = view_qs.values('user').distinct().count()
    revealed_views = view_qs.filter(revealed_punchline=True).count()
    payoff_rate = (revealed_views / total_views) if total_views else None

    # Impression / reach signal (audience telemetry, Phase 1).
    impression_qs = JokeImpression.objects.filter(joke__in=jokes)
    if since:
        impression_qs = impression_qs.filter(created_date__gte=since)
    impressions = impression_qs.count()
    unique_reach = impression_qs.values('user').distinct().count()
    # views ÷ impressions, null when no impressions, capped at 1.0.
    open_rate = min(total_views / impressions, 1.0) if impressions else None

    # Dwell / read-time signal (audience telemetry, Phase 2).
    dwell_qs = JokeDwell.objects.filter(joke__in=jokes)
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

    reaction_qs = JokeReaction.objects.filter(joke__in=jokes)
    if since:
        reaction_qs = reaction_qs.filter(created_at__date__gte=since)
    reactions = reaction_qs.count()

    fav_qs = Favorite.objects.filter(joke__in=jokes)
    if since:
        fav_qs = fav_qs.filter(created_at__date__gte=since)
    favorites = fav_qs.count()

    save_qs = SavedJoke.objects.filter(joke__in=jokes)
    if since:
        save_qs = save_qs.filter(created_at__date__gte=since)
    saves = save_qs.count()

    share_qs = ShareEvent.objects.filter(joke__in=jokes)
    if since:
        share_qs = share_qs.filter(created_at__date__gte=since)
    shares = share_qs.count()

    # Peak read hour (ExtractHour technique from TasteProfileView)
    peak = (
        view_qs.annotate(h=ExtractHour('viewed_at'))
        .values('h').annotate(n=Count('id')).order_by('-n').first()
    )
    peak_read_hour = peak['h'] if peak else None

    # 28-day daily view sparkline (same mapping as TasteProfileView.daily_reads_28d)
    today = timezone.now().date()
    start = today - timedelta(days=27)
    daily_counts = (
        view_qs.filter(viewed_date__gte=start)
        .values('viewed_date').annotate(c=Count('id'))
    )
    sparkline_map = {row['viewed_date']: row['c'] for row in daily_counts}
    daily_reach_28d = [sparkline_map.get(start + timedelta(days=i), 0) for i in range(28)]

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
    }


def _breakdowns(jokes, since):
    """Compute reactions, shares, and source breakdowns."""
    view_qs = JokeView.objects.filter(joke__in=jokes)
    if since:
        view_qs = view_qs.filter(viewed_date__gte=since)

    reaction_qs = JokeReaction.objects.filter(joke__in=jokes)
    if since:
        reaction_qs = reaction_qs.filter(created_at__date__gte=since)
    reactions_breakdown = list(
        reaction_qs.values('reaction').annotate(count=Count('id')).order_by('-count')
    )
    # Rename key to match API shape
    reactions_breakdown = [{'reaction': r['reaction'], 'count': r['count']} for r in reactions_breakdown]

    share_qs = ShareEvent.objects.filter(joke__in=jokes)
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
    rows = model.objects.filter(joke=OuterRef('pk'))
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


def _top_jokes(jokes, since):
    """Return top 10 jokes ordered by view count descending with per-joke metrics."""
    annotated = list(_annotated_top_jokes_qs(jokes, since)[:10])

    # Per-joke dwell metrics computed in a separate, dwell-only aggregation so the
    # multi-JOIN annotate above doesn't fan out / distort the averages.
    top_ids = [j.id for j in annotated]
    dwell_qs = JokeDwell.objects.filter(joke_id__in=top_ids)
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
        result.append({
            'id': j.id,
            'text': j.text,
            'views': vc,
            'impressions': j.impression_count,
            'reactions': j.reaction_count,
            'saves': j.save_count,
            'shares': j.share_count,
            'payoff_rate': round(pc / vc, 4) if vc else None,
            'avg_read_seconds': avg_read_seconds,
            'read_rate': read_rate,
        })
    return result


def _audience(jokes, since):
    """Compute audience taste composition from views of creator's jokes.

    Mirrors TasteProfileView top_themes/categories/formats but scoped to the
    creator's published jokes. Audience composition is aggregate/taste-based only —
    no individual identities are returned.
    """
    view_qs = JokeView.objects.filter(joke__in=jokes)
    if since:
        view_qs = view_qs.filter(viewed_date__gte=since)

    top_themes = list(
        view_qs.values('joke__context_tags__name')
        .exclude(joke__context_tags__name__isnull=True)
        .annotate(c=Count('id')).order_by('-c')[:8]
    )
    top_categories = list(
        view_qs.values('joke__tones__name')
        .exclude(joke__tones__name__isnull=True)
        .annotate(c=Count('id')).order_by('-c')[:8]
    )
    top_formats = list(
        view_qs.values('joke__format__name')
        .exclude(joke__format__name__isnull=True)
        .annotate(c=Count('id')).order_by('-c')[:5]
    )

    return {
        'top_themes': [{'label': r['joke__context_tags__name'], 'count': r['c']} for r in top_themes],
        'top_categories': [{'label': r['joke__tones__name'], 'count': r['c']} for r in top_categories],
        'top_formats': [{'label': r['joke__format__name'], 'count': r['c']} for r in top_formats],
    }


def _suggestions(creator, jokes, since):
    """Compute the three growth suggestion cards.

    1. peak_hour  — when creator's audience reads
    2. what_resonates — best tone/theme by reactions-per-view
    3. consistency — days since last published joke
    """
    view_qs = JokeView.objects.filter(joke__in=jokes)
    if since:
        view_qs = view_qs.filter(viewed_date__gte=since)

    # --- peak_hour card ---
    peak = (
        view_qs.annotate(h=ExtractHour('viewed_at'))
        .values('h').annotate(n=Count('id')).order_by('-n').first()
    )
    peak_hour = peak['h'] if peak else None

    if peak_hour is not None:
        peak_title = f'Publish around {peak_hour}:00'
        peak_detail = (
            f'Your readers are most active around {peak_hour}:00 — '
            'that\'s your best window to share new jokes.'
        )
    else:
        peak_title = 'Post regularly to discover your peak hour'
        peak_detail = 'We\'ll show your audience\'s peak reading time once you have more views.'

    suggestions = [
        {
            'kind': 'peak_hour',
            'title': peak_title,
            'detail': peak_detail,
            'data': {'hour': peak_hour},
        }
    ]

    # --- what_resonates card ---
    # For each tone of creator's jokes, compute reactions-per-view
    # Best tone by (reactions on jokes with that tone) / (views on jokes with that tone)
    tone_stats = (
        view_qs.values('joke__tones__name')
        .exclude(joke__tones__name__isnull=True)
        .annotate(
            # distinct=True prevents fan-out when the reactions JOIN multiplies view rows
            views=Count('id', distinct=True),
            # period-filter reactions so numerator and denominator cover the same window
            reactions=Count(
                'joke__reactions_v2',
                filter=(
                    Q(
                        joke__reactions_v2__isnull=False,
                        joke__reactions_v2__created_at__date__gte=since,
                    )
                    if since
                    else Q(joke__reactions_v2__isnull=False)
                ),
                distinct=True,
            ),
        )
        .order_by('-views')
    )

    best_tone = None
    best_rate = -1
    for row in tone_stats:
        if row['views'] > 0:
            rate = row['reactions'] / row['views']
            if rate > best_rate:
                best_rate = rate
                best_tone = row['joke__tones__name']

    if best_tone:
        resonates_title = f'Your {best_tone} jokes resonate most'
        resonates_detail = (
            f'Jokes tagged "{best_tone}" get the highest reaction rate — '
            'consider creating more in this style.'
        )
        resonates_data = {'top_tone': best_tone, 'reactions_per_view': round(best_rate, 4)}
    else:
        resonates_title = 'Add reactions to discover what resonates'
        resonates_detail = 'Once your audience reacts to your jokes, we\'ll surface your strongest style.'
        resonates_data = {'top_tone': None, 'reactions_per_view': None}

    suggestions.append({
        'kind': 'what_resonates',
        'title': resonates_title,
        'detail': resonates_detail,
        'data': resonates_data,
    })

    # --- consistency card ---
    last_sub = (
        JokeSubmission.objects.filter(user=creator, status='published')
        .order_by('-updated_at').first()
    )
    if last_sub:
        days_since = (timezone.now().date() - last_sub.updated_at.date()).days
    else:
        days_since = None

    if days_since is None:
        consistency_title = 'Publish your first joke!'
        consistency_detail = 'Creators who post 3–5× per week grow their audience fastest.'
    elif days_since == 0:
        consistency_title = 'Great — you published today!'
        consistency_detail = 'Creators who post 3–5× per week grow their audience fastest.'
    elif days_since <= 3:
        consistency_title = f'Published {days_since} day{"s" if days_since != 1 else ""} ago — keep it up!'
        consistency_detail = 'Creators who post 3–5× per week grow their audience fastest.'
    else:
        consistency_title = f'It\'s been {days_since} days since your last joke'
        consistency_detail = (
            f'You haven\'t published in {days_since} days. '
            'Creators who post 3–5× per week grow their audience fastest.'
        )

    suggestions.append({
        'kind': 'consistency',
        'title': consistency_title,
        'detail': consistency_detail,
        'data': {'days_since': days_since},
    })

    return suggestions


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_creator_insights(creator, period):
    """Build the full creator insights dict for the given creator and period.

    Returns a plain dict (no DRF coupling); the view serialises it to Response.
    """
    normalised_period = period if period in ('week', 'month', 'all') else 'month'
    since = window_since(normalised_period)
    jokes = resolve_creator_jokes(creator)

    overview = _overview(jokes, since)
    reactions_breakdown, shares_breakdown, source_mix = _breakdowns(jokes, since)
    top_jokes = _top_jokes(jokes, since)
    audience = _audience(jokes, since)
    suggestions = _suggestions(creator, jokes, since)

    # Follower stats (injected after _overview so the function signature stays stable)
    today = timezone.now().date()
    bf_start = today - timedelta(days=27)
    overview['followers'] = Follow.objects.filter(creator=creator).count()
    follow_counts = (
        Follow.objects.filter(creator=creator, created_at__date__gte=bf_start)
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
