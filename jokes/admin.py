from django.contrib import admin
from .models import (
    Joke, Format, AgeRating, Tone, ContextTag, Language, CultureTag, Source,
    UserPreference, Collection, SavedJoke, DailyJoke, JokeRating, ShareEvent,
    UserProfile, Favorite, JokeSubmission, Achievement, UserAchievement,
    ContentReport, UserBlock,
    Vibe, UserVibe, MysteryBoxRoll, JokeReaction, JokeView,
)


@admin.register(Format)
class FormatAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(AgeRating)
class AgeRatingAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'min_age']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Tone)
class ToneAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(ContextTag)
class ContextTagAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ['code', 'name']
    search_fields = ['code', 'name']


@admin.register(CultureTag)
class CultureTagAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ['name', 'url']
    search_fields = ['name']


@admin.register(Joke)
class JokeAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'format', 'age_rating', 'language', 'created_at']
    list_filter = ['format', 'age_rating', 'tones', 'context_tags', 'language']
    search_fields = ['text', 'setup', 'punchline']
    filter_horizontal = ['tones', 'context_tags', 'culture_tags']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = [
        ('Content', {'fields': ['text', 'setup', 'punchline']}),
        ('Classification', {'fields': ['format', 'age_rating', 'content_tier', 'language', 'source']}),
        ('Tags', {'fields': ['tones', 'context_tags', 'culture_tags']}),
        ('Metadata', {'fields': ['created_at', 'updated_at'], 'classes': ['collapse']}),
    ]


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ['user', 'preferred_age_rating', 'notification_enabled', 'onboarding_completed', 'created_at']
    list_filter = ['notification_enabled', 'onboarding_completed', 'preferred_age_rating']
    search_fields = ['user__email']
    filter_horizontal = ['preferred_tones', 'preferred_contexts']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'is_default', 'created_at']
    list_filter = ['is_default', 'created_at']
    search_fields = ['name', 'user__email']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(SavedJoke)
class SavedJokeAdmin(admin.ModelAdmin):
    list_display = ['user', 'joke', 'collection', 'created_at']
    list_filter = ['created_at', 'collection']
    search_fields = ['user__email', 'joke__text']
    readonly_fields = ['created_at']
    raw_id_fields = ['joke']


@admin.register(DailyJoke)
class DailyJokeAdmin(admin.ModelAdmin):
    list_display = ['user', 'joke', 'date', 'delivered_at']
    list_filter = ['date', 'delivered_at']
    search_fields = ['user__email']
    date_hierarchy = 'date'
    raw_id_fields = ['user', 'joke']


@admin.register(JokeRating)
class JokeRatingAdmin(admin.ModelAdmin):
    list_display = ['user', 'joke_truncated', 'rating', 'created_at']
    list_filter = ['rating', 'created_at']
    search_fields = ['user__email', 'joke__text']
    raw_id_fields = ['joke']
    readonly_fields = ['created_at', 'updated_at']

    def joke_truncated(self, obj):
        """Return truncated joke text."""
        text = obj.joke.text
        return text[:50] + '...' if len(text) > 50 else text
    joke_truncated.short_description = 'Joke'


@admin.register(ShareEvent)
class ShareEventAdmin(admin.ModelAdmin):
    list_display = ['id', 'joke_preview', 'user', 'platform', 'created_at']
    list_filter = ['platform', 'created_at']
    search_fields = ['user__email', 'joke__text']
    raw_id_fields = ['joke', 'user']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at']

    def joke_preview(self, obj):
        return obj.joke.text[:50] + '...' if len(obj.joke.text) > 50 else obj.joke.text
    joke_preview.short_description = 'Joke'


# =============================================================================
# Phase 1: New Models Admin
# =============================================================================

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_premium', 'public_profile', 'theme', 'created_at']
    list_filter = ['is_premium', 'theme', 'public_profile']
    search_fields = ['user__email']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ['user', 'joke_preview', 'created_at']
    search_fields = ['user__email', 'joke__text']
    raw_id_fields = ['joke']
    readonly_fields = ['created_at']

    def joke_preview(self, obj):
        return obj.joke.text[:50] + '...' if len(obj.joke.text) > 50 else obj.joke.text
    joke_preview.short_description = 'Joke'


@admin.register(JokeSubmission)
class JokeSubmissionAdmin(admin.ModelAdmin):
    list_display = ['user', 'text_preview', 'format', 'status', 'updated_at']
    list_filter = ['status', 'format', 'age_rating']
    search_fields = ['user__email', 'text', 'setup', 'punchline']
    filter_horizontal = ['tones', 'context_tags']
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['published_joke']

    def text_preview(self, obj):
        text = obj.text or obj.setup or ''
        return text[:50] + '...' if len(text) > 50 else text
    text_preview.short_description = 'Content'


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'criteria_type', 'criteria_value', 'icon']
    prepopulated_fields = {'slug': ('title',)}


@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    list_display = ['user', 'achievement', 'unlocked_at']
    search_fields = ['user__email', 'achievement__title']
    raw_id_fields = ['user']
    readonly_fields = ['unlocked_at']


@admin.register(ContentReport)
class ContentReportAdmin(admin.ModelAdmin):
    list_display = ['reporter', 'joke_preview', 'reason', 'status', 'created_at']
    list_filter = ['status', 'reason', 'created_at']
    search_fields = ['reporter__email', 'joke__text', 'description']
    raw_id_fields = ['joke']
    readonly_fields = ['created_at']

    def joke_preview(self, obj):
        return obj.joke.text[:50] + '...' if len(obj.joke.text) > 50 else obj.joke.text
    joke_preview.short_description = 'Joke'


@admin.register(UserBlock)
class UserBlockAdmin(admin.ModelAdmin):
    list_display = ['blocker', 'blocked', 'created_at']
    search_fields = ['blocker__email', 'blocked__email']
    readonly_fields = ['created_at']


# =============================================================================
# Vibes (P2 of Pivot Plan)
# =============================================================================

@admin.register(Vibe)
class VibeAdmin(admin.ModelAdmin):
    list_display = ['order', 'icon', 'label', 'slug', 'is_active', 'recipe_summary']
    list_editable = ['is_active']
    list_display_links = ['icon', 'label']
    list_filter = ['is_active']
    search_fields = ['label', 'slug', 'subtitle']
    prepopulated_fields = {'slug': ('label',)}
    filter_horizontal = ['formats', 'themes', 'categories']
    fieldsets = [
        ('Identity', {
            'fields': ['slug', 'label', 'subtitle', 'icon', 'order', 'is_active'],
        }),
        ('Display swatches (hex)', {
            'fields': ['swatch_bg', 'swatch_fg'],
            'description': 'Used in the onboarding picker tile and hero surfaces.',
        }),
        ('Filter recipe', {
            'fields': ['formats', 'themes', 'categories'],
            'description': (
                'A joke matches this vibe iff for each non-empty axis, the joke '
                'shares at least one value with that axis. Empty axes do not '
                'constrain. Edit anytime — joke→vibe membership recomputes on '
                'every query, no backfill needed.'
            ),
        }),
    ]
    readonly_fields = ['created_at', 'updated_at']

    @admin.display(description='Recipe (F·T·C)')
    def recipe_summary(self, obj):
        return f'{obj.formats.count()}·{obj.themes.count()}·{obj.categories.count()}'


@admin.register(UserVibe)
class UserVibeAdmin(admin.ModelAdmin):
    list_display = ['user', 'vibe', 'weight', 'created_at']
    list_filter = ['vibe']
    search_fields = ['user__email', 'vibe__label']
    raw_id_fields = ['user']
    readonly_fields = ['created_at']


@admin.register(MysteryBoxRoll)
class MysteryBoxRollAdmin(admin.ModelAdmin):
    list_display = ['user', 'joke', 'source_vibe', 'rolled_date', 'rolled_at']
    list_filter = ['rolled_date', 'source_vibe']
    search_fields = ['user__email']
    raw_id_fields = ['user', 'joke', 'source_vibe']
    readonly_fields = ['rolled_at', 'rolled_date']
    date_hierarchy = 'rolled_date'


@admin.register(JokeReaction)
class JokeReactionAdmin(admin.ModelAdmin):
    list_display = ['user', 'joke', 'reaction', 'updated_at']
    list_filter = ['reaction']
    search_fields = ['user__email']
    raw_id_fields = ['user', 'joke']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(JokeView)
class JokeViewAdmin(admin.ModelAdmin):
    list_display = ['user', 'joke', 'source', 'revealed_punchline', 'viewed_at']
    list_filter = ['source', 'revealed_punchline', 'viewed_date']
    search_fields = ['user__email']
    raw_id_fields = ['user', 'joke']
    readonly_fields = ['viewed_at', 'viewed_date']
    date_hierarchy = 'viewed_date'
