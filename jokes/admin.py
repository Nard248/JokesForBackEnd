from django.contrib import admin
from .models import Joke, Format, AgeRating, Tone, ContextTag, Language, CultureTag, Source, UserPreference, Collection, SavedJoke, DailyJoke, JokeRating, ShareEvent


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
        ('Classification', {'fields': ['format', 'age_rating', 'language', 'source']}),
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
