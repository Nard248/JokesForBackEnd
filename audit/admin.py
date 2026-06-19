"""Read-only Django admin for AuditLog.

No add/change/delete permissions — the audit log is append-only by design
and must not be modifiable even by staff.
"""
from django.contrib import admin

from audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'outcome', 'actor', 'actor_email_hash', 'ip', 'created_at')
    list_filter = ('action', 'outcome', 'created_at')
    search_fields = ('action', 'actor_email_hash', 'request_id')
    readonly_fields = (
        'actor', 'actor_email_hash', 'action', 'target_type', 'target_id',
        'ip', 'request_id', 'user_agent', 'outcome', 'metadata', 'created_at',
    )
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
