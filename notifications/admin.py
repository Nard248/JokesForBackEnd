from django.contrib import admin

from .models import EmailMessageLog, EmailVerification


@admin.register(EmailMessageLog)
class EmailMessageLogAdmin(admin.ModelAdmin):
    list_display = ['to_email', 'template_name', 'status', 'created_at', 'sent_at']
    list_filter = ['status', 'template_name', 'created_at']
    search_fields = ['to_email', 'subject', 'provider_message_id']
    readonly_fields = [f.name for f in EmailMessageLog._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'expires_at', 'consumed_at', 'attempts', 'created_at']
    list_filter = ['created_at', 'expires_at']
    search_fields = ['user__email']
    readonly_fields = [f.name for f in EmailVerification._meta.fields]

    def has_add_permission(self, request):
        return False
