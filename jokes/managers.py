from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import models
from django.db.models import Case, Count, F, Func, Q, When

from .search import normalize_search_query


class JokeManager(models.Manager):
    """Custom manager for Joke model with full-text search capabilities.

    Takedowns are global: get_queryset() excludes is_removed=True so a moderated
    joke never serves through the default manager on ANY read path. Admin and
    moderation use `Joke.all_objects` (unfiltered) to view/restore removed jokes.
    """

    def get_queryset(self):
        return super().get_queryset().filter(is_removed=False)

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
                - '-created_at': newest first
                - 'popularity': by likes + saves descending
                - 'relevance': by search rank (default when query_text present)
                - None: auto-select (relevance if searching, -created_at otherwise)

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

        # Apply ordering
        if ordering == 'popularity' or ordering == '-popularity':
            qs = qs.annotate(
                like_count=Count('ratings', filter=Q(ratings__rating=1)),
                save_count=Count('saved_by'),
            ).order_by('-like_count', '-save_count', '-created_at', '-pk')
        elif ordering == '-created_at':
            qs = qs.order_by('-created_at', '-pk')
        elif ordering == 'relevance' and has_query:
            qs = qs.order_by('-rank', '-created_at', '-pk')
        elif has_query:
            # Default when searching: order by relevance
            qs = qs.order_by('-rank', '-created_at', '-pk')
        else:
            # Default when browsing: order by date
            qs = qs.order_by('-created_at', '-pk')

        # Only to-many filter joins can duplicate jokes. Avoid forcing a wide
        # DISTINCT/Unique sort (including both vectors) for ordinary searches;
        # PostgreSQL can then use a cheap count and top-N relevance sort.
        if filters and any(filters.get(key) for key in (
            'tones', 'context_tags', 'culture_tags', 'country',
        )):
            return qs.distinct()
        return qs
