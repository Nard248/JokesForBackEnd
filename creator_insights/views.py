from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from creator_insights.permissions import IsCreator
from creator_insights.serializers import CreatorInsightsSerializer
from creator_insights.services import build_creator_insights


class CreatorInsightsView(APIView):
    """GET /api/v1/creators/me/insights/?period=month|week|all

    Returns creator audience intelligence metrics for the authenticated creator.
    Requires IsAuthenticated + IsCreator (at least one published joke submission).
    Owner-scoped: the creator's own tier_2 jokes are visible here; this endpoint
    does NOT expose any other user's personal data.
    """
    permission_classes = [IsAuthenticated, IsCreator]

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
