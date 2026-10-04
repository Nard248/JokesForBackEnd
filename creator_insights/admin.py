"""Moderation surface for explicit taxonomy requests, never private notebooks."""
from django.contrib import admin, messages

from creator_insights.library import review_metadata_request
from creator_insights.models import CreatorMetadataRequest


@admin.register(CreatorMetadataRequest)
class CreatorMetadataRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'joke_id', 'status', 'created_at', 'reviewed_at']
    list_filter = ['status', 'created_at']
    readonly_fields = [field.name for field in CreatorMetadataRequest._meta.fields]
    actions = ['approve_requests', 'reject_requests']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Approve selected metadata requests', permissions=['change'])
    def approve_requests(self, request, queryset):
        approved = rejected = 0
        for pk in queryset.filter(status=CreatorMetadataRequest.Status.PENDING).values_list('pk', flat=True):
            result = review_metadata_request(request, pk, approve=True)
            if result.status == CreatorMetadataRequest.Status.APPROVED:
                approved += 1
            else:
                rejected += 1
        self.message_user(request, f'Approved {approved}; rejected {rejected} stale or unavailable requests.', messages.INFO)

    @admin.action(description='Reject selected metadata requests', permissions=['change'])
    def reject_requests(self, request, queryset):
        count = 0
        for pk in queryset.filter(status=CreatorMetadataRequest.Status.PENDING).values_list('pk', flat=True):
            review_metadata_request(request, pk, approve=False, reason='A moderator declined this metadata request.')
            count += 1
        self.message_user(request, f'Rejected {count} metadata requests.', messages.INFO)
