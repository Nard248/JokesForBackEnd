from rest_framework import serializers

from billing.models import Plan, Subscription, Tip
from billing.stripe_gateway import is_checkout_enabled


class PlanPublicSerializer(serializers.ModelSerializer):
    amount_display = serializers.CharField(read_only=True)
    purchase_available = serializers.SerializerMethodField()

    def get_purchase_available(self, plan):
        return bool(
            is_checkout_enabled() and plan.is_active and plan.is_public
            and not plan.is_default and plan.amount_cents and plan.stripe_price_id
        )

    class Meta:
        model = Plan
        fields = [
            'slug', 'name', 'description', 'interval', 'amount_cents',
            'currency', 'amount_display', 'features', 'limits', 'sort_order', 'purchase_available',
        ]


class MySubscriptionSerializer(serializers.ModelSerializer):
    plan_slug = serializers.CharField(source='plan.slug', read_only=True)
    plan_name = serializers.CharField(source='plan.name', read_only=True)

    class Meta:
        model = Subscription
        fields = [
            'plan_slug', 'plan_name', 'status', 'current_period_end',
            'cancel_at_period_end', 'stripe_customer_id',
        ]


class TipSerializer(serializers.ModelSerializer):
    """Sent-tip history row for GET /api/v1/users/me/tips/."""
    creator_name = serializers.SerializerMethodField()

    class Meta:
        model = Tip
        fields = [
            'id', 'creator', 'creator_name', 'joke', 'amount_cents', 'currency',
            'status', 'created_at', 'completed_at',
        ]

    def get_creator_name(self, obj):
        from jokes.identity import public_display_name
        return public_display_name(obj.creator)


class EntitlementsSerializer(serializers.Serializer):
    plan = serializers.CharField()
    features = serializers.DictField(child=serializers.BooleanField())
    limits = serializers.DictField(child=serializers.IntegerField(allow_null=True))
