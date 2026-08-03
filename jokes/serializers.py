"""
Serializers for the Jokes API.

Provides serializers for all 8 models:
- Lookup serializers: Format, AgeRating, Tone, ContextTag, Language, CultureTag, Source
- JokeSerializer: Nested detail view with all related models
- JokeListSerializer: Compact list view with slugs only
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from jokes.submission_rules import FORMAT_RULES, validate_per_format

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
    Appeal,
    Vibe,
    UserVibe,
    MysteryBoxRoll,
    JokeView,
    Streak,
    StreakDay,
    JokePack,
    JokePackEntry,
    JokePackProgress,
    MediaAsset,
    JokeSubmissionMedia,
)

# 14-day appeal window (spec value, verbatim). Shared by the create
# serializer's window checks for both takedown and rejection appeals.
APPEAL_WINDOW = timedelta(days=14)


# =============================================================================
# Lookup Model Serializers
# =============================================================================

class FormatSerializer(serializers.ModelSerializer):
    """Serializer for joke format with creator-editor schema disclosure."""

    required_fields = serializers.SerializerMethodField()
    forbidden_fields = serializers.SerializerMethodField()
    constraints = serializers.SerializerMethodField()

    class Meta:
        model = Format
        fields = [
            'id', 'name', 'slug', 'description',
            'required_fields', 'forbidden_fields', 'constraints',
        ]

    def _rule(self, obj):
        return FORMAT_RULES.get(obj.slug, {})

    def get_required_fields(self, obj) -> list[str]:
        return list(self._rule(obj).get('required', []))

    def get_forbidden_fields(self, obj) -> list[str]:
        return list(self._rule(obj).get('forbidden', []))

    def get_constraints(self, obj) -> dict:
        return dict(self._rule(obj).get('constraints', {}))


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


class MediaAssetSerializer(serializers.ModelSerializer):
    """Read shape for an uploaded media asset (upload response + attachments)."""

    url = serializers.SerializerMethodField()
    poster_url = serializers.SerializerMethodField()

    class Meta:
        model = MediaAsset
        fields = [
            'id', 'kind', 'url', 'poster_url',
            'width', 'height', 'duration_ms', 'is_gif', 'created_at',
        ]

    def _absolute(self, field_file):
        if not field_file:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(field_file.url) if request else field_file.url

    def get_url(self, obj) -> str | None:
        return self._absolute(obj.file)

    def get_poster_url(self, obj) -> str | None:
        return self._absolute(obj.poster)


# =============================================================================
# Joke Serializers
# =============================================================================

# Formats where the joke IS the ``text`` field (no separate setup teaser): the
# whole card blurs when locked by the paywall. Derived from the canonical
# per-format schema so it stays in sync (oneliner / story / observ).
TEXT_ONLY_FORMATS = frozenset(
    slug for slug, rule in FORMAT_RULES.items()
    if rule.get('required') == ['text']
)


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

    # Freemium paywall: True when this joke's payoff is withheld for this
    # request (free user over the daily read cap, joke not yet opened today).
    is_locked = serializers.SerializerMethodField()

    # Media attachments (Wave 1). Locked jokes get dimensions only.
    media = serializers.SerializerMethodField()

    class Meta:
        model = Joke
        fields = [
            'id',
            'text',
            'setup',
            'punchline',
            'lines',        # P10: knock-knock dialogue (null for other formats)
            'media',
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
            'is_locked',
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

    def _is_locked(self, obj) -> bool:
        """Resolve lock state from the once-per-request paywall_state context.

        Locked iff a free user is over their daily read cap AND this joke was
        not already opened today. The daily editorial joke is exempt simply by
        never having paywall_state injected into its serving path.
        """
        state = self.context.get('paywall_state')
        if state is None or not state.over:
            return False
        return obj.id not in state.consumed_ids

    def get_is_locked(self, obj) -> bool:
        return self._is_locked(obj)

    def get_media(self, obj) -> list[dict]:
        """Media attachments in position order. LOCKED jokes get dimensions
        only — URLs are withheld SERVER-SIDE (spec §6.2): a client-side blur
        over a real URL would still download the payoff.

        Removed jokes get [] unconditionally (defense-in-depth): after the
        quarantine rework their JokeMedia links survive takedown, so any
        serving path that misses an is_removed filter would otherwise emit
        quarantine-path URLs."""
        if obj.is_removed:
            return []
        links = list(obj.media.all())
        if not links:
            return []
        if self._is_locked(obj):
            return [
                {'kind': l.asset.kind, 'width': l.asset.width, 'height': l.asset.height}
                for l in links
            ]
        serializer = MediaAssetSerializer(context=self.context)
        return [
            {
                'kind': l.asset.kind,
                'url': serializer._absolute(l.asset.file),
                'poster_url': serializer._absolute(l.asset.poster),
                'width': l.asset.width,
                'height': l.asset.height,
                'duration_ms': l.asset.duration_ms,
                'is_gif': l.asset.is_gif,
            }
            for l in links
        ]

    def to_representation(self, obj):
        """Strip the payoff SERVER-SIDE when locked — the ONLY place fields are
        withheld, so every serving path inherits it via context.

        Always null ``punchline`` + ``lines``; also null ``text`` for text-only
        formats (the whole card blurs — no teaser). ``setup`` (the teaser for
        two-part jokes) is always kept.
        """
        data = super().to_representation(obj)
        if self._is_locked(obj):
            data['punchline'] = None
            data['lines'] = None
            fmt = getattr(obj.format, 'slug', None) if obj.format_id else None
            if fmt in TEXT_ONLY_FORMATS:
                data['text'] = None
        return data


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

    # Media attachments (Wave 1). Dims-only ALWAYS — see get_media().
    media = serializers.SerializerMethodField()

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
            'media',
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

    def get_media(self, obj) -> list[dict]:
        """Dims-only ALWAYS: this serializer has no paywall context (it serves
        the public creator profile) — emitting URLs here would bypass the
        paywall entirely. Removed jokes get [] (same defense-in-depth as
        JokeSerializer.get_media)."""
        if obj.is_removed:
            return []
        return [
            {'kind': l.asset.kind, 'width': l.asset.width, 'height': l.asset.height}
            for l in obj.media.all()
        ]


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
    culture_tags = serializers.SerializerMethodField()
    # New design vocabulary aliases (P1 of Pivot Plan)
    categories = serializers.SerializerMethodField()
    themes = serializers.SerializerMethodField()
    last_edited_at = serializers.DateTimeField(source='updated_at', read_only=True)
    likes = serializers.SerializerMethodField()
    media = serializers.SerializerMethodField()

    class Meta:
        model = JokeSubmission
        fields = [
            'id', 'text', 'setup', 'punchline', 'lines',
            'format', 'status',
            'tones', 'age_rating', 'context_tags', 'culture_tags',
            'categories',  # alias of tones
            'themes',      # alias of context_tags
            'last_edited_at',
            'created_at', 'likes', 'rejection_reason', 'media',
        ]

    def get_tones(self, obj) -> list[str]:
        return [t.name for t in obj.tones.all()]

    def get_context_tags(self, obj) -> list[str]:
        return [t.slug for t in obj.context_tags.all()]

    def get_culture_tags(self, obj) -> list[str]:
        return [t.slug for t in obj.culture_tags.all()]

    def get_categories(self, obj) -> list[str]:
        return self.get_tones(obj)

    def get_themes(self, obj) -> list[str]:
        return self.get_context_tags(obj)

    def get_likes(self, obj):
        if obj.published_joke:
            return obj.published_joke.ratings.filter(rating=1).count()
        return None

    def get_media(self, obj) -> list[dict]:
        return [
            MediaAssetSerializer(link.asset, context=self.context).data
            for link in obj.media.all()
        ]


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
    media_asset_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, write_only=True,
    )

    class Meta:
        model = JokeSubmission
        fields = [
            'format', 'setup', 'punchline', 'text', 'lines',
            'tones', 'categories', 'themes',
            'age_rating', 'context_tags', 'culture_tags',
            'source', 'language', 'media_asset_ids',
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

        # Resolve media attachments for per-format validation. When the key is
        # absent on a PATCH, the instance's existing attachments stand.
        self._media_provided = 'media_asset_ids' in data
        if self._media_provided:
            media_ids = data.get('media_asset_ids') or []
            if len(set(media_ids)) != len(media_ids):
                raise serializers.ValidationError(
                    {'media_asset_ids': 'Duplicate media attachments.'}
                )
            request = self.context.get('request')
            owner = getattr(request, 'user', None)
            assets = {
                a.id: a for a in MediaAsset.objects.filter(
                    id__in=media_ids, owner=owner,
                )
            }
            missing = [str(i) for i in media_ids if i not in assets]
            if missing:
                raise serializers.ValidationError(
                    {'media_asset_ids': 'One or more media assets were not found.'}
                )
            self._media_assets = [assets[i] for i in media_ids]
            attrs['media'] = [
                {'kind': a.kind, 'duration_ms': a.duration_ms}
                for a in self._media_assets
            ]
        elif self.instance is not None:
            attrs['media'] = [
                {'kind': m.asset.kind, 'duration_ms': m.asset.duration_ms}
                for m in self.instance.media.all()
            ]
        else:
            attrs['media'] = []

        # Draft autosave (JokeDraftDetailView PATCH) sets this flag so an
        # in-progress draft with unfilled required fields persists instead of
        # 400ing and losing the creator's typed text. Per-format validation is
        # enforced later, at submit (JokeDraftSubmitView), and on normal CREATE.
        if not self.context.get('skip_format_validation'):
            errors = validate_per_format(fmt.slug, attrs)
            if errors:
                raise serializers.ValidationError(errors)

        # Backfill `text` for formats that don't have it as a creator input
        # (setup-punchline, anti-joke, knock-knock). Keeps the submission's
        # text field populated for previews, admin __str__, search indexing,
        # and the Joke.text field after publish — without forcing creators
        # to type it twice.
        if not attrs['text']:
            if attrs['setup'] and attrs['punchline']:
                data['text'] = f"{attrs['setup']} {attrs['punchline']}"
            elif attrs['lines']:
                data['text'] = ' '.join(attrs['lines'])
            elif attrs['setup'] and 'media' in FORMAT_RULES.get(fmt.slug, {}).get('required', []):
                # Media formats: the setup teaser IS the searchable/share text.
                # Scoped to media formats only — for setup/anti formats an
                # autosave PATCH of just {setup} must NOT set text, or the
                # later {punchline} PATCH would see non-blank text and skip
                # the full "setup punchline" backfill forever.
                data['text'] = attrs['setup']

        return data

    def create(self, validated_data):
        validated_data.pop('media_asset_ids', None)
        instance = super().create(validated_data)
        self._sync_media(instance)
        return instance

    def update(self, instance, validated_data):
        validated_data.pop('media_asset_ids', None)
        instance = super().update(instance, validated_data)
        self._sync_media(instance)
        return instance

    def _sync_media(self, submission):
        if not getattr(self, '_media_provided', False):
            return
        with transaction.atomic():
            submission.media.all().delete()
            for position, asset in enumerate(getattr(self, '_media_assets', [])):
                JokeSubmissionMedia.objects.create(
                    submission=submission, asset=asset, position=position,
                )


# =============================================================================
# Content Report Serializer (Compliance)
# =============================================================================

class ContentReportSerializer(serializers.ModelSerializer):
    """Write serializer for content reports."""

    class Meta:
        model = ContentReport
        fields = ['joke', 'reason', 'description']


# =============================================================================
# Appeals (Appeals & Notices wave) — spec §API
# =============================================================================

class AppealSerializer(serializers.ModelSerializer):
    """Read serializer for an appeal (GET /users/me/appeals/ and the create
    response). Exposes a lightweight target descriptor rather than nesting
    the full Joke/JokeSubmission (the caller already knows which one they
    filed against)."""

    target_type = serializers.SerializerMethodField()
    target_id = serializers.SerializerMethodField()
    target_preview = serializers.SerializerMethodField()

    class Meta:
        model = Appeal
        fields = [
            'id', 'action_type', 'status', 'reason_text',
            'target_type', 'target_id', 'target_preview',
            'created_at', 'resolved_at', 'resolution_note',
        ]
        read_only_fields = fields

    def get_target_type(self, obj) -> str:
        return 'joke' if obj.joke_id else 'submission'

    def get_target_id(self, obj) -> int:
        return obj.joke_id or obj.submission_id

    def get_target_preview(self, obj) -> str:
        if obj.joke_id:
            text = obj.joke.text if obj.joke else ''
        else:
            text = obj.submission.text if obj.submission else ''
        text = text or ''
        return text[:60]


class AppealCreateSerializer(serializers.ModelSerializer):
    """Write serializer for POST /appeals/. Accepts
    `{joke_id | submission_id, reason_text}`.

    Validates, in order: exactly one target given; the target exists AND
    belongs to the caller (both failures return 404 — indistinguishable, so
    a probe can't learn whether a joke/submission id exists or is someone
    else's); the target is in the appealable state (joke removed /
    submission rejected); the 14-day appeal window hasn't lapsed; no
    existing OPEN (pending) appeal for this target. The last three are 400s
    with a clear message — the caller already knows it's their own target,
    so there's no existence leak to guard against there.
    """

    joke_id = serializers.IntegerField(required=False, write_only=True)
    submission_id = serializers.IntegerField(required=False, write_only=True)

    class Meta:
        model = Appeal
        fields = ['joke_id', 'submission_id', 'reason_text']

    def validate(self, data):
        joke_id = data.get('joke_id')
        submission_id = data.get('submission_id')
        if bool(joke_id) == bool(submission_id):
            raise serializers.ValidationError(
                'Provide exactly one of joke_id or submission_id.'
            )

        user = self.context['request'].user
        now = timezone.now()

        if joke_id is not None:
            # all_objects: the target is a REMOVED joke, hidden from the
            # default (JokeManager) queryset.
            try:
                joke = Joke.all_objects.get(pk=joke_id)
            except Joke.DoesNotExist:
                raise NotFound('Joke not found.')
            if joke.creator_id != user.id:
                raise NotFound('Joke not found.')
            if not joke.is_removed:
                raise serializers.ValidationError(
                    'This joke has not been removed — nothing to appeal.'
                )
            if now > joke.removed_at + APPEAL_WINDOW:
                raise serializers.ValidationError(
                    'The 14-day appeal window for this takedown has passed.'
                )
            if Appeal.objects.filter(user=user, joke=joke, status='pending').exists():
                raise serializers.ValidationError(
                    'An appeal is already pending for this joke.'
                )
            self._target = {'joke': joke, 'submission': None, 'action_type': 'takedown'}
        else:
            try:
                submission = JokeSubmission.objects.get(pk=submission_id)
            except JokeSubmission.DoesNotExist:
                raise NotFound('Submission not found.')
            if submission.user_id != user.id:
                raise NotFound('Submission not found.')
            if submission.status != 'rejected':
                raise serializers.ValidationError(
                    'This submission has not been rejected — nothing to appeal.'
                )
            if now > submission.updated_at + APPEAL_WINDOW:
                raise serializers.ValidationError(
                    'The 14-day appeal window for this rejection has passed.'
                )
            if Appeal.objects.filter(
                user=user, submission=submission, status='pending'
            ).exists():
                raise serializers.ValidationError(
                    'An appeal is already pending for this submission.'
                )
            self._target = {
                'joke': None, 'submission': submission, 'action_type': 'rejection',
            }
        return data

    def create(self, validated_data):
        target = self._target
        return Appeal.objects.create(
            user=self.context['request'].user,
            joke=target['joke'],
            submission=target['submission'],
            action_type=target['action_type'],
            reason_text=validated_data['reason_text'],
        )


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
        from jokes.serving import allowed_tiers
        request = self.context.get('request')
        tiers = allowed_tiers(request) if request is not None else frozenset({'tier_1'})
        # joke__is_removed: taken-down jokes vanish from pack detail — the FK
        # traversal bypasses JokeManager's is_removed gate (same explicit
        # filter as the tier gate on this exact queryset).
        entries = obj.entries.select_related(
            'joke', 'joke__format', 'joke__age_rating', 'joke__language'
        ).prefetch_related('joke__tones', 'joke__context_tags').filter(
            joke__content_tier__in=tiers, joke__is_removed=False,
        ).order_by('order')
        return [
            {
                'order': e.order,
                'joke': JokeSerializer(e.joke, context=self.context).data,
            }
            for e in entries
        ]


class JokePackProgressUpdateSerializer(serializers.Serializer):
    entry_order = serializers.IntegerField(min_value=0)
