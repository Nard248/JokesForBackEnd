"""
Serializers for the Jokes API.

Provides serializers for all 8 models:
- Lookup serializers: Format, AgeRating, Tone, ContextTag, Language, CultureTag, Source
- JokeSerializer: Nested detail view with all related models
- JokeListSerializer: Compact list view with slugs only
"""
from rest_framework import serializers

from jokes.submission_rules import validate_per_format

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
    JokeRating,
    ShareEvent,
    Favorite,
    JokeSubmission,
    ContentReport,
    Vibe,
    UserVibe,
    MysteryBoxRoll,
    JokeView,
    Streak,
    StreakDay,
    JokePack,
    JokePackEntry,
    JokePackProgress,
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

    # New design vocabulary aliases (P1 of Pivot Plan).
    # `themes` mirrors `context_tags`; `categories` mirrors `tones`. Both old and
    # new names ship in the response so the frontend can migrate at its own pace.
    themes = ContextTagSerializer(source='context_tags', many=True, read_only=True)
    categories = ToneSerializer(source='tones', many=True, read_only=True)

    # Share card URL
    share_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Joke
        fields = [
            'id',
            'text',
            'setup',
            'punchline',
            'lines',        # P10: knock-knock dialogue (null for other formats)
            'format',
            'age_rating',
            'language',
            'source',
            'tones',
            'context_tags',
            'themes',       # alias of context_tags
            'categories',   # alias of tones
            'culture_tags',
            'share_image_url',
            'created_at',
            'updated_at',
        ]
        # Explicitly exclude search_vector

    def get_share_image_url(self, obj):
        """Return absolute URL for share image if it exists."""
        if obj.share_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.share_image.url)
            return obj.share_image.url
        return None


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
    # New design vocabulary alias (P1 of Pivot Plan)
    categories = serializers.SlugRelatedField(
        source='tones',
        slug_field='slug',
        many=True,
        read_only=True,
    )

    # Share card URL
    share_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Joke
        fields = [
            'id',
            'text',
            'format',
            'age_rating',
            'tones',
            'categories',   # alias of tones
            'share_image_url',
        ]

    def get_text(self, obj):
        """Return text truncated to 100 characters."""
        if len(obj.text) > 100:
            return obj.text[:100] + '...'
        return obj.text

    def get_share_image_url(self, obj):
        """Return absolute URL for share image if it exists."""
        if obj.share_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.share_image.url)
            return obj.share_image.url
        return None


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

    # New design vocabulary aliases (P1 of Pivot Plan)
    preferred_categories = ToneSerializer(source='preferred_tones', many=True, read_only=True)
    preferred_themes = ContextTagSerializer(source='preferred_contexts', many=True, read_only=True)

    class Meta:
        model = UserPreference
        fields = [
            'id',
            'preferred_tones',
            'preferred_contexts',
            'preferred_categories',  # alias of preferred_tones
            'preferred_themes',      # alias of preferred_contexts
            'preferred_age_rating',
            'preferred_language',
            'notification_enabled',
            'notification_time',
            'notification_days',     # P8: day-of-week mask
            'streak_saver_enabled',  # P8: in-app nudge gate
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
    # New design vocabulary aliases — accepted on write, mapped to canonical
    # field names in to_internal_value() below.
    preferred_categories = serializers.PrimaryKeyRelatedField(
        queryset=Tone.objects.all(),
        many=True,
        required=False,
    )
    preferred_themes = serializers.PrimaryKeyRelatedField(
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
            'preferred_categories',
            'preferred_themes',
            'preferred_age_rating',
            'preferred_language',
            'notification_enabled',
            'notification_time',
            'notification_days',     # P8
            'streak_saver_enabled',  # P8
            'onboarding_completed',
        ]

    def validate_notification_days(self, value):
        valid = {'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'}
        unknown = [d for d in value if d not in valid]
        if unknown:
            raise serializers.ValidationError(f'Unknown weekday(s): {unknown}')
        return list(dict.fromkeys(value))  # dedupe

    def to_internal_value(self, data):
        """Map new vocabulary aliases to canonical field names.

        If both old and new names are present in the input, the new name wins
        (frontend has explicitly migrated). Old name still works for clients
        that haven't migrated yet.
        """
        validated = super().to_internal_value(data)
        if 'preferred_categories' in validated:
            validated['preferred_tones'] = validated.pop('preferred_categories')
        if 'preferred_themes' in validated:
            validated['preferred_contexts'] = validated.pop('preferred_themes')
        return validated

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

    joke = JokeSerializer(read_only=True)
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


# =============================================================================
# JokeRating Serializers
# =============================================================================

class JokeRatingSerializer(serializers.ModelSerializer):
    """
    Serializer for joke ratings.

    Use for displaying user's rating for a joke.
    """

    class Meta:
        model = JokeRating
        fields = ['id', 'rating', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


# =============================================================================
# ShareEvent Serializers
# =============================================================================

class ShareEventSerializer(serializers.ModelSerializer):
    """
    Serializer for share events.

    Use for recording and displaying share events.
    """

    class Meta:
        model = ShareEvent
        fields = ['id', 'joke', 'platform', 'created_at']
        read_only_fields = ['id', 'created_at']


# =============================================================================
# Favorite Serializers
# =============================================================================

class FavoriteSerializer(serializers.ModelSerializer):
    """Read serializer for favorites with nested joke."""

    joke = JokeSerializer(read_only=True)
    favorited_at = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = Favorite
        fields = ['id', 'joke', 'favorited_at']
        read_only_fields = fields


class FavoriteCreateSerializer(serializers.ModelSerializer):
    """Write serializer for creating a favorite."""

    class Meta:
        model = Favorite
        fields = ['joke']

    def validate_joke(self, value):
        user = self.context['request'].user
        if Favorite.objects.filter(user=user, joke=value).exists():
            raise serializers.ValidationError('Joke already favorited.')
        return value


# =============================================================================
# Joke Submission Serializers
# =============================================================================

class JokeSubmissionListSerializer(serializers.ModelSerializer):
    """Read serializer for listing user's drafts/submissions."""

    format = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    age_rating = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    tones = serializers.SerializerMethodField()
    context_tags = serializers.SerializerMethodField()
    # New design vocabulary aliases (P1 of Pivot Plan)
    categories = serializers.SerializerMethodField()
    themes = serializers.SerializerMethodField()
    last_edited_at = serializers.DateTimeField(source='updated_at', read_only=True)
    likes = serializers.SerializerMethodField()

    class Meta:
        model = JokeSubmission
        fields = [
            'id', 'text', 'setup', 'punchline', 'format', 'status',
            'tones', 'age_rating', 'context_tags',
            'categories',  # alias of tones
            'themes',      # alias of context_tags
            'last_edited_at',
            'created_at', 'likes', 'rejection_reason',
        ]

    def get_tones(self, obj) -> list[str]:
        return [t.name for t in obj.tones.all()]

    def get_context_tags(self, obj) -> list[str]:
        return [t.slug for t in obj.context_tags.all()]

    def get_categories(self, obj) -> list[str]:
        return self.get_tones(obj)

    def get_themes(self, obj) -> list[str]:
        return self.get_context_tags(obj)

    def get_likes(self, obj):
        if obj.published_joke:
            return obj.published_joke.ratings.filter(rating=1).count()
        return None


class JokeSubmissionCreateSerializer(serializers.ModelSerializer):
    """Write serializer for creating/updating joke submissions."""

    tones = serializers.SlugRelatedField(
        slug_field='slug', queryset=Tone.objects.all(), many=True, required=False,
    )
    context_tags = serializers.SlugRelatedField(
        slug_field='slug', queryset=ContextTag.objects.all(), many=True, required=False,
    )
    # New design vocabulary aliases (P1 of Pivot Plan) — accepted on write,
    # collapsed into tones/context_tags by to_internal_value().
    categories = serializers.SlugRelatedField(
        slug_field='slug', queryset=Tone.objects.all(), many=True, required=False,
    )
    themes = serializers.SlugRelatedField(
        slug_field='slug', queryset=ContextTag.objects.all(), many=True, required=False,
    )
    format = serializers.SlugRelatedField(
        slug_field='slug', queryset=Format.objects.all(),
    )
    age_rating = serializers.SlugRelatedField(
        slug_field='slug', queryset=AgeRating.objects.all(),
    )
    language = serializers.SlugRelatedField(
        slug_field='code', queryset=Language.objects.all(), required=False,
    )
    culture_tags = serializers.SlugRelatedField(
        slug_field='slug', queryset=CultureTag.objects.all(), many=True, required=False,
    )
    lines = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = JokeSubmission
        fields = [
            'format', 'setup', 'punchline', 'text', 'lines',
            'tones', 'categories', 'themes',
            'age_rating', 'context_tags', 'culture_tags',
            'source', 'language',
        ]

    def to_internal_value(self, data):
        """Map new vocabulary aliases to canonical field names. New name wins."""
        validated = super().to_internal_value(data)
        if 'categories' in validated:
            validated['tones'] = validated.pop('categories')
        if 'themes' in validated:
            validated['context_tags'] = validated.pop('themes')
        return validated

    def validate(self, data):
        # Resolve format from the payload or the instance being patched.
        fmt = data.get('format') or (self.instance.format if self.instance else None)
        if fmt is None:
            raise serializers.ValidationError({'format': 'This field is required.'})

        # Build the attrs view the rule helper expects (slug-agnostic).
        attrs = {
            'text': data.get('text', '') if 'text' in data
                    else (self.instance.text if self.instance else ''),
            'setup': data.get('setup', '') if 'setup' in data
                     else (self.instance.setup if self.instance else ''),
            'punchline': data.get('punchline', '') if 'punchline' in data
                         else (self.instance.punchline if self.instance else ''),
            'lines': data.get('lines') if 'lines' in data
                     else (self.instance.lines if self.instance else None),
        }

        errors = validate_per_format(fmt.slug, attrs)
        if errors:
            raise serializers.ValidationError(errors)
        return data


# =============================================================================
# Content Report Serializer (Compliance)
# =============================================================================

class ContentReportSerializer(serializers.ModelSerializer):
    """Write serializer for content reports."""

    class Meta:
        model = ContentReport
        fields = ['joke', 'reason', 'description']


# =============================================================================
# Vibes (P2 of Pivot Plan)
# =============================================================================

class VibeSerializer(serializers.ModelSerializer):
    """Catalog entry for the onboarding picker — display metadata only."""

    class Meta:
        model = Vibe
        fields = [
            'slug', 'label', 'subtitle', 'icon',
            'swatch_bg', 'swatch_fg', 'order',
        ]
        read_only_fields = fields


class UserVibeSerializer(serializers.ModelSerializer):
    """A user's selected vibe — embeds the vibe display data inline so the
    frontend gets the picker tile state in one round-trip."""

    vibe = VibeSerializer(read_only=True)

    class Meta:
        model = UserVibe
        fields = ['vibe', 'weight', 'created_at']
        read_only_fields = fields


class UserVibesUpdateSerializer(serializers.Serializer):
    """Replace the user's selected vibes with the given list of slugs.

    Per the design's onboarding screen ("Pick at least 3"), enforces a 3-12
    range. Unknown slugs return 400 with a clear error so frontend can guide
    the user.
    """

    slugs = serializers.ListField(
        child=serializers.SlugField(),
        min_length=3,
        max_length=12,
        help_text="List of vibe slugs (3-12). Replaces the user's current selection.",
    )

    def validate_slugs(self, slugs):
        slugs = list(dict.fromkeys(slugs))  # dedupe, preserve order
        existing = set(
            Vibe.objects.filter(slug__in=slugs, is_active=True)
            .values_list('slug', flat=True)
        )
        unknown = [s for s in slugs if s not in existing]
        if unknown:
            raise serializers.ValidationError(
                f"Unknown or inactive vibes: {unknown}"
            )
        return slugs


# =============================================================================
# Mystery Box (P3 of Pivot Plan)
# =============================================================================

class MysteryBoxStatusSerializer(serializers.Serializer):
    """Quota state for the Mystery Box surface — purely computed."""
    rolls_used_today = serializers.IntegerField()
    rolls_remaining_today = serializers.IntegerField()
    max_per_day = serializers.IntegerField()


class MysteryBoxRollResponseSerializer(serializers.Serializer):
    """Successful roll response — joke + remaining quota + which vibe sourced it."""
    joke = JokeSerializer()
    rolls_remaining_today = serializers.IntegerField()
    source_vibe = VibeSerializer(allow_null=True)


# =============================================================================
# JokeView (P5) — recently viewed list
# =============================================================================

class JokeViewSerializer(serializers.ModelSerializer):
    """One row of recently-viewed history with the joke embedded."""
    joke = JokeSerializer(read_only=True)

    class Meta:
        model = JokeView
        fields = ['joke', 'source', 'revealed_punchline', 'viewed_at']
        read_only_fields = fields


# =============================================================================
# Streak (P6 of Pivot Plan)
# =============================================================================

class StreakDaySerializer(serializers.ModelSerializer):
    class Meta:
        model = StreakDay
        fields = ['date', 'status']


class StreakSerializer(serializers.ModelSerializer):
    """Streak state + last 14 days + risk flag for streak-saver UI."""
    last_14_days = serializers.SerializerMethodField()
    streak_at_risk_today = serializers.SerializerMethodField()

    class Meta:
        model = Streak
        fields = [
            'current_count',
            'longest_count',
            'last_active_date',
            'freeze_days_available',
            'freezes_used_total',
            'started_at',
            'last_14_days',
            'streak_at_risk_today',
        ]
        read_only_fields = fields

    def get_last_14_days(self, obj) -> list:
        from django.utils import timezone
        from datetime import timedelta
        today = timezone.now().date()
        start = today - timedelta(days=13)
        days_by_date = {
            d.date: d.status
            for d in StreakDay.objects.filter(
                user=obj.user, date__gte=start, date__lte=today
            )
        }
        out = []
        for offset in range(14):
            d = start + timedelta(days=offset)
            out.append({
                'date': d.isoformat(),
                'status': days_by_date.get(d, 'pending' if d == today else 'missed'),
            })
        return out

    def get_streak_at_risk_today(self, obj) -> bool:
        """True if user hasn't read today AND it's past their (UTC) 8 PM.

        Frontend uses this to render the in-app streak-saver nudge —
        replaces the 8 PM push (we have no scheduled jobs).
        """
        from django.utils import timezone
        now = timezone.now()
        today = now.date()
        if obj.last_active_date == today:
            return False
        # Past 8 PM UTC?
        return now.hour >= 20


# =============================================================================
# Joke Packs (P7 of Pivot Plan)
# =============================================================================

class JokePackListSerializer(serializers.ModelSerializer):
    """Compact pack for catalog listings — no embedded jokes."""
    joke_count = serializers.SerializerMethodField()
    user_progress = serializers.SerializerMethodField()

    class Meta:
        model = JokePack
        fields = [
            'slug', 'title', 'subtitle', 'description',
            'cover_color', 'is_featured', 'joke_count',
            'publish_at', 'expires_at', 'user_progress',
        ]

    def get_joke_count(self, obj) -> int:
        return obj.entries.count()

    def get_user_progress(self, obj) -> dict | None:
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        progress = obj.progress_records.filter(user=request.user).first()
        if not progress:
            return None
        return {
            'last_read_entry': progress.last_read_entry,
            'completed_at': progress.completed_at,
            'is_complete': progress.completed_at is not None,
        }


class JokePackDetailSerializer(JokePackListSerializer):
    """Full pack with embedded ordered jokes."""
    jokes = serializers.SerializerMethodField()

    class Meta(JokePackListSerializer.Meta):
        fields = JokePackListSerializer.Meta.fields + ['jokes']

    def get_jokes(self, obj):
        entries = obj.entries.select_related(
            'joke', 'joke__format', 'joke__age_rating', 'joke__language'
        ).prefetch_related('joke__tones', 'joke__context_tags').order_by('order')
        return [
            {
                'order': e.order,
                'joke': JokeSerializer(e.joke, context=self.context).data,
            }
            for e in entries
        ]


class JokePackProgressUpdateSerializer(serializers.Serializer):
    entry_order = serializers.IntegerField(min_value=0)
