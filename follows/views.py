from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from follows import services
from follows.models import Follow
from follows.serializers import PublicUserSerializer, FollowStatusSerializer
from jokes.moderation import hidden_user_ids

User = get_user_model()


class FollowView(APIView):
    """POST to follow, DELETE to unfollow."""
    permission_classes = [IsAuthenticated]

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

    def delete(self, request, creator_id):
        creator = get_object_or_404(User, pk=creator_id)
        services.unfollow(request.user, creator)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FollowStatusView(APIView):
    """GET {is_following, follower_count}."""
    permission_classes = [IsAuthenticated]

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
