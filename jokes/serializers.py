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
    UserPreference,
    Collection,
    SavedJoke,
    DailyJoke,
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


# =============================================================================
# UserPreference Serializers
# =============================================================================

class UserPreferenceSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for user preferences with nested related models.

    Use for GET requests to display full preference details.
    """

    # Nested serializers for related models (read_only)
    preferred_tones = ToneSerializer(many=True, read_only=True)
    preferred_contexts = ContextTagSerializer(many=True, read_only=True)
    preferred_age_rating = AgeRatingSerializer(read_only=True)
    preferred_language = LanguageSerializer(read_only=True)

    class Meta:
        model = UserPreference
        fields = [
            'id',
            'preferred_tones',
            'preferred_contexts',
            'preferred_age_rating',
            'preferred_language',
            'notification_enabled',
            'notification_time',
            'onboarding_completed',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class UserPreferenceUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer for updating user preferences.

    Use for PATCH requests to update preference settings.
    Accepts primary keys for FK/M2M fields.
    """

    # PrimaryKeyRelatedField for FK/M2M (accept IDs for write)
    preferred_tones = serializers.PrimaryKeyRelatedField(
        queryset=Tone.objects.all(),
        many=True,
        required=False,
    )
    preferred_contexts = serializers.PrimaryKeyRelatedField(
        queryset=ContextTag.objects.all(),
        many=True,
        required=False,
    )
    preferred_age_rating = serializers.PrimaryKeyRelatedField(
        queryset=AgeRating.objects.all(),
        required=False,
        allow_null=True,
    )
    preferred_language = serializers.PrimaryKeyRelatedField(
        queryset=Language.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = UserPreference
        fields = [
            'preferred_tones',
            'preferred_contexts',
            'preferred_age_rating',
            'preferred_language',
            'notification_enabled',
            'notification_time',
            'onboarding_completed',
        ]

    def validate(self, data):
        """Validate notification_time is required when notification_enabled is True."""
        notification_enabled = data.get(
            'notification_enabled',
            getattr(self.instance, 'notification_enabled', False) if self.instance else False
        )
        notification_time = data.get(
            'notification_time',
            getattr(self.instance, 'notification_time', None) if self.instance else None
        )

        if notification_enabled and not notification_time:
            raise serializers.ValidationError({
                'notification_time': 'Notification time is required when notifications are enabled.'
            })

        return data


# =============================================================================
# Collection and SavedJoke Serializers
# =============================================================================

class CollectionSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for collections with joke count.

    Use for GET requests to display collection details.
    """

    joke_count = serializers.SerializerMethodField()

    class Meta:
        model = Collection
        fields = [
            'id',
            'name',
            'description',
            'is_default',
            'joke_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'is_default', 'created_at', 'updated_at']

    def get_joke_count(self, obj):
        """Return the number of jokes in this collection."""
        return obj.saved_jokes.count()


class CollectionCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for creating/updating collections.

    Use for POST/PATCH requests.
    Validates name uniqueness per user.
    """

    class Meta:
        model = Collection
        fields = ['name', 'description']

    def validate_name(self, value):
        """Validate name is unique for the current user."""
        user = self.context['request'].user
        queryset = Collection.objects.filter(user=user, name=value)

        # Exclude current instance on update
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                'You already have a collection with this name.'
            )

        return value


class SavedJokeSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for saved jokes with nested joke and collection.

    Use for GET requests to display saved joke details.
    """

    joke = JokeListSerializer(read_only=True)
    collection = CollectionSerializer(read_only=True)

    class Meta:
        model = SavedJoke
        fields = [
            'id',
            'joke',
            'collection',
            'note',
            'created_at',
        ]
        read_only_fields = fields


class SavedJokeCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for saving jokes to collections.

    Use for POST requests.
    Validates collection belongs to user and joke not already saved in collection.
    """

    joke = serializers.PrimaryKeyRelatedField(queryset=Joke.objects.all())
    collection = serializers.PrimaryKeyRelatedField(
        queryset=Collection.objects.all(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = SavedJoke
        fields = ['joke', 'collection', 'note']

    def validate_collection(self, value):
        """Validate collection belongs to the current user."""
        if value is not None:
            user = self.context['request'].user
            if value.user != user:
                raise serializers.ValidationError(
                    'Collection does not belong to you.'
                )
        return value

    def validate(self, data):
        """Validate joke is not already saved in the same collection."""
        user = self.context['request'].user
        joke = data.get('joke')
        collection = data.get('collection')

        if SavedJoke.objects.filter(
            user=user,
            joke=joke,
            collection=collection
        ).exists():
            if collection:
                raise serializers.ValidationError({
                    'joke': 'This joke is already saved in this collection.'
                })
            else:
                raise serializers.ValidationError({
                    'joke': 'This joke is already saved without a collection.'
                })

        return data


# =============================================================================
# DailyJoke Serializers
# =============================================================================

class DailyJokeSerializer(serializers.ModelSerializer):
    """
    Serializer for daily jokes with nested joke details.

    Use for displaying today's personalized joke and joke history.
    """

    joke = JokeSerializer(read_only=True)

    class Meta:
        model = DailyJoke
        fields = ['id', 'joke', 'date', 'delivered_at', 'created_at']
        read_only_fields = ['id', 'joke', 'date', 'delivered_at', 'created_at']
