import json

from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from billing import entitlements
from billing.models import Plan, ProcessedStripeEvent, Subscription, UsageCounter


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = [
        'slug', 'name', 'amount_display', 'amount_cents', 'interval', 'is_active',
        'is_public', 'is_default', 'stripe_price_id', 'sort_order',
    ]
    list_editable = ['is_active', 'is_public', 'amount_cents', 'sort_order']
    readonly_fields = ['stripe_product_id', 'stripe_price_id']
    search_fields = ['slug', 'name']
    actions = ['push_to_stripe']

    def clean_features(self, features):
        unknown = set(features.keys()) - set(entitlements.KNOWN_FEATURES.keys())
        if unknown:
            raise ValidationError(
                f'Unknown feature key(s): {", ".join(sorted(unknown))}. '
                f'Known: {", ".join(sorted(entitlements.KNOWN_FEATURES.keys()))}.'
            )

    def clean_limits(self, limits):
        unknown = set(limits.keys()) - set(entitlements.KNOWN_LIMITS.keys())
        if unknown:
            raise ValidationError(
                f'Unknown limit key(s): {", ".join(sorted(unknown))}. '
                f'Known: {", ".join(sorted(entitlements.KNOWN_LIMITS.keys()))}.'
            )

    def save_model(self, request, obj, form, change):
        # Warn (not block) on unknown JSON keys
        for field, validator in [('features', self.clean_features), ('limits', self.clean_limits)]:
            val = getattr(obj, field, {}) or {}
            try:
                validator(val)
            except ValidationError as exc:
                self.message_user(request, f'Warning ({field}): {exc.message}', level=messages.WARNING)
        super().save_model(request, obj, form, change)

    @admin.action(description='Push to Stripe (idempotent — creates/updates Product+Price)')
    def push_to_stripe(self, request, queryset):
        from billing.stripe_gateway import BillingUnavailable, is_enabled, push_plan_to_stripe

        if not is_enabled():
            self.message_user(request, 'Stripe is not configured (STRIPE_SECRET_KEY unset).', level=messages.ERROR)
            return

        for plan in queryset:
            if not plan.amount_cents:
                self.message_user(
                    request,
                    f'Skipped "{plan.name}": no amount_cents set (free plan).',
                    level=messages.WARNING,
                )
                continue
            try:
                product_id, price_id = push_plan_to_stripe(plan)
                self.message_user(
                    request,
                    f'"{plan.name}" pushed: product={product_id}, price={price_id}',
                )
            except BillingUnavailable as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
            except Exception as exc:
                self.message_user(request, f'Error for "{plan.name}": {exc}', level=messages.ERROR)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['user', 'plan', 'status', 'current_period_end', 'cancel_at_period_end', 'updated_at']
    search_fields = ['user__email', 'stripe_customer_id', 'stripe_subscription_id']
    readonly_fields = [
        'user', 'plan', 'stripe_customer_id', 'stripe_subscription_id',
        'stripe_price_id', 'status', 'current_period_start', 'current_period_end',
        'cancel_at_period_end', 'updated_at',
    ]
    list_filter = ['status', 'cancel_at_period_end']


@admin.register(UsageCounter)
class UsageCounterAdmin(admin.ModelAdmin):
    list_display = ['user', 'key', 'period_key', 'count']
    search_fields = ['user__email', 'key']
    readonly_fields = ['user', 'key', 'period_key', 'count']
    list_filter = ['key']


@admin.register(ProcessedStripeEvent)
class ProcessedStripeEventAdmin(admin.ModelAdmin):
    list_display = ['event_id', 'event_type', 'created_at']
    search_fields = ['event_id', 'event_type']
    readonly_fields = ['event_id', 'event_type', 'created_at']
    list_filter = ['event_type']
