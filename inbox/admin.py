from django.contrib import admin

from inbox.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['recipient', 'verb', 'actor', 'read', 'created_at']
    list_filter = ['verb', 'read', 'created_at']
    search_fields = ['recipient__email', 'actor__email']
    raw_id_fields = ['recipient', 'actor', 'joke']
    readonly_fields = ['created_at']
