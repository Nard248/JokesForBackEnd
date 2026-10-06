from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from billing.permissions import HasFeature
from communities import services
from communities.models import Community
from creator_insights.permissions import IsCreator
from creator_insights.throttles import CreatorInsightsThrottle
from jokes.discovery import DISCOVERY_PARAMETERS, discovery_pool
from jokes.models import Joke
from jokes.paywall import paywall_state
from jokes.serializers import JokeSerializer

COMMUNITY_ROW = inline_serializer(name='CommunityRow', fields={
    'slug': serializers.CharField(), 'name': serializers.CharField(),
    'description': serializers.CharField(), 'emoji': serializers.CharField(),
    'color': serializers.CharField(),
    'status': serializers.ChoiceField(choices=['active', 'forming', 'cooling']),
    'members': serializers.IntegerField(allow_null=True),
    'engaged_members': serializers.IntegerField(allow_null=True),
    'growth': serializers.IntegerField(allow_null=True),
    'score': serializers.FloatField(), 'joke_count': serializers.IntegerField(),
    'activity': serializers.ListField(child=serializers.IntegerField()),
    'explanation': serializers.CharField(),
    'viewer': serializers.DictField(allow_null=True),
})


def _listed(slug):
    return get_object_or_404(Community.objects.select_related('tag'), tag__slug=slug, is_listed=True)


class CommunityDirectoryView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id='communities_directory',
        description='Self-forming theme communities: aggregate state for everyone, plus your own '
                    'affinity when signed in. Counts under five are null; no individual is exposed.',
        responses={200: inline_serializer(name='CommunityDirectory', fields={
            'generated_at': serializers.CharField(),
            'stats': serializers.DictField(),
            'viewer': serializers.DictField(allow_null=True),
            'communities': serializers.ListField(child=COMMUNITY_ROW),
            'bridges': serializers.ListField(child=serializers.DictField()),
            'methodology': serializers.DictField(),
        })},
    )
    def get(self, request):
        return Response(services.directory(request.user))


class CommunityDetailView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id='communities_detail',
        description='One community: its state, trending and newest jokes visible to you, public '
                    'creators on the theme and overlapping communities. Jokes and creators follow '
                    'the discovery selectors (omitted language = your default language).',
        parameters=DISCOVERY_PARAMETERS,
        responses={200: inline_serializer(name='CommunityDetail', fields={
            'community': COMMUNITY_ROW,
            'trending': serializers.ListField(child=serializers.DictField()),
            'newest': serializers.ListField(child=serializers.DictField()),
            'creators': serializers.ListField(child=serializers.DictField()),
            'bridges': serializers.ListField(child=serializers.DictField()),
        })},
    )
    def get(self, request, slug):
        community = _listed(slug)
        data = services.aggregate()
        ctx = services.viewer_context(request.user)
        viewer = services.viewer_states(request.user, [community]).get(community.pk) if ctx else None
        # The discovery pool (tiers, takedowns, blocks, content selection with
        # the viewer's default language) is applied as a pk subquery so the
        # community scoring aggregates are not multiplied by selector joins.
        base = (
            Joke.objects.filter(pk__in=discovery_pool(request).values('pk'))
            .select_related('format', 'age_rating', 'language', 'source', 'origin_country', 'creator__profile')
            .prefetch_related('tones', 'context_tags', 'culture_tags', 'countries', 'media__asset')
        )
        trending, newest = services.community_jokes(community, base)
        context = {'request': request, 'paywall_state': paywall_state(request)}
        return Response({
            'community': services.community_row(community, data, viewer, ctx),
            'trending': JokeSerializer(trending, many=True, context=context).data,
            'newest': JokeSerializer(newest, many=True, context=context).data,
            'creators': services.community_creators(community, base),
            'bridges': services.community_bridges(community, data),
        })


class MembershipInput(serializers.Serializer):
    action = serializers.ChoiceField(choices=['join', 'leave'])


class CommunityMembershipView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'community_membership'

    @extend_schema(request=MembershipInput, responses={200: COMMUNITY_ROW},
                   description='Explicitly join or leave. Leaving stops automatic membership until you rejoin.')
    def post(self, request, slug):
        community = _listed(slug)
        payload = MembershipInput(data=request.data)
        payload.is_valid(raise_exception=True)
        services.set_membership(request.user, community, payload.validated_data['action'])
        ctx = services.viewer_context(request.user)
        viewer = services.viewer_states(request.user, [community]).get(community.pk)
        return Response(services.community_row(community, services.aggregate(), viewer, ctx))


class CreatorCommunityReachView(APIView):
    """Creator Pro: the communities your consenting audience belongs to."""

    permission_classes = [IsAuthenticated, IsCreator, HasFeature('creator_community_insights')]
    throttle_classes = [CreatorInsightsThrottle]

    @extend_schema(responses={200: inline_serializer(name='CreatorCommunityReach', fields={
        'window_days': serializers.IntegerField(),
        'audience': serializers.DictField(),
        'communities': serializers.ListField(child=serializers.DictField()),
        'opportunities': serializers.ListField(child=serializers.DictField()),
        'measurement_notes': serializers.ListField(child=serializers.CharField()),
    })})
    def get(self, request):
        response = Response(services.creator_reach(request.user))
        response['Cache-Control'] = 'no-store'
        return response
