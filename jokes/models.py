from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
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

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            GinIndex(fields=['search_vector'], name='joke_search_vector_idx'),
        ]

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
