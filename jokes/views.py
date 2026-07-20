"""
API views for the Jokes API.

Provides viewsets for all models:
- JokeViewSet: Search, list, retrieve, and random joke endpoints
- Lookup viewsets: Format, AgeRating, Tone, ContextTag, Language, CultureTag
- GoogleLogin: Google OAuth2 authentication endpoint
- joke_share_page: Public share page with OG meta tags
"""
import io
import json
import zipfile
from datetime import timedelta

from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from django.core.files.base import ContentFile
from django.middleware.csrf import get_token
from drf_spectacular.utils import extend_schema, OpenApiParameter
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.app_settings import api_settings as rest_auth_settings
from dj_rest_auth.jwt_auth import set_jwt_cookies
from dj_rest_auth.registration.views import RegisterView, SocialLoginView
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET

from django.utils import timezone

from django.db.models import Count, Max, Min, Q, Sum
from django.db.models.functions import ExtractHour

from notifications.models import EmailMessageLog, EmailVerification
from billing import entitlements

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
    JokeView,
    JokeImpression,
    JokeDwell,
    Streak,
    StreakDay,
    JokePack,
    JokePackEntry,
    JokePackProgress,
    MediaAsset,
)
from .media_processing import MediaValidationError, process_image
from .media_screening import get_matcher, screen_image
from .recommendations import get_personalized_joke, get_recently_shown_joke_ids
from .serving import allowed_tiers
from .paywall import paywall_state
from .submission_rules import validate_per_format
from .identity import (
    public_display_name, public_handle, normalize_handle, is_valid_handle,
)
from .moderation import visible_jokes, is_blocked_between, hidden_user_ids
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
    JokeViewSerializer,
    StreakSerializer,
    JokePackListSerializer,
    JokePackDetailSerializer,
    JokePackProgressUpdateSerializer,
    MediaAssetSerializer,
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
        qs = Joke.objects.filter(
            content_tier__in=allowed_tiers(self.request)
        ).select_related(
            'format', 'age_rating', 'language', 'source'
        ).prefetch_related('tones', 'context_tags', 'culture_tags', 'media__asset')
        # Moderation: hide removed jokes (global) + blocked users' jokes (per-viewer).
        return visible_jokes(qs, self.request)

    def get_serializer_context(self):
        """Inject the once-per-request paywall decision so JokeSerializer can
        lock/strip the payoff uniformly for list + retrieve."""
        ctx = super().get_serializer_context()
        ctx['paywall_state'] = paywall_state(self.request)
        return ctx

    def retrieve(self, request, *args, **kwargs):
        """Return a joke and log a JokeView (P5) ONLY when it is delivered
        UNLOCKED — a within-limit new open, or a re-open of an already-consumed
        joke. A LOCKED delivery (free user over the cap, new joke) yields no
        payoff, so it must NOT count against / into the ledger. 60s debounce
        still applies to unlocked re-opens.
        """
        response = super().retrieve(request, *args, **kwargs)
        if request.user.is_authenticated and response.status_code == 200:
            # is_locked is computed by the serializer from paywall_state; a
            # locked joke gave the user no payoff, so do not log consumption.
            if response.data.get('is_locked'):
                return response
            from django.utils import timezone
            from datetime import timedelta
            joke_id = response.data.get('id')
            if joke_id:
                source = request.query_params.get('source', JokeView.SOURCE_OTHER)
                if source not in dict(JokeView.SOURCE_CHOICES):
                    source = JokeView.SOURCE_OTHER
                # Debounce: skip if same user+joke logged within 60s
                cutoff = timezone.now() - timedelta(seconds=60)
                recent = JokeView.objects.filter(
                    user=request.user, joke_id=joke_id, viewed_at__gte=cutoff
                ).exists()
                if not recent:
                    JokeView.objects.create(
                        user=request.user, joke_id=joke_id, source=source
                    )
        return response

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
            allowed_tiers=allowed_tiers(request),
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

        # Moderation: hide jokes by users blocked-by/blocking the viewer (removed
        # jokes are already excluded by the default manager).
        hidden = hidden_user_ids(request.user)
        if hidden:
            queryset = queryset.exclude(creator_id__in=hidden)

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
        qs = Joke.objects.filter(content_tier__in=allowed_tiers(request))
        hidden = hidden_user_ids(request.user)
        if hidden:
            qs = qs.exclude(creator_id__in=hidden)
        joke = qs.order_by('?').first()
        if joke is None:
            return Response(
                {'detail': 'No jokes found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = JokeSerializer(
            joke,
            context={'request': request, 'paywall_state': paywall_state(request)},
        )
        return Response(serializer.data)

    @extend_schema(
        description=(
            'Free daily-read cap state for the freemium punchline paywall. '
            'Paid/unlimited tiers return limit=null, remaining=null, over=false.'
        ),
        responses={200: {'type': 'object', 'properties': {
            'limit': {'type': 'integer', 'nullable': True},
            'used': {'type': 'integer'},
            'remaining': {'type': 'integer', 'nullable': True},
            'over': {'type': 'boolean'},
            'reset_at': {'type': 'string', 'format': 'date-time'},
        }}},
    )
    @action(
        detail=False, methods=['get'],
        permission_classes=[IsAuthenticated], url_path='daily-reads',
    )
    def daily_reads(self, request):
        """GET /api/v1/jokes/daily-reads/ — remaining free reads for the nudge."""
        state = paywall_state(request)
        return Response({
            'limit': state.limit,           # null == unlimited (paid)
            'used': state.used,
            'remaining': state.remaining,   # null == unlimited
            'over': state.over,
            'reset_at': state.reset_at,
        })

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

        jokes = Joke.objects.filter(
            content_tier__in=allowed_tiers(request)
        ).select_related(
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
        pw_state = paywall_state(request)  # compute once for the whole page
        for rank, joke in enumerate(page or jokes[:20], 1):
            data = JokeSerializer(
                joke, context={'request': request, 'paywall_state': pw_state},
            ).data
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
# CSRF token endpoint
# =============================================================================

@api_view(['GET'])
@authentication_classes([])  # never cookie-authenticate; usable pre- and post-login
@permission_classes([AllowAny])
def csrf_token_view(request):
    """GET /api/v1/auth/csrf/ — issue the CSRF cookie and return its token value.

    The SPA lives on a different origin than this API, so it cannot read the
    SameSite=None CSRF cookie via document.cookie. Instead it reads the token
    VALUE from this JSON body and echoes it back in the X-CSRFToken header on
    every mutating request; the browser sends the matching cookie automatically
    and Django's double-submit check compares the two.

    Calling get_token() flags request.META['CSRF_COOKIE_NEEDS_UPDATE'], which
    CsrfViewMiddleware.process_response reads to set the cookie on the way out —
    this is exactly what the @ensure_csrf_cookie decorator does internally, but
    without the decorator-from-middleware wrapping that composes awkwardly with
    DRF's @api_view. authentication_classes=[] keeps this endpoint free of the
    JWT-cookie authenticator so it never depends on a token the caller is trying
    to obtain (a GET would pass enforce_csrf anyway, but this removes all doubt).
    """
    return Response({'csrfToken': get_token(request)})


# =============================================================================
# OAuth Authentication Views
# =============================================================================

class CookieRegisterView(RegisterView):
    """Registration with two modes, switched by EMAIL_VERIFICATION_REQUIRED.

    Gated (True): create an inactive user, issue + email a 6-digit code, return
    201 {detail, email} with NO tokens. The user authenticates only after
    POST /auth/verify-email/.

    Legacy (False): original behavior — active user, JWT cookies on 201. Kept so
    the feature can be deployed before a real email provider is live.
    """

    def create(self, request, *args, **kwargs):
        import logging as _logging
        _reg_metrics = _logging.getLogger('jokesfor.metrics')

        if not settings.EMAIL_VERIFICATION_REQUIRED:
            response = super().create(request, *args, **kwargs)
            if (
                response.status_code == status.HTTP_201_CREATED
                and rest_auth_settings.USE_JWT
                and getattr(self, 'access_token', None)
                and getattr(self, 'refresh_token', None)
            ):
                set_jwt_cookies(response, self.access_token, self.refresh_token)
            if response.status_code == status.HTTP_201_CREATED:
                from audit.services import record_audit
                actor = getattr(self, 'user', None)
                record_audit(request, 'registration', outcome='success', actor=actor)
                _reg_metrics.info('metric', extra={
                    'event': 'registration', 'mode': 'legacy', 'outcome': 'created',
                })
            return response

        # Gated flow.
        from notifications import verification
        from notifications.service import EmailSendError
        from audit.services import record_audit

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save(request)
        user.is_active = False
        user.save(update_fields=['is_active'])

        try:
            verification.issue_and_send(user)
        except EmailSendError:
            # Provider down. The user row exists (inactive) and a verification
            # row was issued, so the account is recoverable via
            # POST /auth/resend-verification/. Surface a 502 instead of a 500.
            record_audit(request, 'registration', outcome='failure', actor=user,
                         metadata={'reason': 'email_send_failed'})
            _reg_metrics.info('metric', extra={
                'event': 'registration', 'mode': 'gated', 'outcome': 'email_send_failed',
            })
            return Response(
                {'detail': "We couldn't send your code right now. "
                           'Please use "Resend code" in a moment.',
                 'email': user.email},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        record_audit(request, 'registration', outcome='success', actor=user)
        _reg_metrics.info('metric', extra={
            'event': 'registration', 'mode': 'gated', 'outcome': 'created',
        })
        return Response(
            {'detail': 'Verification code sent to your email.', 'email': user.email},
            status=status.HTTP_201_CREATED,
        )


class GoogleLogin(SocialLoginView):
    """
    Google OAuth2 login endpoint.

    Accepts authorization code from frontend OAuth flow and returns JWT tokens.
    Frontend should redirect user to Google OAuth, receive code, then POST it here.

    Request body:
    {
        "code": "authorization_code_from_google",
        "date_of_birth": "2000-01-01"  # ISO yyyy-mm-dd; required for NEW users
    }

    COPPA age gate (SocialAccountAdapter.pre_social_login):
    - Existing/linked user: logs in, date_of_birth ignored, existing DOB kept.
    - New user, no date_of_birth: 400 {"code": "dob_required", ...}, no account.
    - New user, age < 13: 400 {"date_of_birth": ["...at least 13..."]}, no account.
    - New user, age >= 13: account created with DOB persisted to the profile.

    Response (success):
    {
        "access": "jwt_access_token",  # Also set as HttpOnly cookie
        "refresh": "jwt_refresh_token",  # Also set as HttpOnly cookie
        "user": { ... }
    }
    """
    adapter_class = GoogleOAuth2Adapter
    callback_url = settings.GOOGLE_OAUTH_CALLBACK_URL
    client_class = OAuth2Client

    def post(self, request, *args, **kwargs):
        # allauth hands the SocialAccountAdapter the unwrapped Django
        # HttpRequest, whose .POST is empty for a JSON body. Stash the raw DOB
        # from the parsed DRF body onto it so pre_social_login can read it.
        from JokesForProject.adapters import DOB_REQUEST_ATTR
        setattr(request._request, DOB_REQUEST_ATTR, request.data.get('date_of_birth'))
        return super().post(request, *args, **kwargs)


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
            collection=collection,
            joke__content_tier__in=allowed_tiers(request),
        ).select_related('joke', 'collection')

        # Paywall flows into the nested JokeSerializer via the root context.
        ctx = {'request': request, 'paywall_state': paywall_state(request)}
        page = self.paginate_queryset(saved_jokes)
        if page is not None:
            serializer = SavedJokeSerializer(page, many=True, context=ctx)
            return self.get_paginated_response(serializer.data)

        serializer = SavedJokeSerializer(saved_jokes, many=True, context=ctx)
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
                # public_display_name never exposes the email (chosen name →
                # real name → opaque user_<pk>); this endpoint is AllowAny.
                'creator_name': public_display_name(c.user),
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
        ).prefetch_related(
            'joke__tones', 'joke__context_tags', 'joke__culture_tags', 'joke__media__asset'
        )

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

    def get_serializer_context(self):
        """Inject the once-per-request paywall decision so the nested
        JokeSerializer can lock/strip the payoff (mirrors JokeViewSet)."""
        ctx = super().get_serializer_context()
        ctx['paywall_state'] = paywall_state(self.request)
        return ctx

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

        # Get joke IDs matching the search (within allowed tiers)
        tiers = allowed_tiers(request)
        matching_joke_ids = Joke.objects.search(
            query_text=query, allowed_tiers=tiers
        ).values_list('id', flat=True)

        # Filter saved jokes to those matching (also filter by tier for belt-and-suspenders)
        saved_jokes = self.get_queryset().filter(
            joke_id__in=matching_joke_ids,
            joke__content_tier__in=tiers,
        )

        ctx = self.get_serializer_context()
        page = self.paginate_queryset(saved_jokes)
        if page is not None:
            serializer = SavedJokeSerializer(page, many=True, context=ctx)
            return self.get_paginated_response(serializer.data)

        serializer = SavedJokeSerializer(saved_jokes, many=True, context=ctx)
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

        # Anonymous users get an editorial pick (tier_1 only — always fail-safe for anon)
        if not request.user.is_authenticated:
            joke = Joke.objects.filter(
                content_tier__in=allowed_tiers(request)
            ).select_related(
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
            # Fallback: generate on-demand (respecting allowed tiers for this user)
            exclude_ids = get_recently_shown_joke_ids(request.user, days=30)
            joke = get_personalized_joke(
                request.user,
                exclude_joke_ids=exclude_ids,
                allowed_tiers=allowed_tiers(request),
            )

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

        # P9: include newspaper-style issue label
        data = DailyJokeSerializer(daily).data
        data['issue_label'] = _issue_label_for(daily.date)
        return Response(data)

    @extend_schema(
        description="Tomorrow's daily joke (lazy-generated), truncated to 12 words for the blurred teaser. P9 of Pivot Plan.",
        responses={200: {'type': 'object'}, 404: None},
    )
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def tomorrow(self, request):
        """GET /api/v1/daily-jokes/tomorrow/ — preview tomorrow's joke."""
        from datetime import timedelta
        tomorrow_date = timezone.now().date() + timedelta(days=1)
        daily = DailyJoke.objects.filter(
            user=request.user, date=tomorrow_date
        ).select_related('joke', 'joke__format').first()

        if not daily:
            # Lazy-generate (replaces the Celery beat task)
            exclude_ids = get_recently_shown_joke_ids(request.user, days=30)
            joke = get_personalized_joke(
                request.user,
                exclude_joke_ids=exclude_ids,
                allowed_tiers=allowed_tiers(request),
            )
            if joke is None:
                return Response(
                    {'detail': 'No jokes available for tomorrow yet.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
            daily = DailyJoke.objects.create(
                user=request.user, joke=joke, date=tomorrow_date
            )

        full_text = daily.joke.text or daily.joke.setup or ''
        words = full_text.split()
        preview = ' '.join(words[:12]) + ('…' if len(words) > 12 else '')
        return Response({
            'date': daily.date,
            'issue_label': _issue_label_for(daily.date),
            'preview': preview,
            'format': daily.joke.format.slug if daily.joke.format else None,
        })

    @extend_schema(
        description=(
            'Get the user\'s daily joke history as a rolling window. The window '
            'length is the daily_joke_history_days entitlement (free 30 / '
            'supporter 90 / creator_pro 365) and rolls with the clock.'
        ),
        responses={200: DailyJokeSerializer(many=True)},
    )
    @action(detail=False, methods=['get'])
    def history(self, request):
        """Get the user's daily joke history.

        Rolling "last N days" DATE window (not a fixed row count): entries older
        than ``today - daily_joke_history_days`` roll off as the clock advances,
        and the window honors the per-plan entitlement.
        """
        from datetime import timedelta

        queryset = self.get_queryset().select_related(
            'joke',
            'joke__format',
            'joke__age_rating',
            'joke__language'
        ).prefetch_related(
            'joke__tones',
            'joke__context_tags'
        )

        window_days = entitlements.get_limit(
            request.user, 'daily_joke_history_days', 30
        )
        if window_days is not None:
            cutoff = timezone.now().date() - timedelta(days=window_days)
            queryset = queryset.filter(date__gte=cutoff)

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
        pk=pk,
        content_tier__in=allowed_tiers(request),
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
# Media Uploads (Wave 1: images; video/audio arrive in Wave 2)
# =============================================================================

def _sweep_orphan_assets(user):
    """Request-triggered orphan cleanup (no cron exists): on each upload,
    delete this user's own unattached assets older than 24h."""
    cutoff = timezone.now() - timedelta(hours=24)
    orphans = MediaAsset.objects.filter(
        owner=user, created_at__lt=cutoff,
        submission_links__isnull=True, joke_links__isnull=True,
    )
    for asset in orphans:
        asset.delete_with_files()


class MediaUploadView(APIView):
    """POST /media/uploads/ — validate, screen, and store one media file.

    The returned asset id is what the editor attaches to a draft via
    `media_asset_ids`. The whole pipeline is synchronous and in-request
    (single-app constraint): Pillow validate/re-encode → SafeSearch →
    hash-matcher → GCS write.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'media-upload'

    def post(self, request):
        from audit.services import record_audit

        kind = (request.data.get('kind') or 'image').strip()
        if kind != 'image':
            return Response(
                {'kind': ["Only 'image' uploads are supported. Video and audio arrive in Wave 2."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        uploaded = request.FILES.get('file')
        if uploaded is None:
            return Response(
                {'file': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            processed = process_image(uploaded)
        except MediaValidationError as exc:
            return Response(exc.errors, status=status.HTTP_400_BAD_REQUEST)

        verdict = screen_image(processed.data)
        if verdict.get('status') == 'blocked':
            record_audit(
                request, 'safesearch_block', outcome='blocked',
                actor=request.user, target_type='media_upload', target_id='',
            )
            return Response(
                {'file': ['This image was rejected by automated content screening.']},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        hit = get_matcher().match(processed.phash)
        if hit:
            record_audit(
                request, 'hash_match_hit', outcome='blocked',
                actor=request.user, target_type='media_upload', target_id='',
            )
            return Response(
                {'file': ['This image cannot be uploaded.']},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        asset = MediaAsset(
            owner=request.user, kind='image',
            width=processed.width, height=processed.height,
            phash=processed.phash, safesearch=verdict,
        )
        asset.file.save('image.webp', ContentFile(processed.data), save=False)
        try:
            asset.save()
        except Exception:
            # The row never landed, so the orphan sweep (which queries
            # MediaAsset) could never reclaim this file — delete it now.
            asset.file.delete(save=False)
            raise

        _sweep_orphan_assets(request.user)
        record_audit(
            request, 'media_upload', outcome='success', actor=request.user,
            target_type='media_asset', target_id=str(asset.pk),
        )
        serializer = MediaAssetSerializer(asset, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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


class JokeDraftListView(generics.ListCreateAPIView):
    """GET/POST /jokes/my-drafts/

    GET: List the user's drafts and submissions.
    POST: Create a minimal draft for the user from a `format` slug. Drafts are
    allowed to be incomplete — FORMAT_RULES validation only runs at submit
    (JokeDraftSubmitView), not here. Returns the same shape the list returns so
    the frontend's fromDTO works.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = JokeSubmissionListSerializer

    def get_queryset(self):
        return JokeSubmission.objects.filter(
            user=self.request.user
        ).select_related('format', 'age_rating', 'published_joke').prefetch_related(
            'tones', 'context_tags', 'culture_tags', 'media__asset',
        )

    def create(self, request, *args, **kwargs):
        """Create a minimal draft owned by the user from a `format` slug.

        The `format` is required (a Format looked up by slug). The non-null
        age_rating/language FKs are backfilled with sensible defaults (an
        optional `age_rating` slug is honored if supplied). No content/format
        validation is enforced — drafts may be incomplete.
        """
        format_slug = (request.data.get('format') or '').strip()
        if not format_slug:
            return Response(
                {'format': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            fmt = Format.objects.get(slug=format_slug)
        except Format.DoesNotExist:
            return Response(
                {'format': [f"Unknown format '{format_slug}'."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # age_rating is a non-null FK; honor a supplied slug, else default.
        age_rating = None
        age_rating_slug = (request.data.get('age_rating') or '').strip()
        if age_rating_slug:
            age_rating = AgeRating.objects.filter(slug=age_rating_slug).first()
            if age_rating is None:
                return Response(
                    {'age_rating': [f"Unknown age rating '{age_rating_slug}'."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if age_rating is None:
            age_rating = AgeRating.objects.order_by('min_age', 'name').first()

        # language is a non-null FK; default to English, fall back to any.
        language = (
            Language.objects.filter(code='en').first()
            or Language.objects.order_by('code').first()
        )

        if age_rating is None or language is None:
            return Response(
                {'detail': 'Server is missing default age rating / language lookups.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        draft = JokeSubmission.objects.create(
            user=request.user,
            format=fmt,
            age_rating=age_rating,
            language=language,
            status='draft',
        )
        serializer = self.get_serializer(draft)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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

    def get_serializer_context(self):
        # Draft autosave: a partial PATCH of an in-progress draft may still be
        # missing required per-format fields. Skip that validation here so the
        # editor's 800ms autosave persists (returns 200) instead of 400ing and
        # losing typed text. Format validation is enforced at submit instead.
        context = super().get_serializer_context()
        if self.request.method == 'PATCH':
            context['skip_format_validation'] = True
        return context

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status not in ('draft', 'rejected'):
            return Response(
                {'detail': 'Can only edit drafts or rejected submissions.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().update(request, *args, **kwargs)

    def perform_destroy(self, instance):
        assets = [link.asset for link in instance.media.select_related('asset')]
        super().perform_destroy(instance)
        for asset in assets:
            still_used = (
                asset.submission_links.exists() or asset.joke_links.exists()
            )
            if not still_used:
                asset.delete_with_files()


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

        # Draft PATCH skips per-format validation so autosave never loses work;
        # enforce it HERE so an incomplete draft can't reach moderation.
        errors = validate_per_format(
            submission.format.slug,
            {
                'text': submission.text,
                'setup': submission.setup,
                'punchline': submission.punchline,
                'lines': submission.lines,
                'media': [m.asset.kind for m in submission.media.all()],
            },
        )
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

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
            user=self.request.user,
            joke__content_tier__in=allowed_tiers(self.request),
        ).select_related(
            'joke', 'joke__format', 'joke__age_rating', 'joke__language', 'joke__source'
        ).prefetch_related(
            'joke__tones', 'joke__context_tags', 'joke__culture_tags', 'joke__media__asset'
        )

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

    def get_serializer_context(self):
        """Inject the once-per-request paywall decision so the nested
        JokeSerializer can lock/strip the payoff (mirrors JokeViewSet)."""
        ctx = super().get_serializer_context()
        ctx['paywall_state'] = paywall_state(self.request)
        return ctx

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
            'name': public_display_name(user),
            'username': public_handle(user),
            'display_name': profile.display_name,
            'handle': profile.handle,
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
        if 'display_name' in request.data:
            profile.display_name = (request.data['display_name'] or '')[:50]
        if 'handle' in request.data:
            raw = normalize_handle(request.data['handle'])
            if raw == '':
                profile.handle = None
            elif not is_valid_handle(raw):
                return Response(
                    {'handle': ['Handle must be 3-30 chars: lowercase letters, numbers, or underscore.']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            elif UserProfile.objects.exclude(pk=profile.pk).filter(handle=raw).exists():
                return Response(
                    {'handle': ['That handle is already taken.']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                profile.handle = raw

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

        qs = User.objects.filter(joke_submissions__status='published').select_related('profile')

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
            # Public identity via the shared helper — never derived from email.
            name = public_display_name(u)
            # P10: include this user's top 2 vibes (by recency for now;
            # could weight by submission counts later)
            top_vibes = list(
                UserVibe.objects.filter(user=u)
                .select_related('vibe')
                .order_by('-created_at')[:2]
            )
            results.append({
                'id': u.id,
                'name': name,
                'username': public_handle(u),
                'avatar_url': None,
                'punchline_count': u.punchline_count,
                'rank': rank,
                'top_vibes': [
                    {'slug': uv.vibe.slug, 'label': uv.vibe.label, 'icon': uv.vibe.icon}
                    for uv in top_vibes
                ],
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

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Dedup: one pending report per (reporter, joke) — repeat returns the
        # existing one (200) instead of letting users stack the queue.
        existing = ContentReport.objects.filter(
            reporter=request.user, joke=serializer.validated_data['joke'], status='pending',
        ).first()
        if existing:
            return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        instance = serializer.save(reporter=self.request.user)
        from audit.services import record_audit
        record_audit(
            self.request, 'content_report',
            outcome='success',
            actor=self.request.user,
            target_type='joke',
            target_id=str(instance.joke_id) if hasattr(instance, 'joke_id') else '',
            metadata={'reason': getattr(instance, 'reason', '')},
        )


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
        # Blocking severs any follow relationship in both directions.
        from follows.models import Follow
        Follow.objects.filter(follower=request.user, creator=blocked_user).delete()
        Follow.objects.filter(follower=blocked_user, creator=request.user).delete()
        from audit.services import record_audit
        record_audit(request, 'block', outcome='success', actor=request.user,
                     target_type='user', target_id=str(user_id))
        return Response({'status': 'blocked'}, status=status.HTTP_201_CREATED)

    def delete(self, request, user_id):
        UserBlock.objects.filter(blocker=request.user, blocked_id=user_id).delete()
        from audit.services import record_audit
        record_audit(request, 'unblock', outcome='success', actor=request.user,
                     target_type='user', target_id=str(user_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyBlocksView(APIView):
    """GET /users/me/blocks/ — the users I've blocked (for self-management UI)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from follows.serializers import PublicUserSerializer
        from django.contrib.auth import get_user_model
        User = get_user_model()
        blocked_ids = UserBlock.objects.filter(blocker=request.user).values_list('blocked_id', flat=True)
        blocked = User.objects.filter(pk__in=blocked_ids).select_related('profile').order_by('id')
        return Response({'results': PublicUserSerializer(blocked, many=True, context={'request': request}).data})


class UserAccountDeleteView(APIView):
    """DELETE /users/me/ — Re-authenticated hard delete of account (GDPR)."""

    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user
        # Re-authentication gate — must happen BEFORE any mutation
        if user.has_usable_password():
            password = (request.data or {}).get('password')
            if not password:
                return Response(
                    {'password': ['This field is required.']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not user.check_password(password):
                return Response(
                    {'password': ['Incorrect password.']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            # OAuth / unusable-password accounts require a typed confirmation
            if (request.data or {}).get('confirm') != 'DELETE':
                return Response(
                    {'confirm': ['Type DELETE to confirm account deletion.']},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Capture actor identity BEFORE deletion so the audit row has the hash
        from audit.services import record_audit
        from JokesForProject.observability.redaction import hash_email as _hash_email
        actor_id = user.pk
        actor_email_hash = _hash_email(user.email) if user.email else ''

        with transaction.atomic():
            # 1. Blacklist outstanding refresh tokens BEFORE user.delete()
            #    (OutstandingToken.user is SET_NULL; after delete the rows survive
            #    with user_id=NULL and filter(user=user) would miss them)
            if 'rest_framework_simplejwt.token_blacklist' in settings.INSTALLED_APPS:
                from rest_framework_simplejwt.token_blacklist.models import (
                    OutstandingToken, BlacklistedToken,
                )
                for ot in OutstandingToken.objects.filter(user=user):
                    BlacklistedToken.objects.get_or_create(token=ot)

            # 2. Media lifecycle: remove the user's uploaded assets from
            #    storage explicitly — the DB CASCADE alone would orphan the
            #    files (MediaAsset.owner is CASCADE but delete_with_files()
            #    is the only path that also deletes the storage objects).
            for asset in MediaAsset.objects.filter(owner=user):
                asset.delete_with_files()

            # 3. Delete avatar file from the storage backend (safe/idempotent)
            profile = UserProfile.objects.filter(user=user).first()
            if profile and profile.avatar:
                try:
                    profile.avatar.delete(save=False)
                except Exception:
                    pass  # Missing file must not block account deletion

            # 4. Purge email records.
            #    EmailMessageLog.user is SET_NULL, so its rows SURVIVE user.delete()
            #    and MUST be purged explicitly. We match on the user FK OR the
            #    account email; email is immutable in this app (set only at
            #    registration, no change-email feature), so this covers every log.
            #    EmailVerification.user is CASCADE (user.delete() would remove it),
            #    but we purge it explicitly here for immediacy/clarity.
            EmailMessageLog.objects.filter(
                Q(user=user) | Q(to_email__iexact=user.email)
            ).delete()
            EmailVerification.objects.filter(user=user).delete()

            # 5. Cascade-delete the user (removes all FK=CASCADE rows)
            user.delete()

        # Record audit AFTER delete; actor=None (user gone), hash preserved
        record_audit(
            request, 'account_delete',
            outcome='success',
            actor=None,
            target_type='user',
            target_id=str(actor_id),
            metadata={'actor_email_hash': actor_email_hash},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class DataExportView(APIView):
    """GET /users/me/data-export/ — Synchronous GDPR data export (zipped JSON)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        data = {
            'export_meta': {
                'generated_at': timezone.now(),
                'format_version': 1,
                'note': "Full export of your Jokes For data. Other users' personal data is excluded.",
            },
            'account': {
                'id': u.id,
                'email': u.email,
                'username': u.username,
                'date_joined': u.date_joined,
                'last_login': u.last_login,
                'is_active': u.is_active,
            },
            'profile': [
                {
                    'bio': p.bio,
                    'avatar': p.avatar.name or '',
                    'is_premium': p.is_premium,
                    'public_profile': p.public_profile,
                    'show_activity': p.show_activity,
                    'share_analytics': p.share_analytics,
                    'theme': p.theme,
                    'created_at': p.created_at,
                }
                for p in UserProfile.objects.filter(user=u)
            ],
            'preferences': [
                {
                    'notification_enabled': pr.notification_enabled,
                    'notification_days': pr.notification_days,
                    'onboarding_completed': pr.onboarding_completed,
                    'preferred_tones': list(pr.preferred_tones.values_list('slug', flat=True)),
                    'preferred_contexts': list(pr.preferred_contexts.values_list('slug', flat=True)),
                }
                for pr in UserPreference.objects.filter(user=u)
            ],
            'collections': list(
                Collection.objects.filter(user=u).values('id', 'name', 'description', 'is_public', 'created_at')
            ),
            'saved_jokes': [
                {
                    'joke_id': s.joke_id,
                    'joke_text': s.joke.text,
                    'collection': s.collection.name if s.collection else None,
                    'note': s.note,
                    'created_at': s.created_at,
                }
                for s in SavedJoke.objects.filter(user=u).select_related('joke', 'collection')
            ],
            'favorites': [
                {
                    'joke_id': f.joke_id,
                    'joke_text': f.joke.text,
                    'created_at': f.created_at,
                }
                for f in Favorite.objects.filter(user=u).select_related('joke')
            ],
            'ratings': list(
                JokeRating.objects.filter(user=u).values('joke_id', 'rating', 'created_at')
            ),
            'reactions': list(
                JokeReaction.objects.filter(user=u).values('joke_id', 'reaction', 'created_at')
            ),
            'daily_jokes': list(
                DailyJoke.objects.filter(user=u).values('joke_id', 'date', 'delivered_at')
            ),
            'views': list(
                JokeView.objects.filter(user=u)
                .values('joke_id', 'source', 'revealed_punchline', 'viewed_at')[:5000]
            ),
            'streak': list(
                Streak.objects.filter(user=u).values(
                    'current_count', 'longest_count', 'last_active_date',
                    'freeze_days_available', 'freezes_used_total',
                )
            ),
            'streak_days': list(
                StreakDay.objects.filter(user=u).values('date', 'status')
            ),
            'submissions': list(
                JokeSubmission.objects.filter(user=u).values(
                    'id', 'text', 'setup', 'punchline', 'status', 'created_at'
                )
            ),
            'media_assets': [
                {
                    'id': str(asset.pk),
                    'kind': asset.kind,
                    'url': request.build_absolute_uri(asset.file.url) if asset.file else None,
                    'created_at': asset.created_at.isoformat(),
                }
                for asset in MediaAsset.objects.filter(owner=u)
            ],
            'reports_filed': list(
                ContentReport.objects.filter(reporter=u).values(
                    'joke_id', 'reason', 'description', 'status', 'created_at'
                )
            ),
            'blocks': list(
                UserBlock.objects.filter(blocker=u).values('blocked_id', 'created_at')
            ),
            'achievements': list(
                UserAchievement.objects.filter(user=u).values(
                    'achievement__slug', 'achievement__title', 'unlocked_at'
                )
            ),
            'vibes': list(
                UserVibe.objects.filter(user=u).values('vibe__slug', 'weight', 'created_at')
            ),
            'pack_progress': list(
                JokePackProgress.objects.filter(user=u).values(
                    'pack__slug', 'last_read_entry', 'completed_at'
                )
            ),
            'mystery_rolls': list(
                MysteryBoxRoll.objects.filter(user=u).values(
                    'joke_id', 'source_vibe__slug', 'rolled_date'
                )
            ),
            'share_events': list(
                ShareEvent.objects.filter(user=u).values('joke_id', 'platform', 'created_at')
            ),
            'email_logs': list(
                EmailMessageLog.objects.filter(
                    Q(user=u) | Q(to_email__iexact=u.email)
                ).values('to_email', 'template_name', 'subject', 'status', 'created_at', 'sent_at')
            ),
        }
        payload = json.dumps(data, cls=DjangoJSONEncoder, indent=2)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('jokes-for-data-export.json', payload)
        buf.seek(0)
        resp = HttpResponse(buf.getvalue(), content_type='application/zip')
        resp['Content-Disposition'] = 'attachment; filename="jokes-for-data-export.zip"'
        from audit.services import record_audit
        record_audit(request, 'data_export', outcome='success', actor=u)
        return resp


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

def _mystery_pool_for_user(user, allowed=frozenset({'tier_1'})):
    """Build the joke pool a user can be served from the Mystery Box.

    Strategy:
      1. Union of jokes matching every vibe the user picked (their "pool").
      2. If no vibes / empty pool → fall back to the global joke pool.
      3. Filter to allowed content tiers (serving lock).
      4. Exclude jokes already rolled today by this user (no same-day repeats).
      5. Exclude jokes the user has already saved (already in their library).

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

    # Apply content-tier serving lock
    pool = pool.filter(content_tier__in=allowed)

    # Moderation: exclude blocked users' jokes (removed already excluded by manager).
    hidden = hidden_user_ids(user)
    if hidden:
        pool = pool.exclude(creator_id__in=hidden)

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
        max_per_day = entitlements.get_limit(request.user, 'mystery_box_rolls_per_day', default=MysteryBoxRoll.MAX_DAILY_ROLLS)
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
        if used >= entitlements.get_limit(request.user, 'mystery_box_rolls_per_day', default=MysteryBoxRoll.MAX_DAILY_ROLLS):
            return Response(
                {
                    'detail': 'Daily Mystery Box limit reached. Resets at midnight UTC.',
                    'rolls_used_today': used,
                    'rolls_remaining_today': 0,
                    'max_per_day': entitlements.get_limit(request.user, 'mystery_box_rolls_per_day', default=MysteryBoxRoll.MAX_DAILY_ROLLS),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        pool, source_vibe = _mystery_pool_for_user(request.user, allowed=allowed_tiers(request))
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

        ctx = {'request': request, 'paywall_state': paywall_state(request)}
        return Response({
            'joke': JokeSerializer(joke, context=ctx).data,
            'rolls_remaining_today': entitlements.get_limit(request.user, 'mystery_box_rolls_per_day', default=MysteryBoxRoll.MAX_DAILY_ROLLS) - used - 1,
            'source_vibe': VibeSerializer(source_vibe).data if source_vibe else None,
        })


# =============================================================================
# Recently Viewed (P5 of Pivot Plan)
# =============================================================================

class RecentlyViewedView(APIView):
    """GET /api/v1/users/me/recently-viewed/?limit=20 — chronological view log.

    Powers "continue mid-sip" + Today's "what you've been laughing at" rail.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(name='limit', type=int, description='Max rows (default 20, max 100)'),
        ],
        responses={200: JokeViewSerializer(many=True)},
    )
    def get(self, request):
        try:
            limit = min(int(request.query_params.get('limit', 20)), 100)
        except ValueError:
            limit = 20
        qs = (
            JokeView.objects.filter(
                user=request.user,
                joke__content_tier__in=allowed_tiers(request),
            )
            .select_related('joke', 'joke__format', 'joke__age_rating', 'joke__language')
            .prefetch_related('joke__tones', 'joke__context_tags', 'joke__media__asset')
            .order_by('-viewed_at')[:limit]
        )
        ctx = {'request': request, 'paywall_state': paywall_state(request)}
        return Response(JokeViewSerializer(qs, many=True, context=ctx).data)


# =============================================================================
# Streak (P6 of Pivot Plan)
# =============================================================================

def _reconcile_streak(streak):
    """Lazy gap reconciliation on /streak/ read — handles the case where the
    user opens their streak page after multiple inactive days.

    Reuses the same _walk_gap helper used by the JokeView signal so behaviour
    stays consistent between read-path and write-path reconciliation.
    """
    from django.utils import timezone
    from .signals import _walk_gap

    if not streak.last_active_date:
        return

    # Refresh freezes if month rolled over
    current_month = timezone.now().strftime('%Y-%m')
    if streak.last_freeze_refresh_month != current_month:
        streak.freeze_days_available = Streak.FREEZES_PER_MONTH
        streak.last_freeze_refresh_month = current_month

    today = timezone.now().date()
    _walk_gap(streak, today)
    streak.save()


class StreakView(APIView):
    """GET /api/v1/users/me/streak/  → reconciled streak state + 14-day grid + risk flag.
    POST /api/v1/users/me/streak/freeze/        → manually use a freeze (vacation mode).
    POST /api/v1/users/me/streak/freeze/remove/ → undo today's accidental freeze.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: StreakSerializer})
    def get(self, request):
        streak, _ = Streak.objects.get_or_create(user=request.user)
        _reconcile_streak(streak)
        return Response(StreakSerializer(streak).data)


class StreakFreezeView(APIView):
    """Manual freeze for today — vacation-mode override."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone
        streak, _ = Streak.objects.get_or_create(user=request.user)
        if streak.freeze_days_available <= 0:
            return Response(
                {'detail': 'No freeze days available this month.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        today = timezone.now().date()
        existing = StreakDay.objects.filter(user=request.user, date=today).first()
        if existing and existing.status == StreakDay.STATUS_READ:
            return Response(
                {'detail': 'Already counted today — no need to freeze.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            StreakDay.objects.update_or_create(
                user=request.user, date=today,
                defaults={'status': StreakDay.STATUS_FROZEN},
            )
            streak.freeze_days_available -= 1
            streak.freezes_used_total += 1
            streak.last_active_date = today  # frozen days count for continuity
            streak.save()
        return Response(StreakSerializer(streak).data)


class StreakFreezeRemoveView(APIView):
    """Undo a freeze used today."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone
        today = timezone.now().date()
        streak, _ = Streak.objects.get_or_create(user=request.user)
        existing = StreakDay.objects.filter(
            user=request.user, date=today, status=StreakDay.STATUS_FROZEN
        ).first()
        if not existing:
            return Response(
                {'detail': "No freeze to remove for today."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            existing.delete()
            streak.freeze_days_available += 1
            streak.freezes_used_total = max(0, streak.freezes_used_total - 1)
            streak.save()
        return Response(StreakSerializer(streak).data)


# =============================================================================
# Joke Packs (P7 of Pivot Plan)
# =============================================================================

class JokePackViewSet(viewsets.ReadOnlyModelViewSet):
    """Editor-curated joke packs.

    - GET /api/v1/packs/                  → published packs (paginated)
    - GET /api/v1/packs/{slug}/           → pack with embedded ordered jokes
    - GET /api/v1/packs/featured/         → single featured pack (Weekly Special)
    """
    lookup_field = 'slug'
    permission_classes = [AllowAny]

    def get_queryset(self):
        from django.utils import timezone
        now = timezone.now()
        qs = JokePack.objects.filter(is_published=True)
        # Honor publish/expire windows
        qs = qs.filter(
            Q(publish_at__isnull=True) | Q(publish_at__lte=now)
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )
        return qs.prefetch_related('entries')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return JokePackDetailSerializer
        return JokePackListSerializer

    def get_serializer_context(self):
        """Inject the paywall decision so embedded pack jokes lock/strip too."""
        ctx = super().get_serializer_context()
        ctx['paywall_state'] = paywall_state(self.request)
        return ctx

    @extend_schema(
        description='The currently featured pack (the Today screen Weekly Special).',
        responses={200: JokePackDetailSerializer, 404: None},
    )
    @action(detail=False, methods=['get'])
    def featured(self, request):
        """GET /api/v1/packs/featured/ — currently featured pack."""
        pack = self.get_queryset().filter(is_featured=True).first()
        if pack is None:
            return Response(
                {'detail': 'No featured pack at the moment.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        ctx = {'request': request, 'paywall_state': paywall_state(request)}
        return Response(JokePackDetailSerializer(pack, context=ctx).data)


class JokePackProgressView(APIView):
    """Record progress through a pack and resume later.

    POST /api/v1/packs/{slug}/progress/  body: { "entry_order": N }
                                         marks user at entry N (0 = restart)
                                         If N >= last entry's order → mark complete
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        pack = get_object_or_404(JokePack, slug=slug, is_published=True)
        ser = JokePackProgressUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        entry_order = ser.validated_data['entry_order']

        max_order = pack.entries.aggregate(m=Max('order'))['m'] or 0

        with transaction.atomic():
            progress, _ = JokePackProgress.objects.get_or_create(
                user=request.user, pack=pack
            )
            progress.last_read_entry = entry_order
            if entry_order >= max_order and max_order > 0:
                from django.utils import timezone
                progress.completed_at = progress.completed_at or timezone.now()
            else:
                progress.completed_at = None  # un-complete if user goes back
            progress.save()

        return Response({
            'last_read_entry': progress.last_read_entry,
            'completed_at': progress.completed_at,
            'is_complete': progress.completed_at is not None,
        })


class JokePackInProgressView(APIView):
    """GET /api/v1/users/me/packs/in-progress/ — packs the user has started but not finished."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: JokePackListSerializer(many=True)})
    def get(self, request):
        progress_qs = (
            JokePackProgress.objects
            .filter(user=request.user, completed_at__isnull=True, last_read_entry__gt=0)
            .select_related('pack')
            .order_by('-updated_at')
        )
        packs = [p.pack for p in progress_qs if p.pack.is_published]
        return Response(
            JokePackListSerializer(packs, many=True, context={'request': request}).data
        )


# =============================================================================
# Daily Ritual Status (P8 of Pivot Plan)
# =============================================================================

class DailyRitualStatusView(APIView):
    """GET /api/v1/users/me/today-status/ — flags for the Today surface.

    Replaces the 9 AM daily push: frontend polls this and renders "Today's
    joke is ready" when daily_joke_due is true. Cloud Run-friendly (no cron).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description='Per-user surface flags computed on demand.',
        responses={200: {'type': 'object', 'properties': {
            'daily_joke_due': {'type': 'boolean'},
            'has_read_today': {'type': 'boolean'},
            'today_is_a_notification_day': {'type': 'boolean'},
            'now_past_notification_time': {'type': 'boolean'},
        }}},
    )
    def get(self, request):
        from django.utils import timezone
        from .models import UserPreference

        now = timezone.now()
        today = now.date()
        weekday = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][today.weekday()]

        pref, _ = UserPreference.objects.get_or_create(user=request.user)

        # Has the user read today? (via JokeView)
        has_read_today = JokeView.objects.filter(
            user=request.user, viewed_date=today
        ).exists()

        days = pref.notification_days or []
        today_is_day = (weekday in days) if days else True
        notification_time = pref.notification_time
        now_past = (
            notification_time is None
            or now.time() >= notification_time
        )

        # daily_joke_due: it's a notification day, we're past the time, user
        # hasn't read yet, and they have notifications enabled (or no
        # preference set yet — default to showing the surface).
        daily_joke_due = (
            today_is_day
            and now_past
            and not has_read_today
            and (pref.notification_enabled or not pref.notification_time)
        )

        return Response({
            'daily_joke_due': daily_joke_due,
            'has_read_today': has_read_today,
            'today_is_a_notification_day': today_is_day,
            'now_past_notification_time': now_past,
        })


# =============================================================================
# Insights (P9 of Pivot Plan) — taste profile, tomorrow teaser, issue numbering
# =============================================================================

LAUNCH_DATE_FOR_ISSUE_NUMBERING = None  # lazily computed in helper


def _issue_label_for(date_obj):
    """Newspaper-style issue label like 'Vol. I · No. 042'.

    Issue 1 = the day the first DailyJoke ever existed (or today if none yet).
    Volume rolls over every 365 issues.
    """
    from .models import DailyJoke
    earliest = DailyJoke.objects.aggregate(min_date=Min('date'))['min_date']
    if earliest is None:
        earliest = date_obj
    days_since = (date_obj - earliest).days
    issue = days_since + 1
    volume_index = (issue - 1) // 365 + 1
    issue_in_volume = ((issue - 1) % 365) + 1
    roman = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']
    vol_str = roman[volume_index - 1] if volume_index <= len(roman) else str(volume_index)
    return f"Vol. {vol_str} · No. {issue_in_volume:03d}"


def _select_daily_joke_for(user, target_date, allowed=frozenset({'tier_1'})):
    """Lazy selection of a DailyJoke for the user on target_date — generates
    the row if it doesn't exist yet (replaces the Celery beat task)."""
    from .models import DailyJoke
    existing = DailyJoke.objects.filter(user=user, date=target_date).first()
    if existing:
        return existing
    # Pick a joke (favor user's vibes, fall back to global — both filtered by allowed tiers)
    pool, _ = _mystery_pool_for_user(user, allowed=allowed)
    joke = pool.order_by('?').first() or Joke.objects.filter(
        content_tier__in=allowed
    ).order_by('?').first()
    if joke is None:
        return None
    daily, _ = DailyJoke.objects.get_or_create(
        user=user, date=target_date, defaults={'joke': joke}
    )
    return daily


class TasteProfileView(APIView):
    """GET /api/v1/users/me/taste-profile/ — derived analytics from JokeView,
    SavedJoke, JokeReaction. No new model, no caching (small scale)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(name='period', type=str, description='Window: month (default) | week | all'),
        ],
        responses={200: {'type': 'object'}},
    )
    def get(self, request):
        from django.utils import timezone
        from datetime import timedelta

        period = request.query_params.get('period', 'month')
        if period == 'week':
            since = timezone.now().date() - timedelta(days=6)
        elif period == 'all':
            since = None
        else:
            period = 'month'
            since = timezone.now().date() - timedelta(days=29)

        view_qs = JokeView.objects.filter(user=request.user)
        save_qs = SavedJoke.objects.filter(user=request.user)
        if since:
            view_qs = view_qs.filter(viewed_date__gte=since)
            save_qs = save_qs.filter(created_at__date__gte=since)

        jokes_read = view_qs.values('joke').distinct().count()
        jokes_saved = save_qs.count()

        # Peak read hour
        peak = (
            view_qs.annotate(h=ExtractHour('viewed_at'))
            .values('h').annotate(n=Count('id')).order_by('-n').first()
        )
        peak_hour = peak['h'] if peak else None

        # Top vibe (by user's selected ones, ordered by recency for now;
        # could later weight by view frequency per recipe)
        top_vibe_qs = UserVibe.objects.filter(user=request.user).select_related('vibe').order_by('-created_at')[:1]
        top_vibe = VibeSerializer(top_vibe_qs[0].vibe).data if top_vibe_qs else None

        # Top themes / categories / formats from viewed jokes
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

        # 28-day sparkline of daily read counts
        today = timezone.now().date()
        start = today - timedelta(days=27)
        daily_counts = (
            view_qs.filter(viewed_date__gte=start)
            .values('viewed_date').annotate(c=Count('id'))
        )
        sparkline_map = {row['viewed_date']: row['c'] for row in daily_counts}
        daily_reads_28d = [sparkline_map.get(start + timedelta(days=i), 0) for i in range(28)]

        return Response({
            'period': period,
            'jokes_read': jokes_read,
            'jokes_saved': jokes_saved,
            'peak_read_hour': peak_hour,
            'top_vibe': top_vibe,
            'top_themes': [{'label': r['joke__context_tags__name'], 'count': r['c']} for r in top_themes],
            'top_categories': [{'label': r['joke__tones__name'], 'count': r['c']} for r in top_categories],
            'top_formats': [{'label': r['joke__format__name'], 'count': r['c']} for r in top_formats],
            'daily_reads_28d': daily_reads_28d,
        })


class TelemetryIngestView(APIView):
    """Bulk, fire-and-forget audience-telemetry ingest.

    POST /api/v1/telemetry/events
    Body: {"events": [
        {"joke": <id>, "type": "impression"|"reveal", "source": "<str>"},
        {"joke": <id>, "type": "dwell", "value": <ms>, "scroll_pct": <0-100>, "source": "<str>"},
    ]}

    Request-driven only (no Celery/cron). Cheap: caps the batch, dedups
    impressions to one per (user, joke, day), appends dwell samples, and never
    500s on partial bad data — bad/unknown events are skipped silently.
    Returns 202 + {"accepted": N}.
    """
    permission_classes = [IsAuthenticated]

    MAX_BATCH = 50

    # Dwell clamps (Phase 2): cap at 10 min, ignore sub-half-second blips as noise.
    DWELL_MAX_MS = 600000
    DWELL_MIN_MS = 500

    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'events': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'joke': {'type': 'integer'},
                                'type': {'type': 'string', 'enum': ['impression', 'reveal', 'dwell']},
                                'value': {'type': 'integer', 'description': 'dwell milliseconds (dwell events only)'},
                                'scroll_pct': {'type': 'integer', 'description': '0-100 read-through depth (optional, dwell events only)'},
                                'source': {'type': 'string'},
                            },
                        },
                    },
                },
            }
        },
        responses={202: {'type': 'object', 'properties': {'accepted': {'type': 'integer'}}}},
    )
    def post(self, request):
        events = request.data.get('events') or []
        if not isinstance(events, list):
            events = []
        events = events[:self.MAX_BATCH]

        user = request.user
        today = timezone.now().date()
        accepted = 0

        for event in events:
            try:
                if not isinstance(event, dict):
                    continue
                joke_id = event.get('joke')
                etype = event.get('type')
                source = event.get('source') or 'other'
                if not isinstance(source, str):
                    source = 'other'
                source = source[:16]

                if joke_id is None or etype not in ('impression', 'reveal', 'dwell'):
                    continue
                if not Joke.objects.filter(pk=joke_id).exists():
                    continue

                if etype == 'dwell':
                    # Append-only dwell sample. Clamp ms to [0, 10min];
                    # drop sub-DWELL_MIN_MS blips as noise.
                    raw = event.get('value')
                    if not isinstance(raw, int) or isinstance(raw, bool):
                        continue
                    dwell_ms = max(0, min(raw, self.DWELL_MAX_MS))
                    if dwell_ms < self.DWELL_MIN_MS:
                        continue

                    scroll_pct = event.get('scroll_pct')
                    if isinstance(scroll_pct, bool) or not isinstance(scroll_pct, int):
                        scroll_pct = None
                    else:
                        scroll_pct = max(0, min(scroll_pct, 100))

                    JokeDwell.objects.create(
                        user=user,
                        joke_id=joke_id,
                        dwell_ms=dwell_ms,
                        scroll_pct=scroll_pct,
                        source=source,
                        created_date=today,
                    )
                    accepted += 1
                elif etype == 'impression':
                    # Dedup to one impression per (user, joke, day).
                    JokeImpression.objects.get_or_create(
                        user=user,
                        joke_id=joke_id,
                        created_date=today,
                        defaults={'source': source},
                    )
                    accepted += 1
                else:  # 'reveal'
                    # (etype == 'reveal')
                    view = (
                        JokeView.objects.filter(user=user, joke_id=joke_id)
                        .order_by('-viewed_at').first()
                    )
                    if view is not None:
                        if not view.revealed_punchline:
                            view.revealed_punchline = True
                            view.save(update_fields=['revealed_punchline'])
                    else:
                        JokeView.objects.create(
                            user=user,
                            joke_id=joke_id,
                            source=source,
                            revealed_punchline=True,
                        )
                    accepted += 1
            except Exception:
                # Fire-and-forget: never fail the batch on one bad event.
                continue

        return Response({'accepted': accepted}, status=status.HTTP_202_ACCEPTED)


