from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import models


class JokeManager(models.Manager):
    """Custom manager for Joke model with full-text search capabilities."""

    def search(self, query_text=None, filters=None):
        """
        Full-text search with optional filters.

        Args:
            query_text: Search string (optional - if empty, returns all)
            filters: Dict with optional keys:
                - format: slug string
                - age_rating: slug string
                - tones: list of slug strings
                - context_tags: list of slug strings
                - culture_tags: list of slug strings
                - language: code string

        Returns:
            QuerySet ordered by relevance (if searching) or date (if browsing)
        """
        qs = self.get_queryset()

        # Full-text search
        if query_text and query_text.strip():
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

        # Order by rank if searching, else by date
        if query_text and query_text.strip():
            qs = qs.order_by('-rank')
        else:
            qs = qs.order_by('-created_at')

        return qs.distinct()
