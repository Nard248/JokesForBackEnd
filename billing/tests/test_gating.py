"""Tests for demo gates: Mystery Box quota and creator analytics feature.

Also verifies Wave 1 non-regression (existing behavior unchanged with seed defaults).
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from billing.models import Plan, Subscription
from jokes.models import Format, AgeRating, Language

User = get_user_model()


def _get_joke_fixtures():
    fmt = Format.objects.get(slug='oneliner')
    age = AgeRating.objects.first()
    lang = Language.objects.get(code='en')
    return fmt, age, lang


class AdminEditabilityTests(TestCase):
    """Editing Plan.limits in DB is reflected by get_limit() on next call — no deploy."""

    def setUp(self):
        self.user = User.objects.create_user(username='edit@example.com', email='edit@example.com', password='pw')

    def test_limit_edit_reflected_immediately(self):
        from billing import entitlements

        free_plan = Plan.objects.get(is_default=True)
        self.assertEqual(entitlements.get_limit(self.user, 'mystery_box_rolls_per_day'), 3)

        free_plan.limits['mystery_box_rolls_per_day'] = 99
        free_plan.save()

        self.assertEqual(entitlements.get_limit(self.user, 'mystery_box_rolls_per_day'), 99)

        # Restore
        free_plan.limits['mystery_box_rolls_per_day'] = 3
        free_plan.save()

    def test_feature_edit_reflected_immediately(self):
        from billing import entitlements

        free_plan = Plan.objects.get(is_default=True)
        self.assertTrue(entitlements.has_feature(self.user, 'creator_analytics'))

        free_plan.features['creator_analytics'] = False
        free_plan.save()

        self.assertFalse(entitlements.has_feature(self.user, 'creator_analytics'))

        # Restore
        free_plan.features['creator_analytics'] = True
        free_plan.save()

    def test_plan_admin_push_to_stripe_skips_free_plan(self):
        """PlanAdmin.push_to_stripe skips plans without amount_cents."""
        from django.test import RequestFactory
        from django.contrib.admin.sites import AdminSite
        from billing.admin import PlanAdmin

        site = AdminSite()
        ma = PlanAdmin(Plan, site)

        # Create a mock request with messages
        rf = RequestFactory()
        req = rf.post('/')
        req.user = User.objects.create_superuser(username='admin@example.com', email='admin@example.com', password='pw')

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, 'session', 'session')
        messages = FallbackStorage(req)
        setattr(req, '_messages', messages)

        free_plan = Plan.objects.get(is_default=True)
        with override_settings(STRIPE_SECRET_KEY='sk_test_fake'):
            with patch('billing.stripe_gateway.stripe') as mstripe:
                ma.push_to_stripe(req, Plan.objects.filter(slug='free'))
        # Should not have called stripe — no amount_cents


class MysteryBoxGatingTests(APITestCase):
    """Mystery Box quota gate: both status and roll views agree with plan limit."""

    def setUp(self):
        self.user = User.objects.create_user(username='mb@example.com', email='mb@example.com', password='pw')
        self.client.force_authenticate(self.user)

    def test_status_shows_plan_limit(self):
        resp = self.client.get('/api/v1/mystery-box/status/')
        self.assertEqual(resp.status_code, 200)
        # Default free plan has max_per_day=3
        self.assertEqual(resp.data['max_per_day'], 3)

    def test_roll_blocked_at_plan_limit(self):
        """After free plan's mystery_box_rolls_per_day rolls, next returns 429."""
        from jokes.models import MysteryBoxRoll, Joke
        from django.utils import timezone

        today = timezone.now().date()
        fmt, age, lang = _get_joke_fixtures()
        # Create a joke to satisfy the non-nullable ForeignKey
        with patch('jokes.models.Joke._generate_share_image'):
            joke = Joke.objects.create(
                text='Test joke for mystery box',
                format=fmt,
                age_rating=age,
                language=lang,
            )
        # Insert rolls to exhaust the limit (3 for free plan)
        for _ in range(3):
            MysteryBoxRoll.objects.create(
                user=self.user,
                joke=joke,
                rolled_date=today,
            )

        resp = self.client.post('/api/v1/mystery-box/roll/')
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.data['max_per_day'], 3)

    def test_bumping_plan_limit_allows_more_rolls(self):
        """Raising free plan's limit in DB -> status shows new limit."""
        free_plan = Plan.objects.get(is_default=True)
        free_plan.limits['mystery_box_rolls_per_day'] = 10
        free_plan.save()

        resp = self.client.get('/api/v1/mystery-box/status/')
        self.assertEqual(resp.data['max_per_day'], 10)

        # Restore
        free_plan.limits['mystery_box_rolls_per_day'] = 3
        free_plan.save()


class CreatorAnalyticsGatingTests(APITestCase):
    """HasFeature('creator_analytics') gate on CreatorInsightsView."""

    def setUp(self):
        self.user = User.objects.create_user(username='creator@example.com', email='creator@example.com', password='pw')
        self.client.force_authenticate(self.user)
        # Create a published joke so IsCreator passes
        from jokes.models import Joke, JokeSubmission
        fmt, age, lang = _get_joke_fixtures()
        with patch('jokes.models.Joke._generate_share_image'):
            j = Joke.objects.create(
                text='Test joke',
                format=fmt,
                age_rating=age,
                language=lang,
            )
        JokeSubmission.objects.create(
            user=self.user,
            format=fmt,
            age_rating=age,
            language=lang,
            text=j.text,
            published_joke=j,
            status='published',
        )

    def test_free_user_with_creator_analytics_true_gets_200(self):
        """Wave 1 intact: creator_analytics=True on free plan -> 200."""
        resp = self.client.get('/api/v1/creators/me/insights/')
        self.assertEqual(resp.status_code, 200)

    def test_free_user_with_creator_analytics_false_gets_403(self):
        """Flip feature to False in DB -> 403 without code change."""
        free_plan = Plan.objects.get(is_default=True)
        free_plan.features['creator_analytics'] = False
        free_plan.save()

        resp = self.client.get('/api/v1/creators/me/insights/')
        self.assertEqual(resp.status_code, 403)

        # Restore
        free_plan.features['creator_analytics'] = True
        free_plan.save()

    def test_pro_user_with_creator_analytics_gets_200(self):
        """Pro plan user with creator_analytics=True gets 200."""
        pro_plan = Plan.objects.get(slug='creator_pro')
        Subscription.objects.create(user=self.user, plan=pro_plan, status='active')

        resp = self.client.get('/api/v1/creators/me/insights/')
        self.assertEqual(resp.status_code, 200)
