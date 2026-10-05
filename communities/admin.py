from django.contrib import admin

from communities.models import Community, CommunityMembership, CommunityState


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ('tag', 'emoji', 'color', 'is_listed')
    list_editable = ('emoji', 'color', 'is_listed')
    search_fields = ('tag__name', 'tag__slug')


@admin.register(CommunityMembership)
class CommunityMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'community', 'state', 'updated_at')
    list_filter = ('state', 'community')
    raw_id_fields = ('user',)


@admin.register(CommunityState)
class CommunityStateAdmin(admin.ModelAdmin):
    """Formation tracking (communities/formation.py). Read-only: edits would re-send or swallow notices."""
    list_display = ('community', 'status', 'observed_at', 'active_since', 'inactive_since', 'notified_at')
    list_filter = ('status',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
