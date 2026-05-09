from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.files.base import ContentFile
from django.db import models
import pgtrigger

from .managers import JokeManager


class Format(models.Model):
    """Joke format: one-liner, setup-punchline, short-story"""
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class AgeRating(models.Model):
    """Age rating: kid-safe, teen, adult, family-friendly"""
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    min_age = models.PositiveSmallIntegerField(null=True, blank=True)

    def __str__(self):
        return self.name


class Tone(models.Model):
    """Humor tone — exposed in the new design vocabulary as 'Category' (how it feels): wholesome, dark, dad-jokes, puns, sarcasm, etc."""
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Category (Tone)'
        verbose_name_plural = 'Categories (Tones)'

    def __str__(self):
        return self.name


class ContextTag(models.Model):
    """Context/situation — exposed in the new design vocabulary as 'Theme' (what it's about): work, family, food, tech, school, dating, etc."""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Theme (ContextTag)'
        verbose_name_plural = 'Themes (ContextTags)'

    def __str__(self):
        return self.name


class Language(models.Model):
    """Language: ISO 639-1 code and name"""
    code = models.CharField(max_length=10, unique=True)  # ISO 639-1
    name = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.name} ({self.code})"


class CultureTag(models.Model):
    """Cultural context: American, British, universal"""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Source(models.Model):
    """Source attribution for jokes"""
    name = models.CharField(max_length=200)
    url = models.URLField(blank=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


@pgtrigger.register(
    pgtrigger.UpdateSearchVector(
        name='joke_search_vector_update',
        vector_field='search_vector',
        document_fields=['text', 'setup', 'punchline'],
    )
)
class Joke(models.Model):
    """Main joke model with rich metadata for search and filtering"""

    # Manager
    objects = JokeManager()

    # Content
    text = models.TextField(help_text="Full joke text for one-liners or complete jokes")
    setup = models.TextField(blank=True, help_text="Setup for two-part jokes")
    punchline = models.TextField(blank=True, help_text="Punchline for two-part jokes")

    # Foreign Keys (single value)
    format = models.ForeignKey(Format, on_delete=models.PROTECT, related_name='jokes')
    age_rating = models.ForeignKey(AgeRating, on_delete=models.PROTECT, related_name='jokes')
    language = models.ForeignKey(Language, on_delete=models.PROTECT, related_name='jokes')
    source = models.ForeignKey(Source, on_delete=models.SET_NULL, null=True, blank=True, related_name='jokes')

    # Many-to-Many (multiple values)
    tones = models.ManyToManyField(Tone, related_name='jokes')
    context_tags = models.ManyToManyField(ContextTag, related_name='jokes')
    culture_tags = models.ManyToManyField(CultureTag, related_name='jokes', blank=True)

    # Content classification (compliance: three-bucket framework)
    CONTENT_TIER_CHOICES = [
        ('tier_1', 'Tier 1 - Universal'),
        ('tier_2', 'Tier 2 - Mature'),
        ('tier_3', 'Tier 3 - Prohibited'),
    ]
    content_tier = models.CharField(
        max_length=10,
        choices=CONTENT_TIER_CHOICES,
        default='tier_1',
        db_index=True,
        help_text='Content classification tier for compliance'
    )

    # Search
    search_vector = SearchVectorField(null=True, blank=True)

    # Share card
    share_image = models.ImageField(
        upload_to='share-cards/',
        blank=True,
        help_text='Auto-generated share card image for social media'
    )

    # Track original text for change detection
    _original_text = None

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            GinIndex(fields=['search_vector'], name='joke_search_vector_idx'),
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_text = self.text if self.pk else None

    def save(self, *args, **kwargs):
        # Check if we need to regenerate share image
        regenerate = False
        if self.pk:
            # Existing joke - check if text changed
            if self._original_text != self.text:
                regenerate = True
        else:
            # New joke - always generate
            regenerate = True

        # Generate share image if needed (after first save to ensure pk exists)
        if not regenerate and not self.share_image:
            regenerate = True

        # Save first to ensure pk exists
        super().save(*args, **kwargs)

        # Generate share image after save
        if regenerate:
            self._generate_share_image()
            # Save again with the image (avoid recursion by using update)
            Joke.objects.filter(pk=self.pk).update(share_image=self.share_image.name)

        self._original_text = self.text

    def _generate_share_image(self):
        """Generate themed share card PNG."""
        from .share_cards import generate_share_card_png

        png_buffer = generate_share_card_png(self)
        filename = f'joke-{self.pk}.png'
        self.share_image.save(filename, ContentFile(png_buffer.read()), save=False)

    def __str__(self):
        return self.text[:50] + ('...' if len(self.text) > 50 else '')


class UserPreference(models.Model):
    """User preferences for personalized joke recommendations and notifications"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='preference'
    )
    preferred_tones = models.ManyToManyField(
        Tone,
        blank=True,
        related_name='preferred_by'
    )
    preferred_contexts = models.ManyToManyField(
        ContextTag,
        blank=True,
        related_name='preferred_by'
    )
    preferred_age_rating = models.ForeignKey(
        AgeRating,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='preferred_by'
    )
    preferred_language = models.ForeignKey(
        Language,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='preferred_by'
    )
    notification_enabled = models.BooleanField(default=False)
    notification_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Time for daily joke notification"
    )
    # Granular notification preferences
    notification_daily_joke = models.BooleanField(default=True)
    notification_trending_alerts = models.BooleanField(default=False)
    notification_collection_updates = models.BooleanField(default=True)
    notification_email_digest = models.BooleanField(default=False)
    onboarding_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Preference'
        verbose_name_plural = 'User Preferences'

    def __str__(self):
        return f"Preferences for {self.user.email}"


class Collection(models.Model):
    """User's personal collection of jokes (folder/playlist)"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='collections'
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    is_public = models.BooleanField(
        default=False,
        help_text='Whether this collection is visible to other users'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', 'name']
        unique_together = [['user', 'name']]

    def __str__(self):
        return f"{self.name} ({self.user.email})"


class SavedJoke(models.Model):
    """A joke saved by a user, optionally in a collection"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_jokes'
    )
    joke = models.ForeignKey(
        Joke,
        on_delete=models.CASCADE,
        related_name='saved_by'
    )
    collection = models.ForeignKey(
        Collection,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='saved_jokes'
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [['user', 'joke', 'collection']]

    def __str__(self):
        return f"{self.user.email} saved joke {self.joke_id}"


class DailyJoke(models.Model):
    """Track daily joke delivered to each user"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='daily_jokes'
    )
    joke = models.ForeignKey(
        'Joke',
        on_delete=models.CASCADE,
        related_name='daily_deliveries'
    )
    date = models.DateField()
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['user', 'date']]
        ordering = ['-date']
        indexes = [
            models.Index(fields=['user', 'date']),
        ]

    def __str__(self):
        return f"Daily joke for {self.user.email} on {self.date}"


class JokeRating(models.Model):
    """User rating for a joke (thumbs up/down)"""
    LIKE = 1
    DISLIKE = -1
    RATING_CHOICES = [(LIKE, 'Like'), (DISLIKE, 'Dislike')]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='joke_ratings'
    )
    joke = models.ForeignKey(
        Joke,
        on_delete=models.CASCADE,
        related_name='ratings'
    )
    rating = models.SmallIntegerField(choices=RATING_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['user', 'joke']]
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['joke']),
        ]

    def __str__(self):
        rating_text = 'Like' if self.rating == self.LIKE else 'Dislike'
        return f"{self.user.email} {rating_text} joke {self.joke_id}"


class ShareEvent(models.Model):
    """Track joke share events for analytics."""
    PLATFORM_CHOICES = [
        ('copy', 'Copy to Clipboard'),
        ('twitter', 'Twitter/X'),
        ('facebook', 'Facebook'),
        ('whatsapp', 'WhatsApp'),
        ('other', 'Other'),
    ]

    joke = models.ForeignKey(
        'Joke',
        on_delete=models.CASCADE,
        related_name='share_events'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='share_events',
        help_text='Null for anonymous shares'
    )
    platform = models.CharField(
        max_length=20,
        choices=PLATFORM_CHOICES,
        default='other'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['joke', 'created_at']),
            models.Index(fields=['platform', 'created_at']),
        ]

    def __str__(self):
        user_str = self.user.email if self.user else 'anonymous'
        return f"{user_str} shared joke {self.joke_id} via {self.platform}"


# =============================================================================
# User Profile (extends User via OneToOneField)
# =============================================================================

class UserProfile(models.Model):
    """Extended profile for User. Auto-created via signal on user creation."""

    THEME_CHOICES = [
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('system', 'System'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    bio = models.TextField(blank=True, max_length=500)
    avatar = models.ImageField(upload_to='avatars/', blank=True)
    is_premium = models.BooleanField(default=False)

    # Privacy settings
    public_profile = models.BooleanField(default=True)
    show_activity = models.BooleanField(default=True)
    share_analytics = models.BooleanField(default=False)

    # Theme
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default='light')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self):
        return f"Profile for {self.user.email}"


# =============================================================================
# Favorites (separate from SavedJoke/Collections)
# =============================================================================

class Favorite(models.Model):
    """User's favorited jokes (heart action, distinct from bookmark/save)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='favorites'
    )
    joke = models.ForeignKey(
        Joke,
        on_delete=models.CASCADE,
        related_name='favorited_by'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['user', 'joke']]
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.email} favorited joke {self.joke_id}"


# =============================================================================
# Joke Submission & Drafts
# =============================================================================

class JokeSubmission(models.Model):
    """User-submitted jokes with draft/moderation workflow."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Review'),
        ('published', 'Published'),
        ('rejected', 'Rejected'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='joke_submissions'
    )

    # Content (mirrors Joke fields)
    text = models.TextField(blank=True)
    setup = models.TextField(blank=True)
    punchline = models.TextField(blank=True)
    format = models.ForeignKey(Format, on_delete=models.PROTECT, related_name='submissions')
    age_rating = models.ForeignKey(AgeRating, on_delete=models.PROTECT, related_name='submissions')
    language = models.ForeignKey(Language, on_delete=models.PROTECT, related_name='submissions')
    source = models.CharField(max_length=200, default='original')
    tones = models.ManyToManyField(Tone, blank=True, related_name='submissions')
    context_tags = models.ManyToManyField(ContextTag, blank=True, related_name='submissions')

    # Workflow
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    rejection_reason = models.TextField(blank=True)
    published_joke = models.OneToOneField(
        Joke,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='submission',
        help_text='The published Joke record if approved'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"Submission by {self.user.email}: {self.text[:40]}... ({self.status})"


# =============================================================================
# Achievements
# =============================================================================

class Achievement(models.Model):
    """Achievement badge definitions."""

    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=100)
    description = models.TextField()
    icon = models.CharField(max_length=50, help_text='Icon name (e.g., bookmark, diamond, flame)')
    criteria_type = models.CharField(
        max_length=50,
        help_text='Metric type: save_count, streak_days, share_count, favorite_count, rating_count'
    )
    criteria_value = models.IntegerField(default=1, help_text='Threshold to unlock')

    class Meta:
        ordering = ['criteria_value']

    def __str__(self):
        return self.title


class UserAchievement(models.Model):
    """Tracks which achievements a user has unlocked."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='achievements'
    )
    achievement = models.ForeignKey(
        Achievement,
        on_delete=models.CASCADE,
        related_name='unlocked_by'
    )
    unlocked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['user', 'achievement']]

    def __str__(self):
        return f"{self.user.email} unlocked {self.achievement.title}"


# =============================================================================
# Compliance: Content Reporting
# =============================================================================

class ContentReport(models.Model):
    """User reports on content (required by app stores)."""

    REASON_CHOICES = [
        ('offensive', 'Offensive Content'),
        ('inappropriate', 'Inappropriate for Rating'),
        ('spam', 'Spam'),
        ('copyright', 'Copyright Violation'),
        ('harassment', 'Harassment'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('reviewed', 'Reviewed'),
        ('resolved', 'Resolved'),
        ('dismissed', 'Dismissed'),
    ]

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='content_reports'
    )
    joke = models.ForeignKey(
        Joke,
        on_delete=models.CASCADE,
        related_name='reports'
    )
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"Report on joke {self.joke_id} by {self.reporter.email} ({self.reason})"


# =============================================================================
# Compliance: User Blocking
# =============================================================================

class UserBlock(models.Model):
    """User blocking relationship (required by app stores)."""

    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='blocked_users'
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='blocked_by'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['blocker', 'blocked']]

    def __str__(self):
        return f"{self.blocker.email} blocked {self.blocked.email}"


# =============================================================================
# Vibes (P2 of Pivot Plan) — curated humor flavors used in onboarding +
# recommendations + Mystery Box pull
# =============================================================================

class Vibe(models.Model):
    """A curated humor flavor — preset filter recipe over Format/Theme/Category.

    Each vibe's "membership" of a joke is computed via its M2M sets:
    a joke matches the vibe iff for every non-empty axis, the joke shares at
    least one value with that axis. (any-match within an axis, AND across axes.)

    Twelve canonical vibes are seeded in migration 0013. Curators can adjust the
    recipe via Django admin; joke→vibe membership updates instantly without
    backfilling.
    """
    slug = models.SlugField(max_length=50, unique=True)
    label = models.CharField(max_length=40)
    subtitle = models.CharField(max_length=80, blank=True)
    icon = models.CharField(
        max_length=8, blank=True,
        help_text='Emoji shown in the picker tile (e.g. 💼)'
    )
    swatch_bg = models.CharField(
        max_length=20, default='#6A1CF6',
        help_text='Hex color for the picker tile background'
    )
    swatch_fg = models.CharField(
        max_length=20, default='#FFFFFF',
        help_text='Hex color for the picker tile text'
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        help_text='Display order in the picker (lower = earlier)'
    )

    # Filter recipe — joke matches iff for each non-empty axis, joke shares ≥1 value.
    formats = models.ManyToManyField(Format, blank=True, related_name='vibes')
    themes = models.ManyToManyField(ContextTag, blank=True, related_name='vibes')
    categories = models.ManyToManyField(Tone, blank=True, related_name='vibes')

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'label']

    def __str__(self):
        return f"{self.icon} {self.label}".strip()

    def filter_jokes(self, queryset=None):
        """Apply this vibe's filter recipe to a Joke queryset.

        A joke matches iff for each non-empty axis, the joke shares at least
        one value with that axis. Empty axes don't constrain.
        """
        if queryset is None:
            queryset = Joke.objects.all()
        format_ids = list(self.formats.values_list('id', flat=True))
        theme_ids = list(self.themes.values_list('id', flat=True))
        category_ids = list(self.categories.values_list('id', flat=True))
        if format_ids:
            queryset = queryset.filter(format_id__in=format_ids)
        if theme_ids:
            queryset = queryset.filter(context_tags__id__in=theme_ids)
        if category_ids:
            queryset = queryset.filter(tones__id__in=category_ids)
        # M2M filters can produce duplicates; collapse them
        return queryset.distinct() if (theme_ids or category_ids) else queryset


class UserVibe(models.Model):
    """A user's selected vibe from onboarding — drives recommendations + Mystery Box."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_vibes'
    )
    vibe = models.ForeignKey(
        Vibe,
        on_delete=models.CASCADE,
        related_name='picked_by'
    )
    weight = models.FloatField(
        default=1.0,
        help_text='Future tuning hook: user can boost/dampen a vibe'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['user', 'vibe']]
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user'])]

    def __str__(self):
        return f"{self.user.email} picked {self.vibe.label}"


# =============================================================================
# Mystery Box (P3 of Pivot Plan) — variable-reward pull from user's vibe pool
# =============================================================================

class MysteryBoxRoll(models.Model):
    """Audit row for every Mystery Box pull — used for daily-cap enforcement
    and same-day deduplication.

    Daily cap is enforced at the view layer via a date-bucketed count
    (no Celery beat needed — the cap "resets" implicitly at midnight UTC
    because new rolls land on a new `rolled_date`).
    """

    MAX_DAILY_ROLLS = 3

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='mystery_rolls',
    )
    joke = models.ForeignKey(
        Joke,
        on_delete=models.CASCADE,
        related_name='mystery_pulls',
    )
    source_vibe = models.ForeignKey(
        Vibe,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text='Which vibe the roll was sourced from (null = global fallback)',
    )
    rolled_at = models.DateTimeField(auto_now_add=True)
    rolled_date = models.DateField(db_index=True)

    class Meta:
        ordering = ['-rolled_at']
        indexes = [
            models.Index(fields=['user', 'rolled_date']),
        ]

    def save(self, *args, **kwargs):
        if not self.rolled_date:
            from django.utils import timezone
            self.rolled_date = timezone.now().date()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email} rolled #{self.joke_id} on {self.rolled_date}"


# =============================================================================
# Joke Reactions (P4 of Pivot Plan) — 4-emoji reaction model
# Coexists with the legacy JokeRating like/dislike model (additive, not destructive)
# =============================================================================

class JokeReaction(models.Model):
    """A user's reaction to a joke — one of 4 emojis: 😂 🤣 🤔 🙄.

    A user has at most ONE reaction per joke (unique_together). Posting a
    different reaction switches; posting the same un-reacts. The legacy
    JokeRating like/dislike model is left in place for historical analytics
    and is not affected.
    """

    REACTION_LOL = 'lol'
    REACTION_CRYING = 'crying'
    REACTION_HMM = 'hmm'
    REACTION_EYEROLL = 'eyeroll'
    REACTION_CHOICES = [
        (REACTION_LOL,     '😂 LOL'),
        (REACTION_CRYING,  '🤣 Crying'),
        (REACTION_HMM,     '🤔 Hmm'),
        (REACTION_EYEROLL, '🙄 Eye-roll'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='joke_reactions',
    )
    joke = models.ForeignKey(
        Joke,
        on_delete=models.CASCADE,
        related_name='reactions_v2',  # _v2 to avoid clash with JokeRating's `ratings`
    )
    reaction = models.CharField(max_length=10, choices=REACTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['user', 'joke']]
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['joke', 'reaction']),
        ]

    def __str__(self):
        return f"{self.user.email} {self.reaction} on joke {self.joke_id}"


# =============================================================================
# JokeView (P5 of Pivot Plan) — activity log; foundational for streaks,
# insights, "continue mid-sip", and Mystery Box recent-exclusion
# =============================================================================

class JokeView(models.Model):
    """A user opened/viewed a joke. Logged synchronously by signal/middleware.

    Single source of truth for "the user did something with this joke today".
    Powers: streak detection, taste profile, recently-viewed list, peak-read-hour
    histogram, "continue mid-sip" pack progress, Mystery Box recent-exclusion.

    Debounced at the view layer — multiple fetches of the same joke within 60s
    don't create duplicate rows.
    """

    SOURCE_DAILY = 'daily'
    SOURCE_SEARCH = 'search'
    SOURCE_EXPLORE = 'explore'
    SOURCE_MYSTERY = 'mystery'
    SOURCE_PACK = 'pack'
    SOURCE_SAVED = 'saved'
    SOURCE_SHARE = 'share'
    SOURCE_OTHER = 'other'
    SOURCE_CHOICES = [
        (SOURCE_DAILY,   'Daily'),
        (SOURCE_SEARCH,  'Search'),
        (SOURCE_EXPLORE, 'Explore'),
        (SOURCE_MYSTERY, 'Mystery'),
        (SOURCE_PACK,    'Pack'),
        (SOURCE_SAVED,   'Saved'),
        (SOURCE_SHARE,   'Share'),
        (SOURCE_OTHER,   'Other'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='joke_views',
    )
    joke = models.ForeignKey(
        Joke,
        on_delete=models.CASCADE,
        related_name='views',
    )
    source = models.CharField(
        max_length=16,
        choices=SOURCE_CHOICES,
        default=SOURCE_OTHER,
        db_index=True,
    )
    revealed_punchline = models.BooleanField(
        default=False,
        help_text='Did the user tap to reveal? Tracks engagement vs. bounce.',
    )
    viewed_at = models.DateTimeField(auto_now_add=True)
    viewed_date = models.DateField(db_index=True)

    class Meta:
        ordering = ['-viewed_at']
        indexes = [
            models.Index(fields=['user', '-viewed_at']),
            models.Index(fields=['user', 'viewed_date']),
            models.Index(fields=['joke', '-viewed_at']),
        ]

    def save(self, *args, **kwargs):
        if not self.viewed_date:
            from django.utils import timezone
            self.viewed_date = timezone.now().date()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email} viewed joke {self.joke_id} @ {self.viewed_at}"


# =============================================================================
# Streak (P6 of Pivot Plan) — daily-return loop with forgiveness
# =============================================================================

class Streak(models.Model):
    """Per-user streak state. Updated synchronously on JokeView post-save +
    lazily reconciled when /streak/ is fetched (no scheduled jobs).

    Forgiveness mechanic:
      - 2 freeze days per calendar month, refreshed lazily on first /streak/
        access in a new month
      - A missed day with freezes available auto-burns one (status='frozen')
      - A missed day with no freezes resets current_count to 0
    """

    FREEZES_PER_MONTH = 2

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='streak',
    )
    current_count = models.PositiveIntegerField(default=0)
    longest_count = models.PositiveIntegerField(default=0)
    last_active_date = models.DateField(null=True, blank=True)
    freeze_days_available = models.PositiveSmallIntegerField(default=FREEZES_PER_MONTH)
    freezes_used_total = models.PositiveIntegerField(default=0)
    last_freeze_refresh_month = models.CharField(
        max_length=7, blank=True,
        help_text='YYYY-MM of the last month we refreshed the freeze pool',
    )
    started_at = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} streak={self.current_count}"


class StreakDay(models.Model):
    """Per-day status for a user. One row per (user, date)."""

    STATUS_READ = 'read'
    STATUS_FROZEN = 'frozen'
    STATUS_MISSED = 'missed'
    STATUS_CHOICES = [
        (STATUS_READ,   'Read'),
        (STATUS_FROZEN, 'Frozen'),
        (STATUS_MISSED, 'Missed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='streak_days',
    )
    date = models.DateField()
    status = models.CharField(max_length=8, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['user', 'date']]
        ordering = ['-date']
        indexes = [
            models.Index(fields=['user', '-date']),
        ]

    def __str__(self):
        return f"{self.user.email} {self.date} → {self.status}"


# =============================================================================
# Joke Packs (P7 of Pivot Plan) — editor-curated themed bundles
# =============================================================================

class JokePack(models.Model):
    """Editor-curated themed bundle of jokes (e.g. "Back-to-school survival kit").

    Different from user `Collection` (user-owned, private library) — packs are
    shipped to all users by editors and have publish/expiry windows.
    """

    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    cover_color = models.CharField(
        max_length=20, default='#FFC965',
        help_text='Hex color for the pack tile background',
    )
    is_published = models.BooleanField(default=False, db_index=True)
    is_featured = models.BooleanField(
        default=False,
        help_text='Surface this pack as the Weekly Special on Today',
    )
    publish_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Hide until this time (null = visible immediately when published)',
    )
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Hide after this time (null = never expires)',
    )

    jokes = models.ManyToManyField(
        Joke,
        through='JokePackEntry',
        related_name='packs',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_featured', '-created_at']

    def __str__(self):
        return self.title


class JokePackEntry(models.Model):
    """Through-table for JokePack ↔ Joke with display order."""
    pack = models.ForeignKey(JokePack, on_delete=models.CASCADE, related_name='entries')
    joke = models.ForeignKey(Joke, on_delete=models.CASCADE, related_name='+')
    order = models.PositiveSmallIntegerField()

    class Meta:
        unique_together = [['pack', 'joke']]
        ordering = ['pack', 'order']

    def __str__(self):
        return f"#{self.order} in {self.pack.title}"


class JokePackProgress(models.Model):
    """Per-user reading progress through a pack — powers "continue mid-sip"."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pack_progress',
    )
    pack = models.ForeignKey(
        JokePack,
        on_delete=models.CASCADE,
        related_name='progress_records',
    )
    last_read_entry = models.PositiveSmallIntegerField(
        default=0,
        help_text='order of the last entry the user read; 0 = not started',
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['user', 'pack']]
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.user.email} → {self.pack.title} (#{self.last_read_entry})"
