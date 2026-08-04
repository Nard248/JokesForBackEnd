from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import models
from django.utils import timezone
import pgtrigger
import secrets
import uuid

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

    # Manager. `objects` hides removed jokes globally (takedown enforcement);
    # `all_objects` is unfiltered for admin/moderation (view/restore removed).
    objects = JokeManager()
    all_objects = models.Manager()

    # Content
    text = models.TextField(help_text="Full joke text for one-liners or complete jokes")
    setup = models.TextField(blank=True, help_text="Setup for two-part jokes")
    punchline = models.TextField(blank=True, help_text="Punchline for two-part jokes")

    # Foreign Keys (single value)
    format = models.ForeignKey(Format, on_delete=models.PROTECT, related_name='jokes')
    age_rating = models.ForeignKey(AgeRating, on_delete=models.PROTECT, related_name='jokes')
    language = models.ForeignKey(Language, on_delete=models.PROTECT, related_name='jokes')
    source = models.ForeignKey(Source, on_delete=models.SET_NULL, null=True, blank=True, related_name='jokes')
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_jokes',
        db_index=True,
        help_text='Attributed creator, stamped at publish time. Null = legacy/seed/curated.',
    )

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

    # Moderation takedown (Wave 2). Removed jokes are excluded from all viewer
    # read paths but retained for audit/appeal (not deleted). Set via admin triage.
    is_removed = models.BooleanField(
        default=False, db_index=True,
        help_text='Removed by moderation; hidden from all users but kept for audit.',
    )
    removed_at = models.DateTimeField(null=True, blank=True)

    # P10: knock-knock dialogue storage. Null for non-knock formats. Frontend
    # renders one bubble per line; even/odd indices alternate speaker (A/B).
    lines = models.JSONField(
        null=True, blank=True,
        help_text='List of dialogue lines for knock-knock format; null for other formats.',
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
        self._original_is_removed = self.is_removed if self.pk else False

    def save(self, *args, **kwargs):
        was_existing = bool(self.pk)

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

        # CRITICAL: a removed joke must NEVER (re)generate a share card.
        # Its card was deliberately blanked at takedown time (or on a
        # direct is_removed transition, see below) -- without this guard, a
        # moderator opening the removed joke in the JokeAdmin change form
        # and hitting Save trips the "not self.share_image" branch above,
        # reads the still-readable (merely quarantined -- quarantine only
        # moves the file within the bucket) media asset, and writes a fresh
        # PNG straight back to the PUBLIC share-cards/joke-<pk>.png path
        # (GCS file_overwrite=True reclaims the exact cached URL) --
        # re-leaking the removed joke's poster. The persistence update()
        # below also uses the FILTERED default manager, so for a removed
        # joke it would silently match 0 rows -- the DB field stays blank
        # while the file exists on disk/bucket, and nothing warns.
        if self.is_removed:
            regenerate = False

        # IMPORTANT: a live->removed transition made directly via save()
        # (e.g. the JokeAdmin change form, which bypasses
        # ContentReportAdmin.take_down_joke entirely) must blank the card
        # here too, or that path leaves it serving. Only existing jokes can
        # transition -- a brand-new joke created pre-removed has no card
        # yet (regenerate is already forced False above).
        if was_existing and not self._original_is_removed and self.is_removed:
            if self.share_image:
                self.share_image.delete(save=False)

        # Save first to ensure pk exists
        super().save(*args, **kwargs)

        # Generate share image after save
        if regenerate:
            self._generate_share_image()
            # Save again with the image (avoid recursion by using update)
            Joke.objects.filter(pk=self.pk).update(share_image=self.share_image.name)

        self._original_text = self.text
        self._original_is_removed = self.is_removed

    def _generate_share_image(self):
        """Generate themed share card PNG."""
        from .share_cards import generate_share_card_png

        png_buffer = generate_share_card_png(self)
        filename = f'joke-{self.pk}.png'
        self.share_image.save(filename, ContentFile(png_buffer.read()), save=False)

    def regenerate_share_image(self):
        """Public wrapper around _generate_share_image() so admin code can
        force a card rebuild outside of save()'s text-changed check.

        Needed because `save()` only regenerates when `text` changes or no
        image exists yet -- it has no way to notice that a joke's MEDIA
        arrived after its row was created (approve_and_publish's ordering
        trap: JokeMedia is copied AFTER Joke.objects.create() already fired
        save()), or that media was released back from quarantine on an
        appeal reversal/restore. Mirrors save()'s persistence exactly: the
        new file name is written via a queryset .update() rather than a
        recursive save().

        CRITICAL: a removed joke must NEVER (re)generate a card (see the
        matching guard in save()) -- a no-op here rather than an implicit
        assumption every caller remembers to check first.
        """
        if self.is_removed:
            return
        self._generate_share_image()
        Joke.objects.filter(pk=self.pk).update(share_image=self.share_image.name)

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
    # P8: day-of-week mask for the daily ritual. JSON list of weekday names
    # (lowercase 3-letter): ['mon','tue','wed','thu','fri','sat','sun'].
    # Empty list = no days. Default = weekdays.
    notification_days = models.JSONField(
        default=list,
        blank=True,
        help_text='Weekdays the user wants the daily push: ["mon","tue",...]',
    )
    # P8: streak-saver in-app nudge (no push delivery — frontend reads the flag)
    streak_saver_enabled = models.BooleanField(default=True)

    # Granular notification preferences
    notification_daily_joke = models.BooleanField(default=True)
    notification_trending_alerts = models.BooleanField(default=False)
    notification_collection_updates = models.BooleanField(default=True)
    notification_email_digest = models.BooleanField(default=False)
    onboarding_completed = models.BooleanField(default=False)
    show_mature = models.BooleanField(
        default=False,
        help_text='Adult opt-in to mature (tier_2) content. Default off. Only honored for 18+ users.',
    )
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

    # Public identity (creator profiles, follower lists). Never derived from email.
    display_name = models.CharField(max_length=50, blank=True, default='')
    handle = models.CharField(
        max_length=30, blank=True, null=True, unique=True,
        help_text='User-chosen public @handle (lowercase alphanumeric/underscore). Null = unset.',
    )

    # Privacy settings
    public_profile = models.BooleanField(default=True)
    show_activity = models.BooleanField(default=True)
    share_analytics = models.BooleanField(default=False)

    # Age gating (COPPA). Null = treated as non-adult (OAuth/legacy users fail safe to tier_1).
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        help_text='Neutral DOB for age gating (COPPA). Null = treated as non-adult.',
    )

    # Theme
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default='light')

    # Email preferences (CAN-SPAM one-click unsubscribe flips these; see
    # notifications.unsubscribe). Opt-in true by default per product call.
    email_digest_opt_in = models.BooleanField(default=True)
    creator_milestone_opt_in = models.BooleanField(default=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self):
        return f"Profile for {self.user.email}"

    @property
    def age(self):
        """Return integer age in years, or None if DOB is not set."""
        if self.date_of_birth is None:
            return None
        today = timezone.now().date()
        dob = self.date_of_birth
        years = today.year - dob.year - (
            1 if (today.month, today.day) < (dob.month, dob.day) else 0
        )
        return years

    @property
    def is_adult(self):
        """True only if age is known and >= 18."""
        a = self.age
        return a is not None and a >= 18

    @property
    def is_minor(self):
        """True if age is unknown (null DOB) or < 18. Fail-safe direction."""
        return not self.is_adult


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
    culture_tags = models.ManyToManyField(
        CultureTag, blank=True, related_name='submissions'
    )

    # Knock-knock dialogue storage. Mirrors Joke.lines. Null for non-knock formats.
    lines = models.JSONField(
        null=True, blank=True,
        help_text='Dialogue lines for knock-knock format; null for other formats.',
    )

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
# JokeImpression — audience telemetry: "a real user saw this joke card in a
# list/feed" (vs JokeView which is a detail-open). Powers reach / open-rate.
# Ingested in bulk via POST /api/v1/telemetry/events (request-driven only).
# =============================================================================

class JokeImpression(models.Model):
    """A user saw this joke's card in a list/feed surface (not a detail open).

    Deduped to at most one row per (user, joke, created_date) at ingest time so
    distinct-reach stays honest. This is the missing impression/reach signal:
    JokeView is a detail-open, JokeImpression is a card-seen.
    """

    SOURCE_FEED = 'feed'
    SOURCE_EXPLORE = 'explore'
    SOURCE_SEARCH = 'search'
    SOURCE_DAILY = 'daily'
    SOURCE_PACK = 'pack'
    SOURCE_OTHER = 'other'
    SOURCE_CHOICES = [
        (SOURCE_FEED,    'Feed'),
        (SOURCE_EXPLORE, 'Explore'),
        (SOURCE_SEARCH,  'Search'),
        (SOURCE_DAILY,   'Daily'),
        (SOURCE_PACK,    'Pack'),
        (SOURCE_OTHER,   'Other'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='joke_impressions',
    )
    joke = models.ForeignKey(
        Joke,
        on_delete=models.CASCADE,
        related_name='impressions',
    )
    source = models.CharField(
        max_length=16,
        choices=SOURCE_CHOICES,
        default=SOURCE_OTHER,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_date = models.DateField(db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['joke', 'created_date']),
            models.Index(fields=['user', 'joke', 'created_date']),
        ]

    def save(self, *args, **kwargs):
        if not self.created_date:
            from django.utils import timezone
            self.created_date = timezone.now().date()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email} saw joke {self.joke_id} @ {self.created_date}"


# =============================================================================
# JokeDwell — audience telemetry Phase 2: "user kept this joke visible for N ms
# (and scrolled S%)". Powers read-time / read-rate / completion analytics.
# Append-only (multiple rows per user/joke ok — we average/sum). Ingested in
# bulk via POST /api/v1/telemetry/events (request-driven only).
# =============================================================================

class JokeDwell(models.Model):
    """A user kept this joke's card/detail visible for ``dwell_ms`` milliseconds,
    optionally scrolling ``scroll_pct`` of the way through (for long/story jokes).

    Unlike JokeImpression this is intentionally NOT deduped — every dwell sample
    is a row and we average / sum across them to compute read-time and
    read-through metrics.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='joke_dwells',
    )
    joke = models.ForeignKey(
        Joke,
        on_delete=models.CASCADE,
        related_name='dwells',
    )
    dwell_ms = models.PositiveIntegerField()
    # 0–100, optional read-through depth (most meaningful for long/story jokes).
    scroll_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    source = models.CharField(max_length=16, default='other')
    created_at = models.DateTimeField(auto_now_add=True)
    created_date = models.DateField(db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['joke', 'created_date']),
        ]

    def save(self, *args, **kwargs):
        if not self.created_date:
            from django.utils import timezone
            self.created_date = timezone.now().date()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email} dwelt {self.dwell_ms}ms on joke {self.joke_id} @ {self.created_date}"


# =============================================================================
# JokeWatch — audience telemetry Phase 3: "user watched N ms of this joke's
# video/audio media, reaching P% of it". Powers watch-time / watch-completion
# analytics for media (video/audio) jokes. Append-only (multiple rows per
# user/joke ok — we average/sum), mirrors JokeDwell exactly. Ingested in bulk
# via POST /api/v1/telemetry/events (request-driven only).
# =============================================================================

class JokeWatch(models.Model):
    """A user watched this joke's video/audio media for ``watch_ms``
    milliseconds, reaching ``watch_pct`` percent of the media's duration.

    Unlike JokeImpression this is intentionally NOT deduped — every watch
    sample is a row and we average across them to compute watch-time and
    watch-completion metrics.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='joke_watches',
    )
    joke = models.ForeignKey(
        Joke,
        on_delete=models.CASCADE,
        related_name='watches',
    )
    watch_ms = models.PositiveIntegerField()
    # 0–100, percent of media duration watched.
    watch_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    source = models.CharField(max_length=16, default='other')
    watched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['joke', 'watched_at']),
        ]

    def __str__(self):
        return f"{self.user.email} watched {self.watch_ms}ms of joke {self.joke_id} @ {self.watched_at}"


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


# =============================================================================
# Media Assets (Wave 1: image jokes; video/audio arrive in Wave 2)
# =============================================================================

def media_asset_path(instance, filename):
    """Unguessable, stable storage path: media-assets/<uuid>/<name>."""
    return f'media-assets/{instance.pk}/{filename}'


class MediaAsset(models.Model):
    """A user-owned uploaded media file (the display derivative, never the
    original). Owned by the USER, not a draft, so uploads may precede draft
    creation. Files live in the default storage (GCS in prod) at UUID paths;
    pre-moderation exposure at unguessable public URLs is an accepted spec
    trade-off (spec §3.3). Deletion must go through delete_with_files() so
    storage objects never orphan (no cron exists to sweep them)."""

    KIND_CHOICES = [('image', 'Image'), ('video', 'Video'), ('audio', 'Audio')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='media_assets',
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    file = models.FileField(upload_to=media_asset_path)
    poster = models.ImageField(upload_to=media_asset_path, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    is_gif = models.BooleanField(default=False)
    safesearch = models.JSONField(null=True, blank=True)
    phash = models.CharField(max_length=32, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    quarantined_at = models.DateTimeField(null=True, blank=True)

    def _move_stored_files(self, path_for, extra_update_fields):
        """Crash-safe move of every populated FieldFile (file, poster) to the
        path `path_for(basename)` computes, via default_storage — works on
        both FileSystemStorage and GCS (no direct google.cloud.storage use,
        no signing needed).

        Ordering matters: copy ALL fields' bytes to their new paths, persist
        the new names (+ `extra_update_fields`, already set by the caller) in
        ONE model save, and only THEN delete the old objects. A crash at any
        point leaves at worst a harmless duplicate at the new path — the DB
        never points at a deleted object, and a retry completes the move. If
        a new path already exists from a prior partial attempt it is
        overwritten (deleted first — FileSystemStorage would otherwise
        suffix-rename; GCS with file_overwrite=True overwrites anyway)."""
        old_names = []
        moved = []
        for field_name in ('file', 'poster'):
            field_file = getattr(self, field_name)
            if not field_file:
                continue
            old_name = field_file.name
            basename = old_name.rsplit('/', 1)[-1]
            new_name = path_for(basename)
            with default_storage.open(old_name, 'rb') as fh:
                content = fh.read()
            if default_storage.exists(new_name):
                default_storage.delete(new_name)
            saved_name = default_storage.save(new_name, ContentFile(content))
            field_file.name = saved_name
            old_names.append(old_name)
            moved.append(field_name)
        self.save(update_fields=moved + extra_update_fields)
        for old_name in old_names:
            default_storage.delete(old_name)

    def quarantine(self):
        """Move every stored file to quarantine/<uuid>/<random>/<basename> and
        stamp quarantined_at. Idempotent: a no-op if already quarantined.

        The random path segment is load-bearing for the compliance invariant:
        the asset pk is the SAME uuid that was in the pre-takedown PUBLIC url
        (media-assets/<uuid>/...), and the basename is a deterministic
        derivative name — so without an unguessable segment the quarantine
        path would be derivable by prefix substitution, letting anyone who
        saw the live joke (the taken-down creator above all) fetch the file
        from the public bucket for the 14-day retention. The token lives in
        the FieldFile name persisted to the DB; release() reconstructs the
        original media-assets/<uuid>/<basename> path from the basename alone,
        so the segment is correctly dropped on a legitimate reversal."""
        if self.quarantined_at:
            return
        self.quarantined_at = timezone.now()
        token = secrets.token_urlsafe(16)
        self._move_stored_files(
            lambda basename: f'quarantine/{self.pk}/{token}/{basename}',
            ['quarantined_at'],
        )

    def release(self):
        """Reverse of quarantine(): move files back to the original-style
        media-assets/<uuid>/<basename> path and clear the stamp. Idempotent:
        a no-op if not currently quarantined."""
        if not self.quarantined_at:
            return
        self.quarantined_at = None
        self._move_stored_files(
            lambda basename: f'media-assets/{self.pk}/{basename}', ['quarantined_at'],
        )

    def purge(self):
        """Hard deletion. Thin alias — delete_with_files() stays the ONLY
        storage-deletion path."""
        self.delete_with_files()

    def delete_with_files(self):
        """Delete storage objects, then the row (links CASCADE away)."""
        for field_file in (self.file, self.poster):
            if field_file:
                field_file.delete(save=False)
        self.delete()

    def __str__(self):
        return f'{self.kind} asset {self.id} ({self.owner_id})'


class JokeSubmissionMedia(models.Model):
    """Ordered media attachment on a draft/submission."""
    submission = models.ForeignKey(
        JokeSubmission, on_delete=models.CASCADE, related_name='media',
    )
    asset = models.ForeignKey(
        MediaAsset, on_delete=models.CASCADE, related_name='submission_links',
    )
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(
                fields=['submission', 'position'],
                name='uniq_submission_media_position',
            ),
        ]


class JokeMedia(models.Model):
    """Ordered media attachment on a published joke (copied at publish)."""
    joke = models.ForeignKey(
        Joke, on_delete=models.CASCADE, related_name='media',
    )
    asset = models.ForeignKey(
        MediaAsset, on_delete=models.CASCADE, related_name='joke_links',
    )
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(
                fields=['joke', 'position'], name='uniq_joke_media_position',
            ),
        ]


class Appeal(models.Model):
    """Creator appeal against a takedown (removed Joke) or a rejected
    JokeSubmission. Exactly one of joke/submission is set (DB check
    constraint); at most one PENDING appeal may exist per target (partial
    unique index) — a resolved appeal (upheld/reversed) doesn't block filing
    a new one against the same target."""

    ACTION_CHOICES = [
        ('takedown', 'Takedown'),
        ('rejection', 'Rejection'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('upheld', 'Upheld'),
        ('reversed', 'Reversed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='appeals',
    )
    joke = models.ForeignKey(
        Joke, on_delete=models.CASCADE, null=True, blank=True, related_name='appeals',
    )
    submission = models.ForeignKey(
        JokeSubmission, on_delete=models.CASCADE, null=True, blank=True, related_name='appeals',
    )
    action_type = models.CharField(max_length=10, choices=ACTION_CHOICES)
    reason_text = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    resolution_note = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(joke__isnull=False, submission__isnull=True)
                    | models.Q(joke__isnull=True, submission__isnull=False)
                ),
                name='appeal_exactly_one_target',
            ),
            models.UniqueConstraint(
                fields=['user', 'joke'],
                condition=models.Q(status='pending'),
                name='uniq_pending_appeal_per_user_joke',
            ),
            models.UniqueConstraint(
                fields=['user', 'submission'],
                condition=models.Q(status='pending'),
                name='uniq_pending_appeal_per_user_submission',
            ),
        ]

    def __str__(self):
        target = f'joke {self.joke_id}' if self.joke_id else f'submission {self.submission_id}'
        return f'Appeal({self.action_type}) by {self.user_id} on {target} [{self.status}]'
