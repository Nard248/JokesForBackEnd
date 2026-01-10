"""
Serializers for the Jokes API.

Provides serializers for all 8 models:
- Lookup serializers: Format, AgeRating, Tone, ContextTag, Language, CultureTag, Source
- JokeSerializer: Nested detail view with all related models
- JokeListSerializer: Compact list view with slugs only
"""
from rest_framework import serializers

from .models import (
    Format,
    AgeRating,
    Tone,
    ContextTag,
    Language,
    CultureTag,
    Source,
    Joke,
)


# =============================================================================
# Lookup Model Serializers
# =============================================================================

class FormatSerializer(serializers.ModelSerializer):
    """Serializer for joke format (one-liner, setup-punchline, etc.)."""

    class Meta:
        model = Format
        fields = ['id', 'name', 'slug', 'description']


class AgeRatingSerializer(serializers.ModelSerializer):
    """Serializer for age rating with minimum age."""

    class Meta:
        model = AgeRating
        fields = ['id', 'name', 'slug', 'description', 'min_age']


class ToneSerializer(serializers.ModelSerializer):
    """Serializer for humor tone (clean, dark, dad-jokes, etc.)."""

    class Meta:
        model = Tone
        fields = ['id', 'name', 'slug', 'description']


class ContextTagSerializer(serializers.ModelSerializer):
    """Serializer for context/situation tags."""

    class Meta:
        model = ContextTag
        fields = ['id', 'name', 'slug', 'description']


class LanguageSerializer(serializers.ModelSerializer):
    """Serializer for language (ISO 639-1 code)."""

    class Meta:
        model = Language
        fields = ['id', 'code', 'name']


class CultureTagSerializer(serializers.ModelSerializer):
    """Serializer for cultural context tags."""

    class Meta:
        model = CultureTag
        fields = ['id', 'name', 'slug', 'description']


class SourceSerializer(serializers.ModelSerializer):
    """Serializer for joke source attribution."""

    class Meta:
        model = Source
        fields = ['id', 'name', 'url', 'description']


# =============================================================================
# Joke Serializers
# =============================================================================

class JokeSerializer(serializers.ModelSerializer):
    """
    Full joke serializer with nested related models.

    Use for detail views where complete information is needed.
    Excludes search_vector (internal only).
    """

    # Nested serializers for related models (read_only)
    format = FormatSerializer(read_only=True)
    age_rating = AgeRatingSerializer(read_only=True)
    language = LanguageSerializer(read_only=True)
    source = SourceSerializer(read_only=True, allow_null=True)
    tones = ToneSerializer(many=True, read_only=True)
    context_tags = ContextTagSerializer(many=True, read_only=True)
    culture_tags = CultureTagSerializer(many=True, read_only=True)

    class Meta:
        model = Joke
        fields = [
            'id',
            'text',
            'setup',
            'punchline',
            'format',
            'age_rating',
            'language',
            'source',
            'tones',
            'context_tags',
            'culture_tags',
            'created_at',
            'updated_at',
        ]
        # Explicitly exclude search_vector


class JokeListSerializer(serializers.ModelSerializer):
    """
    Compact joke serializer for list views.

    Shows truncated text and slugs only for related models.
    Optimized for bandwidth when displaying many jokes.
    """

    # Truncated text via SerializerMethodField
    text = serializers.SerializerMethodField()

    # Slug-only representations for FK relations
    format = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    age_rating = serializers.SlugRelatedField(slug_field='slug', read_only=True)

    # Slug list for M2M relations
    tones = serializers.SlugRelatedField(
        slug_field='slug',
        many=True,
        read_only=True
    )

    class Meta:
        model = Joke
        fields = [
            'id',
            'text',
            'format',
            'age_rating',
            'tones',
        ]

    def get_text(self, obj):
        """Return text truncated to 100 characters."""
        if len(obj.text) > 100:
            return obj.text[:100] + '...'
        return obj.text
