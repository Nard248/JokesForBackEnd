from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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
    Requires IsAuthenticated + IsCreator (at least one published joke submission).
    Owner-scoped: the creator's own tier_2 jokes are visible here; this endpoint
    does NOT expose any other user's personal data.
    """
    permission_classes = [IsAuthenticated, IsCreator]
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
        data = build_creator_insights(request.user, period)
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
        tiers = allowed_tiers(request)
        viewer = getattr(request, 'user', None)
        data, jokes = build_creator_profile(creator, viewer, tiers)
        if data is None:
            raise NotFound('Creator not found or has no published jokes.')

        # Paginate + serialize the tier-filtered jokes for the viewer.
        paginator = PageNumberPagination()
        paginator.page_size = 10
        page = paginator.paginate_queryset(jokes, request, view=self)
        serializer = JokeListSerializer(page, many=True, context={'request': request})
        data['jokes'] = serializer.data
        data['jokes_pagination'] = {
            'count': paginator.page.paginator.count,
            'next': paginator.get_next_link(),
            'previous': paginator.get_previous_link(),
        }
        return Response(data)
