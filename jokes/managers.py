from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import models
from django.db.models import Count, Q


class JokeManager(models.Manager):
    """Custom manager for Joke model with full-text search capabilities."""

    def search(self, query_text=None, filters=None, ordering=None):
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

        # Full-text search
        has_query = query_text and query_text.strip()
        if has_query:
            query = SearchQuery(query_text.strip(), search_type='websearch')
            qs = qs.annotate(
                rank=SearchRank('search_vector', query)
            ).filter(search_vector=query)

        # Apply filters
        if filters:
            if filters.get('format'):
                qs = qs.filter(format__slug=filters['format'])
            if filters.get('age_rating'):
                qs = qs.filter(age_rating__slug=filters['age_rating'])
            if filters.get('tones'):
                qs = qs.filter(tones__slug__in=filters['tones'])
            if filters.get('context_tags'):
                qs = qs.filter(context_tags__slug__in=filters['context_tags'])
            if filters.get('culture_tags'):
                qs = qs.filter(culture_tags__slug__in=filters['culture_tags'])
            if filters.get('language'):
                qs = qs.filter(language__code=filters['language'])

        # Apply ordering
        if ordering == 'popularity' or ordering == '-popularity':
            qs = qs.annotate(
                like_count=Count('ratings', filter=Q(ratings__rating=1)),
                save_count=Count('saved_by'),
            ).order_by('-like_count', '-save_count', '-created_at')
        elif ordering == '-created_at':
            qs = qs.order_by('-created_at')
        elif ordering == 'relevance' and has_query:
            qs = qs.order_by('-rank')
        elif has_query:
            # Default when searching: order by relevance
            qs = qs.order_by('-rank')
        else:
            # Default when browsing: order by date
            qs = qs.order_by('-created_at')

        return qs.distinct()
