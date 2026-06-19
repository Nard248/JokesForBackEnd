"""
Serializer for creator insights — used for drf-spectacular schema documentation only.
The view returns the service dict directly via Response; this serializer documents
the expected response shape.
"""
from rest_framework import serializers


class OverviewSerializer(serializers.Serializer):
    published_jokes = serializers.IntegerField()
    reach = serializers.IntegerField()
    views = serializers.IntegerField()
    payoff_rate = serializers.FloatField(allow_null=True)
    reactions = serializers.IntegerField()
    favorites = serializers.IntegerField()
    saves = serializers.IntegerField()
    shares = serializers.IntegerField()
    peak_read_hour = serializers.IntegerField(allow_null=True)
    daily_reach_28d = serializers.ListField(child=serializers.IntegerField())
    followers = serializers.IntegerField()
    follower_growth_28d = serializers.ListField(child=serializers.IntegerField())


class ReactionBreakdownSerializer(serializers.Serializer):
    reaction = serializers.CharField()
    count = serializers.IntegerField()


class ShareBreakdownSerializer(serializers.Serializer):
    platform = serializers.CharField()
    count = serializers.IntegerField()


class SourceMixSerializer(serializers.Serializer):
    source = serializers.CharField()
    count = serializers.IntegerField()


class TopJokeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    text = serializers.CharField()
    views = serializers.IntegerField()
    reactions = serializers.IntegerField()
    saves = serializers.IntegerField()
    shares = serializers.IntegerField()
    payoff_rate = serializers.FloatField(allow_null=True)


class AudienceLabelCountSerializer(serializers.Serializer):
    label = serializers.CharField()
    count = serializers.IntegerField()


class AudienceSerializer(serializers.Serializer):
    top_themes = AudienceLabelCountSerializer(many=True)
    top_categories = AudienceLabelCountSerializer(many=True)
    top_formats = AudienceLabelCountSerializer(many=True)


class SuggestionSerializer(serializers.Serializer):
    kind = serializers.CharField()
    title = serializers.CharField()
    detail = serializers.CharField()
    data = serializers.DictField()


class CreatorInsightsSerializer(serializers.Serializer):
    """Documents the shape of GET /api/v1/creators/me/insights/ for drf-spectacular."""
    period = serializers.CharField()
    is_creator = serializers.BooleanField()
    overview = OverviewSerializer()
    reactions_breakdown = ReactionBreakdownSerializer(many=True)
    shares_breakdown = ShareBreakdownSerializer(many=True)
    source_mix = SourceMixSerializer(many=True)
    top_jokes = TopJokeSerializer(many=True)
    audience = AudienceSerializer()
    suggestions = SuggestionSerializer(many=True)


class CreatorProfileJokesPaginationSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)


class CreatorProfileSerializer(serializers.Serializer):
    """Documents the shape of GET /api/v1/creators/<id>/profile/ for drf-spectacular."""
    id = serializers.IntegerField()
    display_name = serializers.CharField()
    handle = serializers.CharField()
    published_jokes = serializers.IntegerField()
    follower_count = serializers.IntegerField()
    is_following = serializers.BooleanField(allow_null=True)
    # Tier-filtered (for the viewer) page of the creator's published jokes.
    jokes = serializers.ListField(child=serializers.DictField())
    jokes_pagination = CreatorProfileJokesPaginationSerializer()
