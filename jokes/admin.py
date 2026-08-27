from collections import Counter
from datetime import timedelta

from django.contrib import admin
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Achievement,
    AgeRating,
    Appeal,
    Collection,
    ContentReport,
    ContextTag,
    CultureTag,
    DailyJoke,
    Favorite,
    Format,
    Joke,
    JokeMedia,
    JokePack,
    JokePackEntry,
    JokePackProgress,
    JokeRating,
    JokeReaction,
    JokeSubmission,
    JokeView,
    Language,
    MediaAsset,
    MysteryBoxRoll,
    SavedJoke,
    ShareEvent,
    Source,
    Streak,
    StreakDay,
    Tone,
    UserAchievement,
    UserBlock,
    UserPreference,
    UserProfile,
    UserVibe,
    Vibe,
)

# 36h/48h SLA clock values (spec verbatim) — shared by AppealAdmin's
# hours_open red flag and the "overdue" list filter.
APPEAL_SLA_RED_HOURS = 36


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
    # `is_removed` is READ-ONLY on purpose. Ticking it by hand hid the joke
    # without a statement-of-reasons notification, without quarantining its
    # media, without blanking the share card, and left removed_at NULL — which
    # then made the creator's appeal ineligible ("This removal is not eligible
    # for appeal."). Removals must go through the takedown action, which does
    # all of that; `restore_jokes` remains the supported way back.
    readonly_fields = ['created_at', 'updated_at', 'removed_at', 'is_removed']
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
        # Release any quarantined media BEFORE un-removing (mirrors
        # AppealAdmin.reverse_appeals' release-before-unremoved ordering): a
        # restored live joke must serve real media URLs, not quarantine
        # paths — and leaving assets quarantined would let the lazy sweep
        # hard-delete a LIVE joke's media at the 14-day mark.
        joke_ids = list(queryset.values_list('pk', flat=True))
        # Minor: only jokes actually is_removed=True are being flipped by the
        # update() below -- scope the (potentially expensive) share-card
        # regen to those, not every joke in the selection (a no-op reselect
        # of an already-live joke shouldn't pay for a rebuild).
        to_restore_ids = list(
            queryset.filter(is_removed=True).values_list('pk', flat=True)
        )
        assets = MediaAsset.objects.filter(
            joke_links__joke_id__in=joke_ids, quarantined_at__isnull=False,
        ).distinct()
        for asset in assets:
            try:
                asset.release()
            except Exception:
                self.message_user(
                    request,
                    f'Release FAILED for asset {asset.pk} — it stays quarantined; '
                    'retry the restore.',
                    level='WARNING',
                )
        n = queryset.update(is_removed=False, removed_at=None)
        # REVERSAL: the share card was blanked at takedown time (or, for a
        # media joke, may still be an old pre-fix text-only card) -- rebuild
        # it now that the joke is live and its media has been released.
        # Per-item isolation (mirrors the asset.release() loop above): one
        # joke's regen failure must not stop the rest of the batch from
        # getting a fresh card.
        failed_regen_ids = []
        for joke in Joke.all_objects.filter(pk__in=to_restore_ids):
            try:
                joke.regenerate_share_image()
            except Exception:
                failed_regen_ids.append(joke.pk)
        if failed_regen_ids:
            self.message_user(
                request,
                'Share-card regeneration FAILED for joke(s): '
                + ', '.join(str(pk) for pk in failed_regen_ids)
                + ' — the card may be stale; retry the restore.',
                level='WARNING',
            )
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
    list_display = ['user', 'text_preview', 'media_preview', 'safesearch_flags',
                    'format', 'status', 'updated_at']
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

    def media_preview(self, obj):
        link = obj.media.select_related('asset').first()
        if not link or not link.asset.file:
            return '—'
        asset = link.asset
        if asset.kind == 'video':
            if not asset.poster:
                return '—'
            return format_html(
                '<span style="position:relative;display:inline-block;">'
                '<img src="{}" style="max-height:60px;max-width:100px;'
                'border-radius:4px;" />'
                '<span style="position:absolute;bottom:2px;right:2px;'
                'background:rgba(0,0,0,.6);color:#fff;border-radius:50%;'
                'width:16px;height:16px;font-size:10px;line-height:16px;'
                'text-align:center;">▶</span>'
                '</span>',
                asset.poster.url,
            )
        if asset.kind == 'audio':
            seconds = round((asset.duration_ms or 0) / 1000)
            return format_html(
                '<a href="{}">audio ({}s)</a>', asset.file.url, seconds,
            )
        return format_html(
            '<img src="{}" style="max-height:60px;max-width:100px;'
            'border-radius:4px;" />',
            asset.file.url,
        )
    media_preview.short_description = 'Media'

    def safesearch_flags(self, obj):
        flags = []
        for link in obj.media.select_related('asset'):
            verdict = link.asset.safesearch or {}
            # Video verdicts nest per-frame screening results under 'frames'
            # (one dict per sampled frame, same category/level shape as the
            # top-level verdict) — descend into those too, not just the
            # top-level keys.
            for frame in [verdict, *(verdict.get('frames') or [])]:
                flags.extend(
                    f'{category}:{level}'
                    for category, level in frame.items()
                    if category not in ('status', 'frames')
                    and level in ('POSSIBLE', 'LIKELY', 'VERY_LIKELY')
                )
        return ', '.join(flags) or '—'
    safesearch_flags.short_description = 'Screen flags'

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
                    # COPPA age-gating keys entirely on content_tier (see
                    # jokes/serving.allowed_tiers): tier_1 is universal and
                    # reaches minors/anon; tier_2 is mature and adults-only.
                    # Derive the tier from the submission's age rating so
                    # adult/mature jokes (min_age >= 18) don't ship as universal.
                    min_age = getattr(submission.age_rating, 'min_age', None) or 0
                    content_tier = 'tier_2' if min_age >= 18 else 'tier_1'
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
                        content_tier=content_tier,
                    )
                    joke.tones.set(submission.tones.all())
                    joke.context_tags.set(submission.context_tags.all())
                    joke.culture_tags.set(submission.culture_tags.all())
                    for link in submission.media.all():
                        JokeMedia.objects.create(
                            joke=joke, asset=link.asset, position=link.position,
                        )
                    # ORDERING TRAP: Joke.objects.create() above already fired
                    # save() -> a share card, but the media didn't exist yet at
                    # that point, so it's the text-only card. Now that
                    # JokeMedia is attached, force a rebuild so a media
                    # submission publishes with its media card, not a stale
                    # text-only one.
                    joke.regenerate_share_image()
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
        # Capture the affected jokes (is_removed=False) BEFORE the flip: after
        # the update() below they no longer match, and we still need their
        # creator FKs to notify. The row itself stays — only is_removed flips.
        # Statement of reasons (DSA): the notice carries the most common reason
        # among the reports driving THIS takedown (fallback 'other') and the
        # appeal deadline (removed_at + 14 days, ISO).
        from inbox.services import notify
        reasons_by_joke = {}
        for jid, reason in queryset.values_list('joke_id', 'reason'):
            reasons_by_joke.setdefault(jid, []).append(reason)
        to_remove = list(
            Joke.all_objects.filter(pk__in=joke_ids, is_removed=False).select_related('creator')
        )
        removed = Joke.all_objects.filter(pk__in=joke_ids, is_removed=False).update(
            is_removed=True, removed_at=now,
        )
        # TAKEDOWN LEAK: the share card is a SEPARATELY generated PNG (not
        # the media asset itself) embedding a downscaled copy of the
        # poster/image at a guessable share-cards/joke-<pk>.png path. Left
        # in place, it would keep serving a removed joke's poster to OG
        # crawlers (and anyone hitting the URL directly) even after the
        # underlying MediaAsset is quarantined. Blank it -- delete the
        # stored file and clear the field -- for every joke actually
        # removed by this action.
        # Per-item isolation (mirrors the asset.quarantine() loop below): one
        # joke's storage delete failing (transient GCS auth/quota/network)
        # must not abort notify/report-resolve/quarantine for the rest of
        # the batch. Only clear the field for jokes whose file delete
        # actually succeeded -- a joke whose delete failed keeps its field
        # pointing at a file that may still exist, which is the safe,
        # consistent state (and the warning below names it for retry).
        blanked_ids = []
        failed_share_image_ids = []
        for jk in to_remove:
            if not jk.share_image:
                continue
            try:
                jk.share_image.delete(save=False)
            except Exception:
                failed_share_image_ids.append(jk.pk)
                continue
            blanked_ids.append(jk.pk)
        if blanked_ids:
            Joke.all_objects.filter(pk__in=blanked_ids).update(share_image='')
        if failed_share_image_ids:
            self.message_user(
                request,
                'Share-card delete FAILED for joke(s): '
                + ', '.join(str(pk) for pk in failed_share_image_ids)
                + ' — the old card may still be served; retry the takedown for this joke.',
                level='WARNING',
            )
        appeal_deadline = (now + timedelta(days=14)).isoformat()
        for jk in to_remove:
            reasons = reasons_by_joke.get(jk.pk)
            top_reason = Counter(reasons).most_common(1)[0][0] if reasons else 'other'
            notify(
                jk.creator, 'joke_removed', joke=jk,
                reason=top_reason, appeal_deadline=appeal_deadline,
            )
        # Resolve every pending/reviewed report against those jokes.
        ContentReport.objects.filter(joke_id__in=joke_ids).exclude(
            status__in=['resolved', 'dismissed']
        ).update(status='resolved', resolved_at=now)
        # Media lifecycle (reversible takedown): JokeMedia links are KEPT —
        # a reversal (appeal upheld) needs them to restore serving. Nothing
        # is deleted at takedown time anymore. Instead, quarantine() every
        # affected asset that is NOT also linked to a live (non-removed)
        # joke outside this takedown set — that moves the file to an
        # unguessable quarantine/ path, out of every serving surface, while
        # keeping the row (and the option to release() on reversal). An
        # asset shared with a joke that was NOT taken down (and is still
        # live) is left untouched, as before. `to_remove` was already
        # flipped to is_removed=True above, so `joke__is_removed=False`
        # here only matches genuinely external live jokes.
        asset_ids = list(
            MediaAsset.objects.filter(joke_links__joke_id__in=joke_ids)
            .distinct().values_list('pk', flat=True)
        )
        quarantined = 0
        failed_asset_ids = []
        for asset in MediaAsset.objects.filter(pk__in=asset_ids):
            still_shared = JokeMedia.objects.filter(asset=asset, joke__is_removed=False).exclude(
                joke_id__in=joke_ids
            ).exists()
            if still_shared:
                continue
            # Per-asset isolation (mirrors approve_and_publish): one asset's
            # storage failure must not abort the rest of the batch.
            try:
                asset.quarantine()
            except Exception:
                failed_asset_ids.append(asset.pk)
                continue
            quarantined += 1
        if quarantined:
            record_audit(
                request, 'media_quarantined', outcome='success',
                actor=request.user, target_type='joke',
                target_id=','.join(str(j) for j in sorted(joke_ids)),
            )
        if failed_asset_ids:
            self.message_user(
                request,
                'Quarantine FAILED for asset(s): '
                + ', '.join(str(pk) for pk in failed_asset_ids)
                + ' — their files may still sit at serving paths; '
                'retry the takedown for this joke.',
                level='WARNING',
            )
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
# Appeals (Appeals & Notices wave) — resolution queue with SLA clock
# =============================================================================

class OverdueAppealFilter(admin.SimpleListFilter):
    """Appeals still pending more than the 36h SLA-warning threshold."""

    title = f'overdue (>{APPEAL_SLA_RED_HOURS}h open & pending)'
    parameter_name = 'overdue'

    def lookups(self, request, model_admin):
        return [('yes', 'Yes')]

    def queryset(self, request, queryset):
        if self.value() != 'yes':
            return queryset
        cutoff = timezone.now() - timedelta(hours=APPEAL_SLA_RED_HOURS)
        return queryset.filter(status='pending', created_at__lt=cutoff)


@admin.register(Appeal)
class AppealAdmin(admin.ModelAdmin):
    """Moderator resolution queue. Pending appeals surface first (oldest
    first within pending, so the closest-to-SLA-breach are worked first);
    resolved appeals sort after, newest first."""

    list_display = ['target_preview', 'action_type', 'hours_open', 'status', 'created_at']
    list_filter = ['status', 'action_type', OverdueAppealFilter]
    search_fields = ['user__email', 'reason_text']
    raw_id_fields = ['user', 'joke', 'submission', 'resolver']
    readonly_fields = ['created_at', 'resolved_at']
    actions = ['uphold_appeals', 'reverse_appeals']

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('joke', 'submission', 'user')
        # Annotate pending-vs-resolved so pending rows always sort first,
        # regardless of created_at.
        qs = qs.annotate(
            _pending_first=Case(
                When(status='pending', then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        return qs.order_by('_pending_first', 'created_at')

    @admin.display(description='Target')
    def target_preview(self, obj):
        if obj.joke_id:
            text = obj.joke.text if obj.joke else ''
            return f'Joke #{obj.joke_id}: {text[:40]}'
        text = obj.submission.text if obj.submission else ''
        return f'Submission #{obj.submission_id}: {text[:40]}'

    @admin.display(description='Hours open')
    def hours_open(self, obj):
        end = obj.resolved_at or timezone.now()
        hours = (end - obj.created_at).total_seconds() / 3600
        label = f'{hours:.1f}h'
        if obj.status == 'pending' and hours >= APPEAL_SLA_RED_HOURS:
            return format_html('<span style="color:red;font-weight:bold;">{}</span>', label)
        return label

    @admin.action(description='Uphold selected appeals (purge quarantined media)')
    def uphold_appeals(self, request, queryset):
        from audit.services import record_audit
        from inbox.services import notify

        pending = list(queryset.filter(status='pending'))
        skipped = queryset.exclude(status='pending').count()
        now = timezone.now()
        n = 0
        failed = []
        for appeal in pending:
            try:
                if appeal.joke_id:
                    assets = MediaAsset.objects.filter(
                        joke_links__joke_id=appeal.joke_id, quarantined_at__isnull=False,
                    ).distinct()
                    for asset in assets:
                        # Mirror take_down_joke's still_shared guard: between
                        # quarantine and this uphold, the asset may have been
                        # re-attached to a different, still-live joke (e.g. a
                        # reversal-era reshare). Purging it here would destroy
                        # media that joke is still serving — skip it.
                        still_shared = JokeMedia.objects.filter(
                            asset=asset, joke__is_removed=False,
                        ).exclude(joke_id=appeal.joke_id).exists()
                        if still_shared:
                            continue
                        # Sibling-appeal guard: another joke sharing this asset
                        # may be under its OWN pending appeal (both co-taken-
                        # down). Purging now would make THAT appeal's reversal
                        # unable to restore the media — skip if any other
                        # linked joke has a pending appeal.
                        sibling_joke_ids = list(
                            JokeMedia.objects.filter(asset=asset)
                            .exclude(joke_id=appeal.joke_id)
                            .values_list('joke_id', flat=True)
                        )
                        if sibling_joke_ids and Appeal.objects.filter(
                            status='pending', joke_id__in=sibling_joke_ids,
                        ).exists():
                            continue
                        asset.purge()
                appeal.status = 'upheld'
                appeal.resolver = request.user
                appeal.resolved_at = now
                appeal.save(update_fields=['status', 'resolver', 'resolved_at'])
                record_audit(
                    request, 'appeal_upheld', outcome='success', actor=request.user,
                    target_type=appeal.action_type,
                    target_id=str(appeal.joke_id or appeal.submission_id),
                )
                notify(
                    appeal.user, 'appeal_resolved', joke=appeal.joke,
                    outcome='upheld', action_type=appeal.action_type,
                    submission_id=appeal.submission_id,
                )
                n += 1
            except Exception:
                # Per-item isolation (mirrors take_down_joke): one storage/DB
                # failure must not abort the rest of the batch.
                failed.append(appeal.pk)
        msg = f'Upheld {n} appeal(s) (quarantined media purged where applicable).'
        if skipped:
            msg += f' Skipped {skipped} non-pending appeal(s).'
        if failed:
            self.message_user(
                request,
                'Uphold FAILED for appeal(s): ' + ', '.join(str(pk) for pk in failed),
                level='WARNING',
            )
        self.message_user(request, msg)

    @admin.action(description='Reverse selected appeals (restore joke / draft submission)')
    def reverse_appeals(self, request, queryset):
        from audit.services import record_audit
        from inbox.services import notify

        pending = list(queryset.filter(status='pending'))
        skipped = queryset.exclude(status='pending').count()
        now = timezone.now()
        n = 0
        failed = []
        for appeal in pending:
            try:
                if appeal.action_type == 'takedown' and appeal.joke_id:
                    assets = MediaAsset.objects.filter(
                        joke_links__joke_id=appeal.joke_id, quarantined_at__isnull=False,
                    ).distinct()
                    for asset in assets:
                        asset.release()
                    # Mirrors JokeAdmin.restore_jokes: un-remove via the
                    # unfiltered manager (the default manager hides removed jokes).
                    Joke.all_objects.filter(pk=appeal.joke_id).update(
                        is_removed=False, removed_at=None,
                    )
                    # REVERSAL: share_image was blanked at takedown time;
                    # rebuild it now that the joke is live again and its
                    # media has just been released -- media card if media
                    # is present, text card otherwise. Isolated in its own
                    # try/except (mirrors restore_jokes): the joke is
                    # ALREADY live again at this point, so a card regen
                    # blip must not block notify/status=reversed/audit for
                    # the rest of this appeal's resolution.
                    try:
                        Joke.all_objects.get(pk=appeal.joke_id).regenerate_share_image()
                    except Exception:
                        self.message_user(
                            request,
                            f'Share-card regeneration FAILED for joke {appeal.joke_id} '
                            '— the card may be stale; retry the reversal.',
                            level='WARNING',
                        )
                    notify(
                        appeal.user, 'appeal_resolved', joke=appeal.joke,
                        outcome='reversed', action_type='takedown',
                    )
                elif appeal.action_type == 'rejection' and appeal.submission_id:
                    submission = appeal.submission
                    submission.status = 'draft'
                    submission.rejection_reason = (
                        f'Appeal reversed on {now:%Y-%m-%d} — you can edit and resubmit.'
                    )
                    submission.save(update_fields=['status', 'rejection_reason', 'updated_at'])
                    notify(
                        appeal.user, 'appeal_resolved',
                        outcome='reversed', action_type='rejection',
                        submission_id=submission.pk,
                    )
                appeal.status = 'reversed'
                appeal.resolver = request.user
                appeal.resolved_at = now
                appeal.save(update_fields=['status', 'resolver', 'resolved_at'])
                record_audit(
                    request, 'appeal_reversed', outcome='success', actor=request.user,
                    target_type=appeal.action_type,
                    target_id=str(appeal.joke_id or appeal.submission_id),
                )
                n += 1
            except Exception:
                # Per-item isolation (mirrors take_down_joke): one storage/DB
                # failure must not abort the rest of the batch.
                failed.append(appeal.pk)
        msg = f'Reversed {n} appeal(s).'
        if skipped:
            msg += f' Skipped {skipped} non-pending appeal(s).'
        if failed:
            self.message_user(
                request,
                'Reverse FAILED for appeal(s): ' + ', '.join(str(pk) for pk in failed),
                level='WARNING',
            )
        self.message_user(request, msg)


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
