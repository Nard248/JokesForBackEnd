"""
API views for the Jokes API.

Provides viewsets for all models:
- JokeViewSet: Search, list, retrieve, and random joke endpoints
- Lookup viewsets: Format, AgeRating, Tone, ContextTag, Language, CultureTag
- GoogleLogin: Google OAuth2 authentication endpoint
- joke_share_page: Public share page with OG meta tags
"""
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView
from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET

from django.utils import timezone

from django.db.models import Sum

from .models import (
    Joke,
    Format,
    AgeRating,
    Tone,
    ContextTag,
    Language,
    CultureTag,
    UserPreference,
    Collection,
    SavedJoke,
    DailyJoke,
    JokeRating,
    ShareEvent,
)
from .recommendations import get_personalized_joke, get_recently_shown_joke_ids
from .serializers import (
    JokeSerializer,
    JokeListSerializer,
    FormatSerializer,
    AgeRatingSerializer,
    ToneSerializer,
    ContextTagSerializer,
    LanguageSerializer,
    CultureTagSerializer,
    UserPreferenceSerializer,
    UserPreferenceUpdateSerializer,
    CollectionSerializer,
    CollectionCreateSerializer,
    SavedJokeSerializer,
    SavedJokeCreateSerializer,
    DailyJokeSerializer,
    JokeRatingSerializer,
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

    @extend_schema(
        description='Rate a joke with thumbs up (1) or thumbs down (-1). Updates existing rating if present.',
        request={'application/json': {'type': 'object', 'properties': {'rating': {'type': 'integer', 'enum': [1, -1]}}}},
        responses={200: {'type': 'object', 'properties': {
            'rating': {'type': 'integer'},
            'created': {'type': 'boolean'},
            'joke_score': {'type': 'integer'}
        }}},
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def rate(self, request, pk=None):
        """Rate a joke: POST /api/v1/jokes/{id}/rate/ with {"rating": 1} or {"rating": -1}"""
        joke = self.get_object()
        rating_value = request.data.get('rating')

        if rating_value not in [1, -1]:
            return Response(
                {'error': 'Rating must be 1 (like) or -1 (dislike)'},
                status=status.HTTP_400_BAD_REQUEST
            )

        rating, created = JokeRating.objects.update_or_create(
            user=request.user,
            joke=joke,
            defaults={'rating': rating_value}
        )

        # Calculate aggregate score
        score = joke.ratings.aggregate(score=Sum('rating'))['score'] or 0

        return Response({
            'rating': rating.rating,
            'created': created,
            'joke_score': score
        })

    @extend_schema(
        description='Get current user\'s rating for this joke, or null if not rated.',
        responses={200: JokeRatingSerializer},
    )
    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated], url_path='my-rating')
    def get_rating(self, request, pk=None):
        """Get user's rating for a joke: GET /api/v1/jokes/{id}/my-rating/"""
        joke = self.get_object()
        try:
            rating = JokeRating.objects.get(user=request.user, joke=joke)
            return Response(JokeRatingSerializer(rating).data)
        except JokeRating.DoesNotExist:
            return Response({'rating': None})

    def get_permissions(self):
        """Allow unauthenticated access to share endpoint."""
        if self.action == 'share':
            return [AllowAny()]
        return super().get_permissions()

    @extend_schema(
        description='Record a share event for analytics. Platform: copy, twitter, facebook, whatsapp, other.',
        request={'application/json': {'type': 'object', 'properties': {
            'platform': {'type': 'string', 'enum': ['copy', 'twitter', 'facebook', 'whatsapp', 'other']}
        }}},
        responses={201: {'type': 'object', 'properties': {
            'status': {'type': 'string'},
            'share_url': {'type': 'string'},
            'joke_id': {'type': 'integer'}
        }}},
    )
    @action(detail=True, methods=['post'])
    def share(self, request, pk=None):
        """
        Record share event: POST /api/v1/jokes/{id}/share/ with {"platform": "twitter"}

        Returns the shareable URL for the joke.
        Authentication optional - tracks user if authenticated.
        """
        joke = self.get_object()
        platform = request.data.get('platform', 'other')

        # Validate platform
        valid_platforms = [choice[0] for choice in ShareEvent.PLATFORM_CHOICES]
        if platform not in valid_platforms:
            platform = 'other'

        # Create share event
        ShareEvent.objects.create(
            joke=joke,
            user=request.user if request.user.is_authenticated else None,
            platform=platform
        )

        # Build share URL
        share_url = request.build_absolute_uri(f'/jokes/{joke.pk}/share/')

        return Response({
            'status': 'recorded',
            'share_url': share_url,
            'joke_id': joke.pk,
        }, status=status.HTTP_201_CREATED)


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


# =============================================================================
# User Preferences ViewSet
# =============================================================================

class UserPreferenceViewSet(viewsets.GenericViewSet):
    """
    User preference management.

    Endpoints:
    - GET /api/v1/preferences/me/ - Get current user's preferences
    - PATCH /api/v1/preferences/me/ - Update current user's preferences
    - POST /api/v1/preferences/complete-onboarding/ - Mark onboarding as complete
    """

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'me' and self.request.method == 'PATCH':
            return UserPreferenceUpdateSerializer
        return UserPreferenceSerializer

    @extend_schema(
        description='Get or update current user preferences.',
        responses={200: UserPreferenceSerializer},
    )
    @action(detail=False, methods=['get', 'patch'], url_path='me')
    def me(self, request):
        """Get or update current user's preferences."""
        preference = request.user.preference

        if request.method == 'GET':
            serializer = UserPreferenceSerializer(preference)
            return Response(serializer.data)

        # PATCH
        serializer = UserPreferenceUpdateSerializer(
            preference, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Return updated preferences with nested serializer
        return Response(UserPreferenceSerializer(preference).data)

    @extend_schema(
        description='Mark user onboarding as complete.',
        responses={200: {'type': 'object', 'properties': {
            'status': {'type': 'string'},
            'onboarding_completed': {'type': 'boolean'}
        }}},
    )
    @action(detail=False, methods=['post'], url_path='complete-onboarding')
    def complete_onboarding(self, request):
        """Mark onboarding as complete."""
        preference = request.user.preference
        preference.onboarding_completed = True
        preference.save(update_fields=['onboarding_completed', 'updated_at'])
        return Response({
            'status': 'onboarding_completed',
            'onboarding_completed': True
        })


# =============================================================================
# OAuth Authentication Views
# =============================================================================

class GoogleLogin(SocialLoginView):
    """
    Google OAuth2 login endpoint.

    Accepts authorization code from frontend OAuth flow and returns JWT tokens.
    Frontend should redirect user to Google OAuth, receive code, then POST it here.

    Request body:
    {
        "code": "authorization_code_from_google"
    }

    Response:
    {
        "access": "jwt_access_token",  # Also set as HttpOnly cookie
        "refresh": "jwt_refresh_token",  # Also set as HttpOnly cookie
        "user": { ... }
    }
    """
    adapter_class = GoogleOAuth2Adapter
    callback_url = settings.GOOGLE_OAUTH_CALLBACK_URL
    client_class = OAuth2Client


# =============================================================================
# Collection and SavedJoke ViewSets
# =============================================================================

class CollectionViewSet(viewsets.ModelViewSet):
    """
    Collection management for authenticated users.

    Endpoints:
    - GET /api/v1/collections/ - List user's collections
    - POST /api/v1/collections/ - Create a new collection
    - GET /api/v1/collections/{id}/ - Get collection details
    - PATCH /api/v1/collections/{id}/ - Update collection
    - DELETE /api/v1/collections/{id}/ - Delete collection (except default)
    - GET /api/v1/collections/{id}/jokes/ - List jokes in collection
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return collections belonging to the current user."""
        return Collection.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return CollectionCreateSerializer
        return CollectionSerializer

    def perform_create(self, serializer):
        """Set the user when creating a collection."""
        serializer.save(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Prevent deletion of default collection."""
        instance = self.get_object()
        if instance.is_default:
            return Response(
                {'detail': 'Cannot delete the default Favorites collection.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        description='List jokes saved in this collection.',
        responses={200: SavedJokeSerializer(many=True)},
    )
    @action(detail=True, methods=['get'])
    def jokes(self, request, pk=None):
        """List jokes in this collection."""
        collection = self.get_object()
        saved_jokes = SavedJoke.objects.filter(
            collection=collection
        ).select_related('joke', 'collection')

        page = self.paginate_queryset(saved_jokes)
        if page is not None:
            serializer = SavedJokeSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = SavedJokeSerializer(saved_jokes, many=True)
        return Response(serializer.data)


class SavedJokeViewSet(
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Save and unsave jokes for authenticated users.

    Endpoints:
    - GET /api/v1/saved-jokes/ - List user's saved jokes
    - POST /api/v1/saved-jokes/ - Save a joke
    - DELETE /api/v1/saved-jokes/{id}/ - Unsave a joke
    - GET /api/v1/saved-jokes/search/?q=... - Search within saved jokes
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return saved jokes for the current user with related data."""
        return SavedJoke.objects.filter(
            user=self.request.user
        ).select_related('joke', 'collection')

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'create':
            return SavedJokeCreateSerializer
        return SavedJokeSerializer

    def perform_create(self, serializer):
        """Set the user when saving a joke."""
        serializer.save(user=self.request.user)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='q',
                type=str,
                description='Search query for joke text',
                required=False,
            ),
        ],
        description='Search within user\'s saved jokes by joke text.',
        responses={200: SavedJokeSerializer(many=True)},
    )
    @action(detail=False, methods=['get'])
    def search(self, request):
        """Search within saved jokes by joke text."""
        query = request.query_params.get('q', '').strip()

        if not query:
            return Response(
                {'detail': 'Search query "q" is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get joke IDs matching the search
        matching_joke_ids = Joke.objects.search(query_text=query).values_list('id', flat=True)

        # Filter saved jokes to those matching
        saved_jokes = self.get_queryset().filter(joke_id__in=matching_joke_ids)

        page = self.paginate_queryset(saved_jokes)
        if page is not None:
            serializer = SavedJokeSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = SavedJokeSerializer(saved_jokes, many=True)
        return Response(serializer.data)


# =============================================================================
# Daily Joke ViewSet
# =============================================================================

class DailyJokeViewSet(viewsets.GenericViewSet):
    """
    ViewSet for daily joke functionality.
    All endpoints require authentication.

    Endpoints:
    - GET /api/v1/daily-jokes/today/ - Get today's personalized joke
    - GET /api/v1/daily-jokes/history/ - Get last 30 days of jokes
    """

    permission_classes = [IsAuthenticated]
    serializer_class = DailyJokeSerializer

    def get_queryset(self):
        """Return daily jokes for the current user."""
        return DailyJoke.objects.filter(user=self.request.user)

    @extend_schema(
        description='Get today\'s personalized joke. Generates on-demand if not pre-generated.',
        responses={200: DailyJokeSerializer, 404: None},
    )
    @action(detail=False, methods=['get'])
    def today(self, request):
        """
        Get today's personalized joke.

        If scheduled task already generated one, return it.
        Otherwise, generate on-demand (fallback).

        Returns 404 if no joke available (dataset exhausted).
        """
        today = timezone.now().date()

        # Try to get pre-generated daily joke
        daily = DailyJoke.objects.filter(
            user=request.user,
            date=today
        ).select_related(
            'joke',
            'joke__format',
            'joke__age_rating',
            'joke__language'
        ).prefetch_related(
            'joke__tones',
            'joke__context_tags'
        ).first()

        if not daily:
            # Fallback: generate on-demand
            exclude_ids = get_recently_shown_joke_ids(request.user, days=30)
            joke = get_personalized_joke(request.user, exclude_joke_ids=exclude_ids)

            if joke:
                daily = DailyJoke.objects.create(
                    user=request.user,
                    joke=joke,
                    date=today
                )
            else:
                return Response(
                    {'detail': 'No jokes available. Please try again later.'},
                    status=status.HTTP_404_NOT_FOUND
                )

        # Mark as delivered on first access
        if not daily.delivered_at:
            daily.delivered_at = timezone.now()
            daily.save(update_fields=['delivered_at'])

        return Response(DailyJokeSerializer(daily).data)

    @extend_schema(
        description='Get user\'s daily joke history (last 30 days).',
        responses={200: DailyJokeSerializer(many=True)},
    )
    @action(detail=False, methods=['get'])
    def history(self, request):
        """
        Get user's daily joke history.
        Returns last 30 days of daily jokes.
        """
        queryset = self.get_queryset().select_related(
            'joke',
            'joke__format',
            'joke__age_rating',
            'joke__language'
        ).prefetch_related(
            'joke__tones',
            'joke__context_tags'
        )[:30]

        serializer = DailyJokeSerializer(queryset, many=True)
        return Response(serializer.data)


# =============================================================================
# Public Share Page View
# =============================================================================

@require_GET
def joke_share_page(request, pk):
    """
    Public share page for a joke with OG meta tags.

    This page is designed for social media crawlers. It returns
    an HTML page with proper Open Graph and Twitter Card meta tags
    so the joke preview looks great when shared.
    """
    joke = get_object_or_404(
        Joke.objects.select_related('format', 'age_rating').prefetch_related('tones'),
        pk=pk
    )

    # Build absolute URLs
    share_image_url = ''
    if joke.share_image:
        share_image_url = request.build_absolute_uri(joke.share_image.url)

    canonical_url = request.build_absolute_uri()

    # Get badge text from primary tone
    tone = joke.tones.first()
    badge_text = tone.name if tone else None

    return render(request, 'jokes/share.html', {
        'joke': joke,
        'share_image_url': share_image_url,
        'canonical_url': canonical_url,
        'badge_text': badge_text,
    })
