from rest_framework import serializers

from billing.models import Plan, Subscription, Tip


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
