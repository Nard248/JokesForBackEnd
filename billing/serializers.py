from rest_framework import serializers

from billing.models import Plan, Subscription
from billing import entitlements


class PlanPublicSerializer(serializers.ModelSerializer):
    amount_display = serializers.CharField(read_only=True)

    class Meta:
        model = Plan
        fields = [
            'slug', 'name', 'description', 'interval', 'amount_cents',
            'currency', 'amount_display', 'features', 'limits', 'sort_order',
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


class EntitlementsSerializer(serializers.Serializer):
    plan = serializers.CharField()
    features = serializers.DictField(child=serializers.BooleanField())
    limits = serializers.DictField(child=serializers.IntegerField(allow_null=True))
