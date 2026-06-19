"""Tests for the entitlement resolver and model seed."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from billing import entitlements
from billing.models import Plan, Subscription

User = get_user_model()


class PlanSeedTests(TestCase):
    """Data migration seeds exactly the expected plans."""

    def test_exactly_one_default_plan(self):
        count = Plan.objects.filter(is_default=True).count()
        self.assertEqual(count, 1)

    def test_free_plan_exists_and_is_default(self):
        plan = Plan.objects.get(slug='free')
        self.assertTrue(plan.is_default)
        self.assertIsNone(plan.amount_cents)

    def test_supporter_plan_exists(self):
        plan = Plan.objects.get(slug='supporter')
        self.assertFalse(plan.is_default)
        self.assertEqual(plan.amount_cents, 500)

    def test_creator_pro_plan_exists(self):
        plan = Plan.objects.get(slug='creator_pro')
        self.assertEqual(plan.amount_cents, 1500)


class SubscriptionEntitledTests(TestCase):
    """Subscription.is_entitled() returns True for active/trialing only."""

    def setUp(self):
        self.user = User.objects.create_user(username='sub@example.com', email='sub@example.com', password='pw')
        self.free_plan = Plan.objects.get(is_default=True)

    def _make_sub(self, status):
        return Subscription(user=self.user, plan=self.free_plan, status=status)

    def test_active_is_entitled(self):
        self.assertTrue(self._make_sub('active').is_entitled())

    def test_trialing_is_entitled(self):
        self.assertTrue(self._make_sub('trialing').is_entitled())

    def test_canceled_not_entitled(self):
        self.assertFalse(self._make_sub('canceled').is_entitled())

    def test_past_due_not_entitled(self):
        self.assertFalse(self._make_sub('past_due').is_entitled())


class EffectivePlanTests(TestCase):
    """effective_plan() resolves correctly."""

    def setUp(self):
        self.user = User.objects.create_user(username='ep@example.com', email='ep@example.com', password='pw')
        self.free_plan = Plan.objects.get(is_default=True)
        self.pro_plan = Plan.objects.get(slug='creator_pro')

    def test_no_sub_returns_free_plan(self):
        plan = entitlements.effective_plan(self.user)
        self.assertEqual(plan.slug, 'free')

    def test_active_sub_returns_pro_plan(self):
        Subscription.objects.create(user=self.user, plan=self.pro_plan, status='active')
        plan = entitlements.effective_plan(self.user)
        self.assertEqual(plan.slug, 'creator_pro')

    def test_canceled_sub_returns_free_plan(self):
        Subscription.objects.create(user=self.user, plan=self.pro_plan, status='canceled')
        plan = entitlements.effective_plan(self.user)
        self.assertEqual(plan.slug, 'free')

    def test_anon_user_returns_free_plan(self):
        from django.contrib.auth.models import AnonymousUser
        plan = entitlements.effective_plan(AnonymousUser())
        self.assertEqual(plan.slug, 'free')

    def test_trialing_sub_returns_plan(self):
        Subscription.objects.create(user=self.user, plan=self.pro_plan, status='trialing')
        plan = entitlements.effective_plan(self.user)
        self.assertEqual(plan.slug, 'creator_pro')


class HasFeatureTests(TestCase):
    """has_feature() resolves correctly."""

    def setUp(self):
        self.user = User.objects.create_user(username='feat@example.com', email='feat@example.com', password='pw')
        self.pro_plan = Plan.objects.get(slug='creator_pro')

    def test_free_user_creator_analytics_true_from_seed(self):
        # Seed sets creator_analytics=True on free plan
        self.assertTrue(entitlements.has_feature(self.user, 'creator_analytics'))

    def test_free_user_daily_joke_preview_false(self):
        self.assertFalse(entitlements.has_feature(self.user, 'daily_joke_preview'))

    def test_pro_user_daily_joke_preview_true(self):
        Subscription.objects.create(user=self.user, plan=self.pro_plan, status='active')
        self.assertTrue(entitlements.has_feature(self.user, 'daily_joke_preview'))

    def test_unknown_feature_key_returns_false(self):
        result = entitlements.has_feature(self.user, 'nonexistent_feature')
        self.assertFalse(result)


class GetLimitTests(TestCase):
    """get_limit() resolves correctly."""

    def setUp(self):
        self.user = User.objects.create_user(username='limit@example.com', email='limit@example.com', password='pw')
        self.pro_plan = Plan.objects.get(slug='creator_pro')

    def test_free_mystery_box_limit_is_3(self):
        self.assertEqual(entitlements.get_limit(self.user, 'mystery_box_rolls_per_day'), 3)

    def test_pro_mystery_box_limit_is_20(self):
        Subscription.objects.create(user=self.user, plan=self.pro_plan, status='active')
        self.assertEqual(entitlements.get_limit(self.user, 'mystery_box_rolls_per_day'), 20)

    def test_unknown_limit_uses_default_param(self):
        result = entitlements.get_limit(self.user, 'unknown_key', default=99)
        self.assertEqual(result, 99)

    def test_plan_limit_overrides_registry(self):
        # Bump the free plan's mystery_box limit in DB -> reflected immediately
        free_plan = Plan.objects.get(is_default=True)
        free_plan.limits['mystery_box_rolls_per_day'] = 10
        free_plan.save()
        self.assertEqual(entitlements.get_limit(self.user, 'mystery_box_rolls_per_day'), 10)
        # Restore
        free_plan.limits['mystery_box_rolls_per_day'] = 3
        free_plan.save()
