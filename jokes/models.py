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
    """Humor tone: clean, dark, dad-jokes, puns, sarcasm"""
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class ContextTag(models.Model):
    """Context/situation: wedding, work, school, presentation, icebreaker"""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)

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
