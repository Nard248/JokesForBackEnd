from django.contrib import admin
from django.db import transaction
from django.utils import timezone
from .models import (
    Joke, Format, AgeRating, Tone, ContextTag, Language, CultureTag, Source,
    UserPreference, Collection, SavedJoke, DailyJoke, JokeRating, ShareEvent,
    UserProfile, Favorite, JokeSubmission, Achievement, UserAchievement,
    ContentReport, UserBlock,
    Vibe, UserVibe, MysteryBoxRoll, JokeReaction, JokeView, Streak, StreakDay,
    JokePack, JokePackEntry, JokePackProgress,
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
    list_display = ['__str__', 'format', 'age_rating', 'language', 'is_removed', 'created_at']
    list_filter = ['is_removed', 'format', 'age_rating', 'tones', 'context_tags', 'language']
    search_fields = ['text', 'setup', 'punchline']
    filter_horizontal = ['tones', 'context_tags', 'culture_tags']
    readonly_fields = ['created_at', 'updated_at', 'removed_at']
    actions = ['restore_jokes']
    fieldsets = [
        ('Content', {'fields': ['text', 'setup', 'punchline']}),
        ('Classification', {'fields': ['format', 'age_rating', 'content_tier', 'language', 'source']}),
        ('Tags', {'fields': ['tones', 'context_tags', 'culture_tags']}),
        ('Moderation', {'fields': ['is_removed', 'removed_at']}),
        ('Metadata', {'fields': ['created_at', 'updated_at'], 'classes': ['collapse']}),
    ]

    def get_queryset(self, request):
        # Admin must see removed jokes (the default manager hides them).
        return Joke.all_objects.get_queryset()

    @admin.action(description='Restore selected jokes (un-remove)')
    def restore_jokes(self, request, queryset):
        n = queryset.update(is_removed=False, removed_at=None)
        self.message_user(request, f'Restored {n} joke(s).')


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
    filter_horizontal = ['tones', 'context_tags', 'culture_tags']
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['published_joke']
    actions = ['approve_and_publish']

    def text_preview(self, obj):
        text = obj.text or obj.setup or (obj.lines[0] if obj.lines else '')
        return text[:50] + '...' if len(text) > 50 else text
    text_preview.short_description = 'Content'

    @admin.action(description='Approve and publish selected submissions')
    def approve_and_publish(self, request, queryset):
        pending = queryset.filter(status='pending')
        created = 0
        skipped = 0
        for submission in pending:
            try:
                with transaction.atomic():
                    source_obj, _ = Source.objects.get_or_create(
                        name=submission.source or 'original'
                    )
                    joke = Joke.objects.create(
                        text=submission.text,
                        setup=submission.setup,
                        punchline=submission.punchline,
                        lines=submission.lines,
                        format=submission.format,
                        age_rating=submission.age_rating,
                        language=submission.language,
                        source=source_obj,
                        creator=submission.user,
                        content_tier='tier_1',
                    )
                    joke.tones.set(submission.tones.all())
                    joke.context_tags.set(submission.context_tags.all())
                    joke.culture_tags.set(submission.culture_tags.all())
                    submission.published_joke = joke
                    submission.status = 'published'
                    submission.save(update_fields=['published_joke', 'status', 'updated_at'])
                    from inbox.services import notify
                    notify(submission.user, 'joke_published', joke=joke)
                    created += 1
            except Exception as exc:
                self.message_user(
                    request, f'Skipped {submission.id}: {exc}', level='WARNING'
                )
                skipped += 1
        non_pending = queryset.exclude(status='pending').count()
        self.message_user(
            request,
            f'Published {created} submission(s); skipped {skipped} error(s); '
            f'{non_pending} not in pending status were ignored.',
        )


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
    list_display = ['reporter', 'joke_preview', 'reason', 'status', 'joke_removed', 'created_at']
    list_filter = ['status', 'reason', 'created_at']
    search_fields = ['reporter__email', 'joke__text', 'description']
    raw_id_fields = ['joke']
    readonly_fields = ['created_at', 'resolved_at']
    actions = ['take_down_joke', 'dismiss_reports', 'mark_resolved']

    def get_queryset(self, request):
        # Reports may point at already-removed jokes; the FK uses the base manager
        # so this is fine, but select_related keeps the changelist efficient.
        return super().get_queryset(request).select_related('joke', 'reporter')

    def joke_preview(self, obj):
        return obj.joke.text[:50] + '...' if len(obj.joke.text) > 50 else obj.joke.text
    joke_preview.short_description = 'Joke'

    @admin.display(boolean=True, description='Joke removed')
    def joke_removed(self, obj):
        return obj.joke.is_removed

    @admin.action(description='Take down reported joke (remove + resolve its reports)')
    def take_down_joke(self, request, queryset):
        from audit.services import record_audit
        joke_ids = set(queryset.values_list('joke_id', flat=True))
        now = timezone.now()
        # Notify creators before flipping the flag (need the creator FK; the row
        # stays, only is_removed changes). One notification per affected joke.
        from inbox.services import notify
        to_remove = list(
            Joke.all_objects.filter(pk__in=joke_ids, is_removed=False).select_related('creator')
        )
        removed = Joke.all_objects.filter(pk__in=joke_ids, is_removed=False).update(
            is_removed=True, removed_at=now,
        )
        for jk in to_remove:
            notify(jk.creator, 'joke_removed', joke=jk)
        # Resolve every pending/reviewed report against those jokes.
        ContentReport.objects.filter(joke_id__in=joke_ids).exclude(
            status__in=['resolved', 'dismissed']
        ).update(status='resolved', resolved_at=now)
        for jid in joke_ids:
            record_audit(request, 'content_takedown', outcome='success', actor=request.user,
                         target_type='joke', target_id=str(jid))
        self.message_user(request, f'Removed {removed} joke(s) and resolved their reports.')

    @admin.action(description='Dismiss selected reports (no action on joke)')
    def dismiss_reports(self, request, queryset):
        n = queryset.update(status='dismissed', resolved_at=timezone.now())
        self.message_user(request, f'Dismissed {n} report(s).')

    @admin.action(description='Mark selected reports resolved')
    def mark_resolved(self, request, queryset):
        n = queryset.update(status='resolved', resolved_at=timezone.now())
        self.message_user(request, f'Marked {n} report(s) resolved.')


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


@admin.register(Streak)
class StreakAdmin(admin.ModelAdmin):
    list_display = ['user', 'current_count', 'longest_count', 'freeze_days_available', 'last_active_date']
    search_fields = ['user__email']
    raw_id_fields = ['user']
    readonly_fields = ['updated_at']


@admin.register(StreakDay)
class StreakDayAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'status']
    list_filter = ['status', 'date']
    search_fields = ['user__email']
    raw_id_fields = ['user']
    date_hierarchy = 'date'


# =============================================================================
# Joke Packs (P7 of Pivot Plan)
# =============================================================================

class JokePackEntryInline(admin.TabularInline):
    model = JokePackEntry
    raw_id_fields = ['joke']
    extra = 1
    ordering = ['order']


@admin.register(JokePack)
class JokePackAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'is_published', 'is_featured', 'entry_count', 'publish_at', 'expires_at']
    list_editable = ['is_published', 'is_featured']
    list_filter = ['is_published', 'is_featured']
    search_fields = ['title', 'slug', 'description']
    prepopulated_fields = {'slug': ('title',)}
    inlines = [JokePackEntryInline]
    readonly_fields = ['created_at', 'updated_at', 'created_by']

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description='Jokes')
    def entry_count(self, obj):
        return obj.entries.count()


@admin.register(JokePackProgress)
class JokePackProgressAdmin(admin.ModelAdmin):
    list_display = ['user', 'pack', 'last_read_entry', 'completed_at', 'updated_at']
    list_filter = ['pack']
    search_fields = ['user__email', 'pack__title']
    raw_id_fields = ['user', 'pack']
    readonly_fields = ['started_at', 'updated_at']
