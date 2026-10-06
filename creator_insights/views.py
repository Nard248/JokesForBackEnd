from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.permissions import HasFeature
from creator_insights.permissions import IsCreator
from creator_insights.serializers import CreatorInsightsSerializer, CreatorProfileSerializer
from creator_insights.services import build_creator_insights, build_creator_profile
from creator_insights.throttles import CreatorInsightsThrottle
from jokes.serializers import JokeListSerializer
from jokes.serving import allowed_tiers

User = get_user_model()


class CreatorInsightsView(APIView):
    """GET /api/v1/creators/me/insights/?period=month|week|all

    Returns creator audience intelligence metrics for the authenticated creator.
    Requires an authenticated author with currently published content.
    Owner metrics include tier_2 jokes, but their text follows the account's
    current age and mature-content preference. No audience identities are exposed.
    """
    permission_classes = [IsAuthenticated, IsCreator, HasFeature('creator_analytics')]
    throttle_classes = [CreatorInsightsThrottle]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='period',
                type=str,
                description='Analytics window: month (default) | week | all',
            ),
        ],
        responses={200: CreatorInsightsSerializer},
    )
    def get(self, request):
        period = request.query_params.get('period', 'month')
        data = build_creator_insights(
            request.user, period, allowed_content_tiers=allowed_tiers(request),
        )
        return Response(data)


class CreatorProfileView(APIView):
    """GET /api/v1/creators/<creator_id>/profile/

    Public profile for a creator. Returns 404 if the user doesn't exist or
    has no published jokes visible to the requester.
    is_following is set only when authenticated and not viewing own profile.
    """
    permission_classes = [AllowAny]

    @extend_schema(responses={200: CreatorProfileSerializer})
    def get(self, request, creator_id):
        creator = get_object_or_404(User, pk=creator_id)
        viewer = getattr(request, 'user', None)
        # Symmetric block: a blocked pair can't see each other's profile.
        if viewer is not None and viewer.is_authenticated:
            from jokes.moderation import is_blocked_between
            if is_blocked_between(viewer, creator):
                raise NotFound('Creator not found or has no published jokes.')
        tiers = allowed_tiers(request)
        data, jokes = build_creator_profile(creator, viewer, tiers)
        if data is None:
            raise NotFound('Creator not found or has no published jokes.')

        # Paginate + serialize the tier-filtered jokes for the viewer.
        paginator = PageNumberPagination()
        paginator.page_size = 10
        jokes = jokes.select_related(
            'format', 'age_rating', 'language', 'origin_country',
        ).prefetch_related('tones', 'media__asset')
        page = paginator.paginate_queryset(jokes, request, view=self)
        serializer = JokeListSerializer(page, many=True, context={'request': request})
        data['jokes'] = serializer.data
        data['jokes_pagination'] = {
            'count': paginator.page.paginator.count,
            'next': paginator.get_next_link(),
            'previous': paginator.get_previous_link(),
        }
        return Response(data)
