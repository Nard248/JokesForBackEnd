from django.contrib import admin

from communities.models import Community, CommunityMembership


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
