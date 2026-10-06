from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import models
from django.db.models import Case, Count, F, Func, IntegerField, Q, Value, When

from .search import normalize_search_query

# Editorial publication gate. An allow-list, so any status that is not
# explicitly published (today: 'generated', an unscreened AI draft) is HELD and
# never reaches a reader. Fail-closed: a future status is held until added here.
PUBLISHED_EDITORIAL_STATUSES = ('legacy', 'ai_screened', 'native_reviewed')
# Human-written or human-reviewed content ranks ahead of AI-screened content
# wherever recency is the default order or a tie-break.
HUMAN_EDITORIAL_STATUSES = ('legacy', 'native_reviewed')


def live_joke_q(prefix=''):
    """Q for jokes a reader may be served: not taken down and not editorially held.

    ``prefix`` addresses the joke through a relation (``'joke__'``,
    ``'jokes__'``) for read paths that do not go through ``Joke.objects``:
    forward FK traversals, reverse-relation aggregates and through tables.
    """
    return Q(**{
        f'{prefix}is_removed': False,
        f'{prefix}editorial_status__in': PUBLISHED_EDITORIAL_STATUSES,
    })


def human_first_rank():
    """0 for human-written/reviewed jokes, 1 for AI-authored ones (sort ascending)."""
    return Case(
        When(editorial_status__in=HUMAN_EDITORIAL_STATUSES, then=Value(0)),
        default=Value(1), output_field=IntegerField(),
    )


def prefer_human(queryset):
    """Narrow a selection pool to human content when any exists, else keep it whole."""
    human = queryset.filter(editorial_status__in=HUMAN_EDITORIAL_STATUSES)
    return human if human.exists() else queryset


class JokeManager(models.Manager):
    """Custom manager for Joke model with full-text search capabilities.

    Takedowns and editorial holds are global: get_queryset() excludes
    is_removed=True and every unpublished editorial status (see
    ``live_joke_q``), so a moderated or held joke never serves through the
    default manager on ANY read path. Admin and moderation use
    `Joke.all_objects` (unfiltered) to view, review, publish or restore them.
    """

    def get_queryset(self):
        return super().get_queryset().filter(live_joke_q())

    def search(self, query_text=None, filters=None, ordering=None, allowed_tiers=None):
        """
        Full-text search with optional filters and ordering.

        Args:
            query_text: Search string (optional - if empty, returns all)
            filters: Dict with optional keys:
                - format: slug string
                - age_rating: slug string
                - tones: list of slug strings
                - context_tags: list of slug strings
                - culture_tags: list of slug strings
                - language: code string
            ordering: Sort order string (optional):
                - '-created_at': newest first (pure recency, explicit choice)
                - 'popularity': by likes + saves descending
                - 'relevance': by search rank (default when query_text present)
                - None: auto-select (relevance if searching, human content
                  first then newest otherwise)

        Returns:
            QuerySet ordered by the specified ordering
        """
        qs = self.get_queryset()

        # Content-tier serving lock: filter to allowed tiers when caller provides them.
        # (None means no tier filter — e.g. admin/internal callers.)
        if allowed_tiers is not None:
            qs = qs.filter(content_tier__in=allowed_tiers)

        # Each language uses one consistent parser for both matching and rank.
        # OR-ing English/simple matches for the same row breaks exclusions.
        query_text = normalize_search_query(query_text)
        has_query = bool(query_text)
        if has_query:
            query = SearchQuery(query_text, search_type='websearch', config='english')
            simple_query = SearchQuery(query_text, search_type='websearch', config='simple')
            qs = qs.alias(
                _search_tree=Func(query, function='querytree', output_field=models.TextField()),
                _simple_search_tree=Func(
                    simple_query, function='querytree', output_field=models.TextField(),
                ),
            ).annotate(rank=Case(
                When(language__code='en', then=SearchRank(F('search_vector'), query)),
                default=SearchRank(F('search_vector_simple'), simple_query),
            )).filter(
                (Q(language__code='en', search_vector=query) & ~Q(_search_tree__in=['', 'T']))
                | (~Q(language__code='en') & Q(search_vector_simple=simple_query)
                   & ~Q(_simple_search_tree__in=['', 'T']))
            )

        # Apply filters
        if filters:
            if filters.get('format'):
                # Accept one slug or a comma-separated list, matching the
                # tone/context/culture axes below. Explore lets a reader stack
                # formats; an exact match here turned any multi-select into an
                # empty feed instead of a union.
                fmt = filters['format']
                fmt_slugs = fmt if isinstance(fmt, (list, tuple, set)) else [
                    s.strip() for s in str(fmt).split(',') if s.strip()
                ]
                qs = qs.filter(format__slug__in=fmt_slugs)
            if filters.get('age_rating'):
                qs = qs.filter(age_rating__slug=filters['age_rating'])
            if filters.get('tones'):
                qs = qs.filter(tones__slug__in=filters['tones'])
            if filters.get('context_tags'):
                qs = qs.filter(context_tags__slug__in=filters['context_tags'])
            if filters.get('culture_tags'):
                qs = qs.filter(culture_tags__slug__in=filters['culture_tags'])
            if filters.get('language'):
                qs = qs.filter(language__code=str(filters['language']).lower())
            if filters.get('country'):
                qs = qs.filter(countries__code=str(filters['country']).upper())

        # Apply ordering. Human-written/reviewed jokes (human_rank=0) rank
        # ahead of AI-screened ones in the default browse order and in every
        # tie-break; an explicit '-created_at' is honored as pure recency.
        qs = qs.annotate(human_rank=human_first_rank())
        if ordering == 'popularity' or ordering == '-popularity':
            qs = qs.annotate(
                like_count=Count('ratings', filter=Q(ratings__rating=1)),
                save_count=Count('saved_by'),
            ).order_by('-like_count', '-save_count', 'human_rank', '-created_at', '-pk')
        elif ordering == '-created_at':
            qs = qs.order_by('-created_at', '-pk')
        elif has_query:
            # Default when searching (and explicit 'relevance'): order by rank
            qs = qs.order_by('-rank', 'human_rank', '-created_at', '-pk')
        else:
            # Default when browsing: human content first, then newest
            qs = qs.order_by('human_rank', '-created_at', '-pk')

        # Only to-many filter joins can duplicate jokes. Avoid forcing a wide
        # DISTINCT/Unique sort (including both vectors) for ordinary searches;
        # PostgreSQL can then use a cheap count and top-N relevance sort.
        if filters and any(filters.get(key) for key in (
            'tones', 'context_tags', 'culture_tags', 'country',
        )):
            return qs.distinct()
        return qs
