"""Reading remains free regardless of legacy billing state; safety still applies."""
from datetime import date
from importlib import import_module
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import connection
from django.utils import timezone
from rest_framework.test import APITestCase

from billing import entitlements
from billing.models import Plan, Subscription
from jokes.models import (
    AgeRating,
    DailyJoke,
    Format,
    Joke,
    JokeView,
    Language,
    MysteryBoxRoll,
    UserBlock,
)

User = get_user_model()


class FreeAudienceTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reader = User.objects.create_user(username='free-audience', password='pw')
        cls.creator = User.objects.create_user(username='free-audience-creator', password='pw')
        with patch('jokes.models.Joke._generate_share_image'):
            cls.jokes = [
                Joke.objects.create(
                    text=f'Setup {i}. Punchline {i}.', setup=f'Setup {i}.',
                    punchline=f'Punchline {i}.', format=Format.objects.get(slug='setup'),
                    age_rating=AgeRating.objects.first(), language=Language.objects.get(code='en'),
                    creator=cls.creator,
                )
                for i in range(13)
            ]
        JokeView.objects.bulk_create([
            JokeView(user=cls.reader, joke=joke, viewed_date=timezone.now().date())
            for joke in cls.jokes[:12]
        ])

    def setUp(self):
        self.client.force_authenticate(self.reader)

    def test_stale_custom_plan_cannot_withhold_thirteenth_joke(self):
        plan = Plan.objects.create(
            slug='legacy-custom-reader', name='Legacy',
            limits={'free_joke_reads_per_day': 1},
        )
        Subscription.objects.create(user=self.reader, plan=plan, status='active')
        target = self.jokes[-1]
        response = self.client.get(f'/api/v1/jokes/{target.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['is_locked'])
        self.assertEqual(response.data['text'], target.text)
        self.assertEqual(response.data['punchline'], target.punchline)
        self.assertTrue(JokeView.objects.filter(user=self.reader, joke=target).exists())

    def test_lapsed_subscriptions_still_get_free_full_content(self):
        free = Plan.objects.get(is_default=True)
        free.limits['free_joke_reads_per_day'] = 1
        free.save(update_fields=['limits'])
        sub = Subscription.objects.create(
            user=self.reader, plan=Plan.objects.get(slug='creator_pro'), status='canceled',
        )
        for subscription_status in ('canceled', 'past_due', 'incomplete_expired'):
            with self.subTest(status=subscription_status):
                sub.status = subscription_status
                sub.save(update_fields=['status'])
                self.reader.refresh_from_db()
                response = self.client.get(f'/api/v1/jokes/{self.jokes[-1].pk}/')
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.data['is_locked'])
                self.assertEqual(response.data['punchline'], self.jokes[-1].punchline)

    def test_legacy_cookie_cannot_lock_anonymous_content(self):
        self.client.force_authenticate(None)
        self.client.cookies['jf_anon_reads'] = signing.dumps({
            'date': timezone.now().date().isoformat(),
            'ids': [j.pk for j in self.jokes[:10]],
        }, salt='jokes.paywall.anon')
        response = self.client.get(f'/api/v1/jokes/{self.jokes[-1].pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['is_locked'])
        self.assertEqual(response.data['punchline'], self.jokes[-1].punchline)
        self.assertNotIn('jf_anon_reads', response.cookies)

    def test_anonymous_reveal_retains_unlimited_contract_without_cookie(self):
        self.client.force_authenticate(None)
        response = self.client.post(f'/api/v1/jokes/{self.jokes[-1].pk}/reveal/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['limit'])
        self.assertIsNone(response.data['remaining'])
        self.assertFalse(response.data['over'])
        self.assertEqual(response.data['used'], 0)
        self.assertNotIn('jf_anon_reads', response.cookies)

    def test_daily_reads_keeps_legacy_unlimited_shape(self):
        response = self.client.get('/api/v1/jokes/daily-reads/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {'limit', 'remaining', 'used', 'over', 'reset_at'})
        self.assertIsNone(response.data['limit'])
        self.assertIsNone(response.data['remaining'])
        self.assertFalse(response.data['over'])
        self.assertEqual(response.data['used'], 0)

    def test_reader_entitlements_ignore_stale_plan_json_and_default_argument(self):
        free = Plan.objects.get(is_default=True)
        keys = ('free_joke_reads_per_day', 'mystery_box_rolls_per_day',
                'daily_joke_history_days', 'daily_jokes_per_day')
        free.limits.update(dict.fromkeys(keys, 1))
        free.save(update_fields=['limits'])
        for key in keys:
            with self.subTest(key=key):
                self.assertIsNone(entitlements.get_limit(self.reader, key, default=3))
        response = self.client.get('/api/v1/billing/entitlements')
        for key in keys:
            self.assertIsNone(response.data['limits'][key])

    def test_mystery_box_ignores_legacy_quota_and_retains_usage(self):
        MysteryBoxRoll.objects.bulk_create([
            MysteryBoxRoll(user=self.reader, joke=joke, rolled_date=timezone.now().date())
            for joke in self.jokes[:12]
        ])
        response = self.client.get('/api/v1/mystery-box/status/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['rolls_used_today'], 12)
        self.assertIsNone(response.data['max_per_day'])
        self.assertIsNone(response.data['rolls_remaining_today'])
        response = self.client.post('/api/v1/mystery-box/roll/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['rolls_remaining_today'])
        self.assertEqual(MysteryBoxRoll.objects.filter(user=self.reader).count(), 13)

    def test_history_retains_old_deliveries_despite_stale_plan_window(self):
        free = Plan.objects.get(is_default=True)
        free.limits['daily_joke_history_days'] = 1
        free.save(update_fields=['limits'])
        DailyJoke.objects.create(user=self.reader, joke=self.jokes[0], date=date(2020, 1, 1))
        response = self.client.get('/api/v1/daily-jokes/history/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['date'] for row in response.data], ['2020-01-01'])

    def test_free_viewing_preserves_minor_and_anonymous_content_tiers(self):
        for tier in ('tier_2', 'tier_3'):
            Joke.objects.filter(pk=self.jokes[-1].pk).update(content_tier=tier)
            for viewer in (None, self.reader):
                with self.subTest(tier=tier, viewer=viewer):
                    self.client.force_authenticate(viewer)
                    response = self.client.get(f'/api/v1/jokes/{self.jokes[-1].pk}/')
                    self.assertEqual(response.status_code, 404)

    def test_free_viewing_preserves_block_and_takedown(self):
        target = self.jokes[-1]
        block = UserBlock.objects.create(blocker=self.reader, blocked=self.creator)
        self.assertEqual(self.client.get(f'/api/v1/jokes/{target.pk}/').status_code, 404)
        block.delete()
        Joke.objects.filter(pk=target.pk).update(is_removed=True)
        self.assertEqual(self.client.get(f'/api/v1/jokes/{target.pk}/').status_code, 404)


class RetiredReaderPlanTests(APITestCase):
    def test_supporter_remains_stored_but_is_not_for_sale(self):
        plan = Plan.objects.get(slug='supporter')
        self.assertFalse(plan.is_active)
        self.assertFalse(plan.is_public)
        response = self.client.get('/api/v1/billing/plans')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('supporter', [row['slug'] for row in response.data])

    def test_catalog_migration_preserves_existing_contracts_and_custom_creator_limits(self):
        plan = Plan.objects.get(slug='supporter')
        plan.limits = {'free_joke_reads_per_day': 10, 'submissions_per_day': 17}
        plan.features = {'creator_analytics': True, 'custom_tool': True}
        plan.stripe_price_id = 'price_existing_supporter'
        plan.stripe_product_id = 'prod_existing_supporter'
        plan.save()
        reader = User.objects.create_user(username='legacy-contract', password='pw')
        sub = Subscription.objects.create(
            user=reader, plan=plan, status='active',
            stripe_customer_id='cus_existing', stripe_subscription_id='sub_existing',
            stripe_price_id='price_existing_supporter',
        )
        migrate = import_module('billing.migrations.0005_free_audience').free_audience
        editor = connection.schema_editor()
        migrate(apps, editor)
        migrate(apps, editor)  # Safe to retry without replacing financial records.
        plan.refresh_from_db()
        sub.refresh_from_db()
        self.assertEqual(plan.amount_cents, 500)
        self.assertEqual(plan.stripe_price_id, 'price_existing_supporter')
        self.assertEqual(plan.stripe_product_id, 'prod_existing_supporter')
        self.assertEqual(plan.features, {'creator_analytics': True, 'custom_tool': True})
        self.assertEqual(plan.limits['submissions_per_day'], 17)
        self.assertIsNone(plan.limits['free_joke_reads_per_day'])
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan_id, plan.pk)
        self.assertEqual(sub.stripe_customer_id, 'cus_existing')
        self.assertEqual(sub.stripe_subscription_id, 'sub_existing')
