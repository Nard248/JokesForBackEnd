"""
API views for the Jokes API.

Provides viewsets for all models:
- JokeViewSet: Search, list, retrieve, and random joke endpoints
- Lookup viewsets: Format, AgeRating, Tone, ContextTag, Language, CultureTag
- GoogleLogin: Google OAuth2 authentication endpoint
- joke_share_page: Public share page with OG meta tags
"""
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.app_settings import api_settings as rest_auth_settings
from dj_rest_auth.jwt_auth import set_jwt_cookies
from dj_rest_auth.registration.views import RegisterView, SocialLoginView
from django.conf import settings
from django.db import transaction
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET

from django.utils import timezone

from django.db.models import Count, Q, Sum

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
    Favorite,
    JokeSubmission,
    ContentReport,
    UserBlock,
    Achievement,
    UserAchievement,
    UserProfile,
    Vibe,
    UserVibe,
    MysteryBoxRoll,
    JokeReaction,
)
from .recommendations import get_personalized_joke, get_recently_shown_joke_ids
from .serializers import (
    JokeSerializer,
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
    FavoriteSerializer,
    FavoriteCreateSerializer,
    JokeSubmissionListSerializer,
    JokeSubmissionCreateSerializer,
    ContentReportSerializer,
    VibeSerializer,
    UserVibeSerializer,
    UserVibesUpdateSerializer,
    MysteryBoxStatusSerializer,
    MysteryBoxRollResponseSerializer,
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

    serializer_class = JokeSerializer

    def get_queryset(self):
        """Optimized queryset with eager loading for nested serializer."""
        return Joke.objects.select_related(
            'format', 'age_rating', 'language', 'source'
        ).prefetch_related('tones', 'context_tags', 'culture_tags')

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
            OpenApiParameter(
                name='vibe',
                type=str,
                description="Filter to jokes matching a curated vibe's recipe (e.g., 'office', 'puns'). Resolves the vibe's M2M filter recipe to themes/categories/formats.",
                required=False,
            ),
            OpenApiParameter(
                name='ordering',
                type=str,
                description='Sort order: -created_at (newest), popularity (by likes/saves), relevance (default when q is present)',
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
        ordering = request.query_params.get('ordering', '').strip()

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
            ordering=ordering if ordering else None,
        )

        # Vibe filter (P2): resolves to the vibe's M2M filter recipe.
        # Applied AFTER search() so it composes with all other filters.
        vibe_slug = request.query_params.get('vibe', '').strip()
        if vibe_slug:
            try:
                vibe = Vibe.objects.get(slug=vibe_slug, is_active=True)
            except Vibe.DoesNotExist:
                return Response(
                    {'detail': f"Unknown vibe '{vibe_slug}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = vibe.filter_jokes(queryset)

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
        score = joke.ratings.aggregate(score=Sum('rating'))['score'] or 0
        try:
            rating = JokeRating.objects.get(user=request.user, joke=joke)
            data = JokeRatingSerializer(rating).data
            data['joke_score'] = score
            return Response(data)
        except JokeRating.DoesNotExist:
            return Response({'rating': None, 'joke_score': score})

    @extend_schema(
        description=(
            'React to a joke with one of 4 emoji reactions (P4 of Pivot Plan). '
            'Posting the same reaction toggles it off; posting a different one '
            'switches. Returns my current reaction + aggregated counts.'
        ),
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'reaction': {
                        'type': 'string',
                        'enum': [r[0] for r in JokeReaction.REACTION_CHOICES],
                    },
                },
                'required': ['reaction'],
            },
        },
        responses={200: {'type': 'object', 'properties': {
            'my_reaction': {'type': 'string', 'nullable': True},
            'counts': {'type': 'object', 'additionalProperties': {'type': 'integer'}},
        }}},
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def react(self, request, pk=None):
        """React to a joke: POST /api/v1/jokes/{id}/react/ {"reaction": "lol"}"""
        joke = self.get_object()
        value = request.data.get('reaction')
        valid = {r[0] for r in JokeReaction.REACTION_CHOICES}
        if value not in valid:
            return Response(
                {'error': f'reaction must be one of {sorted(valid)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            existing = JokeReaction.objects.filter(user=request.user, joke=joke).first()
            if existing and existing.reaction == value:
                # Toggle off
                existing.delete()
                my_reaction = None
            elif existing:
                # Switch
                existing.reaction = value
                existing.save(update_fields=['reaction', 'updated_at'])
                my_reaction = value
            else:
                JokeReaction.objects.create(user=request.user, joke=joke, reaction=value)
                my_reaction = value

        # Aggregate counts
        counts = dict.fromkeys([r[0] for r in JokeReaction.REACTION_CHOICES], 0)
        for row in joke.reactions_v2.values('reaction').annotate(c=Count('id')):
            counts[row['reaction']] = row['c']

        return Response({'my_reaction': my_reaction, 'counts': counts})

    @extend_schema(
        description='Get aggregated reaction counts + the current user\'s reaction (if any).',
        responses={200: {'type': 'object', 'properties': {
            'my_reaction': {'type': 'string', 'nullable': True},
            'counts': {'type': 'object', 'additionalProperties': {'type': 'integer'}},
        }}},
    )
    @action(detail=True, methods=['get'])
    def reactions(self, request, pk=None):
        """Reactions summary: GET /api/v1/jokes/{id}/reactions/"""
        joke = self.get_object()
        counts = dict.fromkeys([r[0] for r in JokeReaction.REACTION_CHOICES], 0)
        for row in joke.reactions_v2.values('reaction').annotate(c=Count('id')):
            counts[row['reaction']] = row['c']
        my_reaction = None
        if request.user.is_authenticated:
            my = JokeReaction.objects.filter(user=request.user, joke=joke).first()
            if my:
                my_reaction = my.reaction
        return Response({'my_reaction': my_reaction, 'counts': counts})

    @extend_schema(
        parameters=[
            OpenApiParameter(name='period', type=str, description='Time window: today, week (default), month'),
        ],
        description='Get jokes ranked by recent popularity.',
    )
    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def trending(self, request):
        """GET /jokes/trending/ — Jokes ranked by recent popularity."""
        from datetime import timedelta

        period = request.query_params.get('period', 'week')
        period_map = {'today': 1, 'week': 7, 'month': 30}
        days = period_map.get(period, 7)
        since = timezone.now() - timedelta(days=days)

        jokes = Joke.objects.select_related(
            'format', 'age_rating', 'language', 'source'
        ).prefetch_related('tones', 'context_tags', 'culture_tags').annotate(
            recent_likes=Count('ratings', filter=Q(ratings__rating=1, ratings__created_at__gte=since)),
            recent_shares=Count('share_events', filter=Q(share_events__created_at__gte=since)),
            recent_saves=Count('saved_by', filter=Q(saved_by__created_at__gte=since)),
            score=Count('ratings', filter=Q(ratings__rating=1, ratings__created_at__gte=since))
                  + Count('share_events', filter=Q(share_events__created_at__gte=since)) * 2
                  + Count('saved_by', filter=Q(saved_by__created_at__gte=since)),
        ).filter(
            Q(recent_likes__gt=0) | Q(recent_shares__gt=0) | Q(recent_saves__gt=0)
        ).order_by('-score')

        page = self.paginate_queryset(jokes)
        results = []
        for rank, joke in enumerate(page or jokes[:20], 1):
            data = JokeSerializer(joke, context={'request': request}).data
            results.append({
                'rank': rank,
                'joke': data,
                'likes': joke.recent_likes,
                'shares': joke.recent_shares,
                'comments': 0,
                'trending_since': since.isoformat(),
            })

        if page is not None:
            return self.get_paginated_response(results)
        return Response({'count': len(results), 'next': None, 'previous': None, 'results': results})

    def get_permissions(self):
        """Allow unauthenticated access to share and trending endpoints."""
        if self.action in ('share', 'trending'):
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

class CookieRegisterView(RegisterView):
    # dj-rest-auth's RegisterView returns JWTs in the body but doesn't write
    # cookies — only LoginView does. Mirror LoginView's cookie-setting here so
    # the browser is authenticated immediately after sign-up, no extra login round-trip.
    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        if (
            response.status_code == status.HTTP_201_CREATED
            and rest_auth_settings.USE_JWT
            and getattr(self, 'access_token', None)
            and getattr(self, 'refresh_token', None)
        ):
            set_jwt_cookies(response, self.access_token, self.refresh_token)
        return response


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

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def trending(self, request):
        """GET /collections/trending/ — Public collections gaining traction."""
        from datetime import timedelta

        week_ago = timezone.now() - timedelta(days=7)
        collections = (
            Collection.objects.filter(is_public=True)
            .annotate(
                saves_this_week=Count('saved_jokes', filter=Q(saved_jokes__created_at__gte=week_ago)),
                joke_count=Count('saved_jokes'),
            )
            .filter(saves_this_week__gt=0)
            .order_by('-saves_this_week')[:10]
        )

        results = []
        for c in collections:
            results.append({
                'id': c.id,
                'name': c.name,
                'joke_count': c.joke_count,
                'saves_this_week': c.saves_this_week,
                'creator_name': c.user.first_name or c.user.email.split('@')[0],
            })

        return Response({'results': results})


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
        qs = SavedJoke.objects.filter(
            user=self.request.user
        ).select_related(
            'joke', 'joke__format', 'joke__age_rating', 'joke__language', 'joke__source',
            'collection'
        ).prefetch_related('joke__tones', 'joke__context_tags', 'joke__culture_tags')

        ordering = self.request.query_params.get('ordering', '-saved_at')
        ordering_map = {
            '-saved_at': '-created_at',
            'saved_at': 'created_at',
            '-created_at': '-created_at',
            'created_at': 'created_at',
        }
        qs = qs.order_by(ordering_map.get(ordering, '-created_at'))
        return qs

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

    Endpoints:
    - GET /api/v1/daily-jokes/today/ - Get today's joke (personalized for auth, editorial pick for anon)
    - GET /api/v1/daily-jokes/history/ - Get last 30 days of jokes (auth required)
    """

    serializer_class = DailyJokeSerializer

    def get_permissions(self):
        """Allow anonymous access to today's joke, require auth for history."""
        if self.action == 'today':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_queryset(self):
        """Return daily jokes for the current user."""
        if self.request.user.is_authenticated:
            return DailyJoke.objects.filter(user=self.request.user)
        return DailyJoke.objects.none()

    @extend_schema(
        description='Get today\'s joke. Personalized for authenticated users, editorial pick for anonymous.',
        responses={200: DailyJokeSerializer, 404: None},
    )
    @action(detail=False, methods=['get'])
    def today(self, request):
        """
        Get today's joke.

        For authenticated users: personalized based on preferences.
        For anonymous users: an editorial pick (random curated joke).
        """
        today_date = timezone.now().date()

        # Anonymous users get an editorial pick
        if not request.user.is_authenticated:
            joke = Joke.objects.select_related(
                'format', 'age_rating', 'language', 'source'
            ).prefetch_related(
                'tones', 'context_tags', 'culture_tags'
            ).order_by('?').first()

            if not joke:
                return Response(
                    {'detail': 'No jokes available.'},
                    status=status.HTTP_404_NOT_FOUND
                )
            return Response({
                'joke': JokeSerializer(joke, context={'request': request}).data,
                'date': today_date.isoformat(),
            })

        # Authenticated users get personalized daily joke
        daily = DailyJoke.objects.filter(
            user=request.user,
            date=today_date
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
                    date=today_date
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


# =============================================================================
# Phase 2: Joke Submission & Drafts
# =============================================================================

class JokeSubmitView(generics.CreateAPIView):
    """POST /jokes/submit/ — Submit a new joke for moderation."""

    permission_classes = [IsAuthenticated]
    serializer_class = JokeSubmissionCreateSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, status='pending')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {'id': serializer.instance.id, 'status': 'pending', 'created_at': serializer.instance.created_at},
            status=status.HTTP_201_CREATED,
        )


class JokeDraftListView(generics.ListAPIView):
    """GET /jokes/my-drafts/ — List user's drafts and submissions."""

    permission_classes = [IsAuthenticated]
    serializer_class = JokeSubmissionListSerializer

    def get_queryset(self):
        return JokeSubmission.objects.filter(
            user=self.request.user
        ).select_related('format', 'age_rating', 'published_joke').prefetch_related('tones', 'context_tags')


class JokeDraftDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE /jokes/my-drafts/{id}/

    PATCH: Only allowed when status is 'draft' or 'rejected'.
    DELETE: Always allowed for the owner.
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return JokeSubmission.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.request.method == 'PATCH':
            return JokeSubmissionCreateSerializer
        return JokeSubmissionListSerializer

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status not in ('draft', 'rejected'):
            return Response(
                {'detail': 'Can only edit drafts or rejected submissions.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().update(request, *args, **kwargs)


class JokeDraftSubmitView(APIView):
    """POST /jokes/my-drafts/{id}/submit/ — Submit a draft for review."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        submission = get_object_or_404(JokeSubmission, pk=pk, user=request.user)
        if submission.status not in ('draft', 'rejected'):
            return Response(
                {'detail': 'Can only submit drafts or rejected submissions for review.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        submission.status = 'pending'
        submission.save(update_fields=['status', 'updated_at'])
        return Response({'id': submission.id, 'status': 'pending'})


# =============================================================================
# Phase 3: Favorites
# =============================================================================

class FavoriteViewSet(
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Favorite management for authenticated users.

    Endpoints:
    - GET /api/v1/favorites/ — List favorited jokes
    - POST /api/v1/favorites/ — Favorite a joke
    - DELETE /api/v1/favorites/{id}/ — Unfavorite
    - GET /api/v1/favorites/stats/ — Favorite statistics
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Favorite.objects.filter(
            user=self.request.user
        ).select_related(
            'joke', 'joke__format', 'joke__age_rating', 'joke__language', 'joke__source'
        ).prefetch_related('joke__tones', 'joke__context_tags', 'joke__culture_tags')

        # Filter by tones
        tones_param = self.request.query_params.get('tones', '').strip()
        if tones_param:
            tone_slugs = [t.strip() for t in tones_param.split(',')]
            qs = qs.filter(joke__tones__slug__in=tone_slugs).distinct()

        # Ordering
        ordering = self.request.query_params.get('ordering', '-favorited_at')
        if ordering == '-popularity':
            qs = qs.annotate(
                popularity=Count('joke__ratings', filter=Q(joke__ratings__rating=1))
            ).order_by('-popularity')
        elif ordering == 'favorited_at':
            qs = qs.order_by('created_at')
        else:  # -favorited_at (default)
            qs = qs.order_by('-created_at')

        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return FavoriteCreateSerializer
        return FavoriteSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        """Override to return full Favorite object (not just joke id) after creation."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # Return full Favorite shape (id, joke, favorited_at) via FavoriteSerializer
        full_data = FavoriteSerializer(
            serializer.instance, context=self.get_serializer_context()
        ).data
        return Response(full_data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """GET /favorites/stats/ — Favorite statistics."""
        from datetime import timedelta

        favorites = Favorite.objects.filter(user=request.user)
        total = favorites.count()

        week_ago = timezone.now() - timedelta(days=7)
        this_week = favorites.filter(created_at__gte=week_ago).count()

        # Top tone: most common tone among favorited jokes
        top_tone_data = (
            Tone.objects.filter(jokes__favorited_by__user=request.user)
            .annotate(fav_count=Count('jokes__favorited_by'))
            .order_by('-fav_count')
            .first()
        )
        top_tone = top_tone_data.name if top_tone_data else None

        return Response({
            'total_count': total,
            'top_tone': top_tone,
            'this_week_count': this_week,
        })


# =============================================================================
# Phase 4: User Profile, Activity, Achievements, Preferences
# =============================================================================

class UserProfileView(APIView):
    """GET/PATCH /users/me/profile/ — User profile with stats and humor DNA."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        profile = user.profile

        # Compute stats
        stats = {
            'jokes_saved': SavedJoke.objects.filter(user=user).count(),
            'jokes_shared': ShareEvent.objects.filter(user=user).count(),
            'collections': Collection.objects.filter(user=user).count(),
            'days_active': (timezone.now().date() - user.date_joined.date()).days,
        }

        # Compute humor DNA from interaction history
        humor_dna = self._compute_humor_dna(user)

        return Response({
            'name': f"{user.first_name} {user.last_name}".strip() or user.email.split('@')[0],
            'username': f"@{user.email.split('@')[0]}",
            'email': user.email,
            'bio': profile.bio,
            'avatar_url': request.build_absolute_uri(profile.avatar.url) if profile.avatar else None,
            'member_since': user.date_joined.date().isoformat(),
            'is_premium': profile.is_premium,
            'stats': stats,
            'humor_dna': humor_dna,
        })

    def patch(self, request):
        user = request.user
        profile = user.profile

        if 'first_name' in request.data:
            user.first_name = request.data['first_name']
        if 'last_name' in request.data:
            user.last_name = request.data['last_name']
        if 'bio' in request.data:
            profile.bio = request.data['bio']

        user.save()
        profile.save()

        return self.get(request)

    def _compute_humor_dna(self, user):
        """Distribution of tones across user's positive interactions."""
        tone_counts = (
            Tone.objects.filter(
                Q(jokes__ratings__user=user, jokes__ratings__rating=1)
                | Q(jokes__favorited_by__user=user)
                | Q(jokes__saved_by__user=user)
            )
            .annotate(interaction_count=Count('id'))
            .order_by('-interaction_count')[:4]
        )
        total = sum(t.interaction_count for t in tone_counts) or 1
        return [
            {'type': t.name, 'percentage': round(t.interaction_count / total * 100)}
            for t in tone_counts
        ]


class UserActivityView(APIView):
    """GET /users/me/activity/ — Recent activity feed."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = int(request.query_params.get('limit', 10))
        activities = []

        # Recent ratings
        for r in JokeRating.objects.filter(user=request.user).select_related('joke').order_by('-created_at')[:limit]:
            verb = 'Liked' if r.rating == 1 else 'Disliked'
            activities.append({
                'id': f'rating_{r.id}',
                'type': 'like' if r.rating == 1 else 'dislike',
                'description': f"{verb} '{r.joke.text[:40]}...'",
                'created_at': r.created_at,
            })

        # Recent saves
        for s in SavedJoke.objects.filter(user=request.user).select_related('joke').order_by('-created_at')[:limit]:
            activities.append({
                'id': f'save_{s.id}',
                'type': 'save',
                'description': f"Saved '{s.joke.text[:40]}...'",
                'created_at': s.created_at,
            })

        # Recent favorites
        for f in Favorite.objects.filter(user=request.user).select_related('joke').order_by('-created_at')[:limit]:
            activities.append({
                'id': f'fav_{f.id}',
                'type': 'save',
                'description': f"Favorited '{f.joke.text[:40]}...'",
                'created_at': f.created_at,
            })

        # Recent shares
        for e in ShareEvent.objects.filter(user=request.user).order_by('-created_at')[:limit]:
            activities.append({
                'id': f'share_{e.id}',
                'type': 'share',
                'description': f"Shared a joke via {e.get_platform_display()}",
                'created_at': e.created_at,
            })

        # Sort and limit
        activities.sort(key=lambda x: x['created_at'], reverse=True)
        return Response({'results': activities[:limit]})


class UserAchievementsView(APIView):
    """GET /users/me/achievements/ — All achievement badges with unlock status."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        unlocked = dict(
            UserAchievement.objects.filter(user=user).values_list('achievement__slug', 'unlocked_at')
        )

        results = []
        for ach in Achievement.objects.all():
            results.append({
                'id': ach.slug,
                'title': ach.title,
                'description': ach.description,
                'icon': ach.icon,
                'unlocked': ach.slug in unlocked,
                'unlocked_at': unlocked.get(ach.slug),
            })

        return Response({'results': results})


class UserPreferencesView(APIView):
    """GET/PUT/PATCH /users/me/preferences/ — Composite preferences from UserPreference + UserProfile."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        pref = request.user.preference
        profile = request.user.profile
        return Response({
            'humor_types': list(pref.preferred_tones.values_list('slug', flat=True)),
            'notifications': {
                'daily_joke': pref.notification_daily_joke,
                'trending_alerts': pref.notification_trending_alerts,
                'collection_updates': pref.notification_collection_updates,
                'email_digest': pref.notification_email_digest,
            },
            'privacy': {
                'public_profile': profile.public_profile,
                'show_activity': profile.show_activity,
                'share_analytics': profile.share_analytics,
            },
            'theme': profile.theme,
        })

    def put(self, request):
        return self._update(request)

    def patch(self, request):
        return self._update(request)

    def _update(self, request):
        pref = request.user.preference
        profile = request.user.profile
        data = request.data

        # Update humor_types
        if 'humor_types' in data:
            tone_slugs = data['humor_types']
            tones = Tone.objects.filter(slug__in=tone_slugs)
            pref.preferred_tones.set(tones)

        # Update notifications
        if 'notifications' in data:
            notif = data['notifications']
            for key in ('daily_joke', 'trending_alerts', 'collection_updates', 'email_digest'):
                if key in notif:
                    setattr(pref, f'notification_{key}', notif[key])
            pref.save()

        # Update privacy
        if 'privacy' in data:
            priv = data['privacy']
            for key in ('public_profile', 'show_activity', 'share_analytics'):
                if key in priv:
                    setattr(profile, key, priv[key])
            profile.save()

        # Update theme
        if 'theme' in data:
            profile.theme = data['theme']
            profile.save()

        return self.get(request)


# =============================================================================
# Phase 5: Trending & Discovery
# =============================================================================

class TagsTrendingView(APIView):
    """GET /tags/trending/ — Tags ranked by engagement."""

    permission_classes = [AllowAny]

    def get(self, request):
        from datetime import timedelta
        since = timezone.now() - timedelta(days=7)

        results = (
            Tone.objects.annotate(
                count=Count('jokes__ratings', filter=Q(
                    jokes__ratings__rating=1, jokes__ratings__created_at__gte=since
                ))
            ).filter(count__gt=0).order_by('-count')[:10]
        )

        return Response({
            'results': [
                {'name': t.name, 'slug': t.slug, 'count': t.count, 'growth_percent': 0}
                for t in results
            ]
        })


class TagsRisingView(APIView):
    """GET /tags/rising/ — Topics with highest growth rate."""

    permission_classes = [AllowAny]

    def get(self, request):
        from datetime import timedelta
        now = timezone.now()
        this_week = now - timedelta(days=7)
        prev_week = this_week - timedelta(days=7)

        results = []
        for tag in ContextTag.objects.all():
            current = tag.jokes.filter(
                ratings__rating=1, ratings__created_at__gte=this_week
            ).count()
            previous = tag.jokes.filter(
                ratings__rating=1, ratings__created_at__gte=prev_week,
                ratings__created_at__lt=this_week
            ).count()
            if current > 0:
                growth = round((current - previous) / max(previous, 1) * 100)
                results.append({'name': tag.name, 'slug': tag.slug, 'growth_percent': growth})

        results.sort(key=lambda x: x['growth_percent'], reverse=True)
        return Response({'results': results[:10]})


class TopJokestersView(APIView):
    """GET /users/top-jokesters/ — Users ranked by contributions."""

    permission_classes = [AllowAny]

    def get(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        period = request.query_params.get('period', 'all_time')
        limit = int(request.query_params.get('limit', 5))

        qs = User.objects.filter(joke_submissions__status='published')

        if period != 'all_time':
            from datetime import timedelta
            days = {'week': 7, 'month': 30}.get(period, 365)
            since = timezone.now() - timedelta(days=days)
            qs = qs.filter(joke_submissions__updated_at__gte=since)

        users = qs.annotate(
            punchline_count=Count('joke_submissions', filter=Q(joke_submissions__status='published'))
        ).order_by('-punchline_count')[:limit]

        results = []
        for rank, u in enumerate(users, 1):
            name = f"{u.first_name} {u.last_name}".strip() or u.email.split('@')[0]
            results.append({
                'id': u.id,
                'name': name,
                'username': f"@{u.email.split('@')[0]}",
                'avatar_url': None,
                'punchline_count': u.punchline_count,
                'rank': rank,
            })

        return Response({'results': results})


class ThemesPopularView(APIView):
    """GET /themes/popular/ — Popular topic labels for discovery."""

    permission_classes = [AllowAny]

    def get(self, request):
        names = list(
            ContextTag.objects.annotate(joke_count=Count('jokes'))
            .order_by('-joke_count')
            .values_list('name', flat=True)[:10]
        )
        return Response({'results': names})


# =============================================================================
# Phase 6: Compliance & Account Management
# =============================================================================

class ContentReportView(generics.CreateAPIView):
    """POST /reports/ — Report content (app store compliance)."""

    permission_classes = [IsAuthenticated]
    serializer_class = ContentReportSerializer

    def perform_create(self, serializer):
        serializer.save(reporter=self.request.user)


class UserBlockView(APIView):
    """POST/DELETE /users/{user_id}/block/ — Block/unblock a user."""

    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        blocked_user = get_object_or_404(User, pk=user_id)
        if blocked_user == request.user:
            return Response({'detail': 'Cannot block yourself.'}, status=status.HTTP_400_BAD_REQUEST)
        UserBlock.objects.get_or_create(blocker=request.user, blocked=blocked_user)
        return Response({'status': 'blocked'}, status=status.HTTP_201_CREATED)

    def delete(self, request, user_id):
        UserBlock.objects.filter(blocker=request.user, blocked_id=user_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserAccountDeleteView(APIView):
    """DELETE /users/me/ — Permanently delete account (GDPR)."""

    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DataExportView(APIView):
    """GET /users/me/data-export/ — GDPR data export (placeholder)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            'status': 'processing',
            'message': 'Your data export is being prepared. You will receive an email when ready.',
        }, status=status.HTTP_202_ACCEPTED)


# =============================================================================
# Vibes (P2 of Pivot Plan)
# =============================================================================

class VibeViewSet(viewsets.ReadOnlyModelViewSet):
    """Catalog of curated vibes shown in the onboarding picker.

    Read-only — vibes are seeded by migration 0013 and edited by curators in
    Django admin.
    """
    queryset = Vibe.objects.filter(is_active=True)
    serializer_class = VibeSerializer
    lookup_field = 'slug'
    pagination_class = None  # 12 vibes; pagination would just add noise


class UserVibesView(APIView):
    """The current user's vibe selection — read with GET, replace with PUT.

    GET   /api/v1/users/me/vibes/  → list of {vibe, weight, created_at}
    PUT   /api/v1/users/me/vibes/  → body {"slugs": ["office","puns",…]}
                                      replaces selection atomically; 3-12 slugs
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            UserVibe.objects.filter(user=request.user)
            .select_related('vibe')
            .order_by('-created_at')
        )
        return Response(UserVibeSerializer(qs, many=True).data)

    @extend_schema(
        request=UserVibesUpdateSerializer,
        responses={200: UserVibeSerializer(many=True)},
        description='Replace the user\'s vibe selection. Body: {"slugs": [...]}.',
    )
    def put(self, request):
        serializer = UserVibesUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        slugs = serializer.validated_data['slugs']

        with transaction.atomic():
            UserVibe.objects.filter(user=request.user).delete()
            vibes = list(Vibe.objects.filter(slug__in=slugs, is_active=True))
            UserVibe.objects.bulk_create(
                [UserVibe(user=request.user, vibe=v) for v in vibes]
            )

        qs = (
            UserVibe.objects.filter(user=request.user)
            .select_related('vibe')
            .order_by('-created_at')
        )
        return Response(UserVibeSerializer(qs, many=True).data)


# =============================================================================
# Mystery Box (P3 of Pivot Plan) — variable-reward pull from user's vibe pool
# =============================================================================

def _mystery_pool_for_user(user):
    """Build the joke pool a user can be served from the Mystery Box.

    Strategy:
      1. Union of jokes matching every vibe the user picked (their "pool").
      2. If no vibes / empty pool → fall back to the global joke pool.
      3. Exclude jokes already rolled today by this user (no same-day repeats).
      4. Exclude jokes the user has already saved (already in their library).

    Returns a 2-tuple `(queryset, source_vibe)`. `source_vibe` is one of the
    user's vibes (any) — for telemetry on the roll, not for filtering.
    """
    from django.utils import timezone
    today = timezone.now().date()

    user_vibes = list(
        Vibe.objects.filter(picked_by__user=user, is_active=True).distinct()
    )

    pool = Joke.objects.none()
    used_vibe = None
    if user_vibes:
        joke_ids = set()
        for v in user_vibes:
            joke_ids.update(v.filter_jokes().values_list('id', flat=True))
        if joke_ids:
            pool = Joke.objects.filter(id__in=joke_ids)
            used_vibe = user_vibes[0]
    if not pool.exists():
        pool = Joke.objects.all()
        used_vibe = None

    rolled_today = MysteryBoxRoll.objects.filter(
        user=user, rolled_date=today
    ).values_list('joke_id', flat=True)
    pool = pool.exclude(id__in=list(rolled_today))

    saved_ids = SavedJoke.objects.filter(user=user).values_list('joke_id', flat=True)
    pool = pool.exclude(id__in=list(saved_ids))

    return pool, used_vibe


class MysteryBoxStatusView(APIView):
    """GET /api/v1/mystery-box/status/ — current quota state for the user."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MysteryBoxStatusSerializer})
    def get(self, request):
        from django.utils import timezone
        used = MysteryBoxRoll.objects.filter(
            user=request.user, rolled_date=timezone.now().date()
        ).count()
        max_per_day = MysteryBoxRoll.MAX_DAILY_ROLLS
        return Response({
            'rolls_used_today': used,
            'rolls_remaining_today': max(0, max_per_day - used),
            'max_per_day': max_per_day,
        })


class MysteryBoxRollView(APIView):
    """POST /api/v1/mystery-box/roll/ — pull one joke from the user's pool.

    Returns 429 if daily cap reached, 404 if pool exhausted, 200 with the
    joke + remaining quota otherwise.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: MysteryBoxRollResponseSerializer,
            404: None,
            429: None,
        },
    )
    def post(self, request):
        from django.utils import timezone
        today = timezone.now().date()

        used = MysteryBoxRoll.objects.filter(
            user=request.user, rolled_date=today
        ).count()
        if used >= MysteryBoxRoll.MAX_DAILY_ROLLS:
            return Response(
                {
                    'detail': 'Daily Mystery Box limit reached. Resets at midnight UTC.',
                    'rolls_used_today': used,
                    'rolls_remaining_today': 0,
                    'max_per_day': MysteryBoxRoll.MAX_DAILY_ROLLS,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        pool, source_vibe = _mystery_pool_for_user(request.user)
        joke = pool.order_by('?').first()
        if joke is None:
            return Response(
                {'detail': 'No jokes available — your pool is exhausted for today.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        with transaction.atomic():
            MysteryBoxRoll.objects.create(
                user=request.user,
                joke=joke,
                source_vibe=source_vibe,
                rolled_date=today,
            )

        return Response({
            'joke': JokeSerializer(joke, context={'request': request}).data,
            'rolls_remaining_today': MysteryBoxRoll.MAX_DAILY_ROLLS - used - 1,
            'source_vibe': VibeSerializer(source_vibe).data if source_vibe else None,
        })
