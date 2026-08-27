from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from follows import services
from follows.models import Follow
from follows.serializers import FollowStatusSerializer, PublicUserSerializer
from jokes.moderation import hidden_user_ids

User = get_user_model()

# Shape of one PublicUserSerializer row. Declared inline rather than pointing the
# schema at the serializer because name/username/avatar_url are
# SerializerMethodFields with no return-type hints — drf-spectacular would type
# avatar_url as a non-nullable string, which breaks a strict generated client the
# first time a user has no avatar.
_PUBLIC_USER_SCHEMA = {
    'type': 'object',
    'properties': {
        'id': {'type': 'integer'},
        'name': {'type': 'string', 'description': 'Display name — never the email address.'},
        'username': {'type': 'string', 'description': 'Public @handle, e.g. "@someone".'},
        'avatar_url': {'type': 'string', 'format': 'uri', 'nullable': True},
    },
}


def _paginated(item_schema):
    """PageNumberPagination envelope around ``item_schema`` (these views build
    their paginator by hand, so drf-spectacular cannot infer the wrapper)."""
    return {'type': 'object', 'properties': {
        'count': {'type': 'integer'},
        'next': {'type': 'string', 'format': 'uri', 'nullable': True},
        'previous': {'type': 'string', 'format': 'uri', 'nullable': True},
        'results': {'type': 'array', 'items': item_schema},
    }}


_FOLLOW_RESULT_SCHEMA = {'type': 'object', 'properties': {
    'is_following': {'type': 'boolean'},
    'follower_count': {'type': 'integer'},
}}


class FollowView(APIView):
    """POST to follow, DELETE to unfollow."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            'Follow the creator. Idempotent: 201 when the follow row is created, '
            '200 when it already existed. Takes no request body.'
        ),
        request=None,
        responses={
            201: _FOLLOW_RESULT_SCHEMA,
            200: _FOLLOW_RESULT_SCHEMA,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}},
                  'description': 'Rejected by validation (e.g. self-follow).'},
            404: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
    )
    def post(self, request, creator_id):
        creator = get_object_or_404(User, pk=creator_id)
        try:
            _, created = services.follow(request.user, creator)
        except ValidationError as exc:
            # Only surface validation messages (e.g. self-follow). Let any other
            # exception propagate to DRF's handler → logged + generic 500 (no
            # internal-error leakage to the client).
            return Response({'detail': exc.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        st = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response({
            'is_following': True,
            'follower_count': services.follower_count(creator),
        }, status=st)

    @extend_schema(
        description='Unfollow the creator. Idempotent — 204 with no body even if not following.',
        request=None,
        responses={204: None, 404: {'type': 'object', 'properties': {'detail': {'type': 'string'}}}},
    )
    def delete(self, request, creator_id):
        creator = get_object_or_404(User, pk=creator_id)
        services.unfollow(request.user, creator)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FollowStatusView(APIView):
    """GET {is_following, follower_count}."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Whether the caller follows this creator, plus the creator's follower count.",
        responses={
            200: FollowStatusSerializer,
            404: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
    )
    def get(self, request, creator_id):
        creator = get_object_or_404(User, pk=creator_id)
        data = {
            'is_following': services.is_following(request.user, creator),
            'follower_count': services.follower_count(creator),
        }
        return Response(FollowStatusSerializer(data).data)


class FollowersListView(APIView):
    """GET paginated list of followers for a creator."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            'Followers of this creator, page size 10. Anyone on either side of a block '
            'with the caller is omitted.'
        ),
        parameters=[
            OpenApiParameter(name='page', type=int, description='1-based page number.'),
        ],
        responses={
            200: _paginated(_PUBLIC_USER_SCHEMA),
            404: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
    )
    def get(self, request, creator_id):
        creator = get_object_or_404(User, pk=creator_id)
        follower_ids = (
            Follow.objects.filter(creator=creator)
            .order_by('-created_at')
            .values_list('follower_id', flat=True)
        )
        followers = (
            User.objects.filter(pk__in=follower_ids)
            .exclude(pk__in=hidden_user_ids(request.user))
            .order_by('id')
        )
        paginator = PageNumberPagination()
        paginator.page_size = 10
        page = paginator.paginate_queryset(followers, request)
        serializer = PublicUserSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)


class MyFollowingView(APIView):
    """GET paginated list of creators I follow."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            'Creators the caller follows, page size 10. Anyone on either side of a block '
            'with the caller is omitted.'
        ),
        parameters=[
            OpenApiParameter(name='page', type=int, description='1-based page number.'),
        ],
        responses={200: _paginated(_PUBLIC_USER_SCHEMA)},
    )
    def get(self, request):
        creator_ids = (
            Follow.objects.filter(follower=request.user)
            .order_by('-created_at')
            .values_list('creator_id', flat=True)
        )
        creators = (
            User.objects.filter(pk__in=creator_ids)
            .exclude(pk__in=hidden_user_ids(request.user))
            .order_by('id')
        )
        paginator = PageNumberPagination()
        paginator.page_size = 10
        page = paginator.paginate_queryset(creators, request)
        serializer = PublicUserSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)
