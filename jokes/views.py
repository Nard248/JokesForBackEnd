"""
API views for the Jokes API.

Provides viewsets for all models:
- JokeViewSet: Search, list, retrieve, and random joke endpoints
- Lookup viewsets: Format, AgeRating, Tone, ContextTag, Language, CultureTag
"""
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter

from .models import (
    Joke,
    Format,
    AgeRating,
    Tone,
    ContextTag,
    Language,
    CultureTag,
)
from .serializers import (
    JokeSerializer,
    JokeListSerializer,
    FormatSerializer,
    AgeRatingSerializer,
    ToneSerializer,
    ContextTagSerializer,
    LanguageSerializer,
    CultureTagSerializer,
)


class JokeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Joke viewset with search, filtering, and random joke endpoints.

    list:
    Return a paginated list of jokes with optional search and filtering.

    retrieve:
    Return a single joke with full details and nested relations.

    random:
    Return a random joke (useful for "Joke of the Day" features).
    """

    queryset = Joke.objects.all()

    def get_serializer_class(self):
        """Use compact serializer for list, full serializer for detail."""
        if self.action == 'list':
            return JokeListSerializer
        return JokeSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='q',
                type=str,
                description='Full-text search query (searches text, setup, punchline)',
                required=False,
            ),
            OpenApiParameter(
                name='joke_format',
                type=str,
                description='Filter by format slug (e.g., one-liner, setup-punchline). Note: named joke_format to avoid conflict with DRF content negotiation.',
                required=False,
            ),
            OpenApiParameter(
                name='age_rating',
                type=str,
                description='Filter by age rating slug (e.g., kid-safe, family-friendly)',
                required=False,
            ),
            OpenApiParameter(
                name='tones',
                type=str,
                description='Filter by tone slugs, comma-separated (e.g., clean,dad-jokes)',
                required=False,
            ),
            OpenApiParameter(
                name='context_tags',
                type=str,
                description='Filter by context tag slugs, comma-separated (e.g., wedding,icebreaker)',
                required=False,
            ),
            OpenApiParameter(
                name='culture_tags',
                type=str,
                description='Filter by culture tag slugs, comma-separated (e.g., american,universal)',
                required=False,
            ),
            OpenApiParameter(
                name='language',
                type=str,
                description='Filter by language code (e.g., en)',
                required=False,
            ),
        ],
        description='List jokes with optional full-text search and filtering.',
    )
    def list(self, request, *args, **kwargs):
        """
        List jokes with optional full-text search and filtering.

        Query Parameters:
        - q: Full-text search query
        - joke_format: Filter by format slug (named to avoid DRF format param conflict)
        - age_rating: Filter by age rating slug
        - tones: Filter by tone slugs (comma-separated)
        - context_tags: Filter by context tag slugs (comma-separated)
        - culture_tags: Filter by culture tag slugs (comma-separated)
        - language: Filter by language code

        Examples:
        - /api/v1/jokes/?q=chicken
        - /api/v1/jokes/?joke_format=one-liner
        - /api/v1/jokes/?tones=clean,dad-jokes
        - /api/v1/jokes/?q=why&age_rating=kid-safe
        """
        # Extract query parameters
        query_text = request.query_params.get('q', '').strip()
        format_slug = request.query_params.get('joke_format', '').strip()  # named joke_format to avoid DRF conflict
        age_rating_slug = request.query_params.get('age_rating', '').strip()
        tones_param = request.query_params.get('tones', '').strip()
        context_tags_param = request.query_params.get('context_tags', '').strip()
        culture_tags_param = request.query_params.get('culture_tags', '').strip()
        language_code = request.query_params.get('language', '').strip()

        # Build filters dict
        filters = {}
        if format_slug:
            filters['format'] = format_slug
        if age_rating_slug:
            filters['age_rating'] = age_rating_slug
        if tones_param:
            filters['tones'] = [t.strip() for t in tones_param.split(',') if t.strip()]
        if context_tags_param:
            filters['context_tags'] = [t.strip() for t in context_tags_param.split(',') if t.strip()]
        if culture_tags_param:
            filters['culture_tags'] = [t.strip() for t in culture_tags_param.split(',') if t.strip()]
        if language_code:
            filters['language'] = language_code

        # Use JokeManager.search() for combined search and filtering
        queryset = Joke.objects.search(
            query_text=query_text if query_text else None,
            filters=filters if filters else None,
        )

        # Paginate results
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        description='Return a random joke with full details.',
        responses={200: JokeSerializer, 404: None},
    )
    @action(detail=False, methods=['get'])
    def random(self, request):
        """
        Return a random joke.

        Useful for "Joke of the Day" or random joke button features.
        Returns 404 if no jokes exist in the database.
        """
        joke = Joke.objects.order_by('?').first()
        if joke is None:
            return Response(
                {'detail': 'No jokes found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = JokeSerializer(joke)
        return Response(serializer.data)


# =============================================================================
# Lookup Model Viewsets
# =============================================================================

class FormatViewSet(viewsets.ReadOnlyModelViewSet):
    """Viewset for joke formats (one-liner, setup-punchline, etc.)."""
    queryset = Format.objects.all().order_by('name')
    serializer_class = FormatSerializer


class AgeRatingViewSet(viewsets.ReadOnlyModelViewSet):
    """Viewset for age ratings (kid-safe, teen, adult, family-friendly)."""
    queryset = AgeRating.objects.all().order_by('min_age', 'name')
    serializer_class = AgeRatingSerializer


class ToneViewSet(viewsets.ReadOnlyModelViewSet):
    """Viewset for humor tones (clean, dark, dad-jokes, puns, sarcasm)."""
    queryset = Tone.objects.all().order_by('name')
    serializer_class = ToneSerializer


class ContextTagViewSet(viewsets.ReadOnlyModelViewSet):
    """Viewset for context/situation tags (wedding, work, school, etc.)."""
    queryset = ContextTag.objects.all().order_by('name')
    serializer_class = ContextTagSerializer


class LanguageViewSet(viewsets.ReadOnlyModelViewSet):
    """Viewset for languages (ISO 639-1 codes)."""
    queryset = Language.objects.all().order_by('name')
    serializer_class = LanguageSerializer


class CultureTagViewSet(viewsets.ReadOnlyModelViewSet):
    """Viewset for cultural context tags (American, British, universal)."""
    queryset = CultureTag.objects.all().order_by('name')
    serializer_class = CultureTagSerializer
