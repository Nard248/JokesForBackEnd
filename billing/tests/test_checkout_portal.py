"""Tests for checkout/portal endpoints and dormant mode."""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

User = get_user_model()


class DormantBillingTests(APITestCase):
    """With no STRIPE_SECRET_KEY, checkout and portal return 503."""

    def setUp(self):
        self.user = User.objects.create_user(username='dormant@example.com', email='dormant@example.com', password='pw')
        self.client.force_authenticate(self.user)

    @override_settings(STRIPE_SECRET_KEY='')
    def test_checkout_dormant_returns_503_when_no_keys(self):
        resp = self.client.post('/api/v1/billing/checkout-session', {'plan_slug': 'creator_pro'})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data['code'], 'billing_unavailable')

    @override_settings(STRIPE_SECRET_KEY='')
    def test_portal_dormant_returns_503_when_no_keys(self):
        resp = self.client.post('/api/v1/billing/portal-session')
        self.assertEqual(resp.status_code, 503)

    @override_settings(STRIPE_SECRET_KEY='')
    def test_webhook_dormant_returns_200_noop(self):
        resp = self.client.post(
            '/api/v1/billing/webhook',
            data=b'{}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)


class CheckoutTests(APITestCase):
    """Checkout session with mocked Stripe."""

    def setUp(self):
        self.user = User.objects.create_user(username='checkout@example.com', email='checkout@example.com', password='pw')
        self.client.force_authenticate(self.user)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('billing.stripe_gateway.stripe')
    def test_checkout_returns_session_url(self, mstripe):
        from billing.models import Plan
        # Give creator_pro a fake price_id so the 422 guard doesn't fire
        pro = Plan.objects.get(slug='creator_pro')
        pro.stripe_price_id = 'price_fake_pro'
        pro.save()

        mstripe.api_key = ''
        mstripe.api_version = ''
        mock_session = MagicMock()
        mock_session.url = 'https://stripe.test/cs_test_123'
        mstripe.checkout.Session.create.return_value = mock_session
        mock_customer = MagicMock()
        mock_customer.id = 'cus_test_123'
        mstripe.Customer.create.return_value = mock_customer

        resp = self.client.post('/api/v1/billing/checkout-session', {'plan_slug': 'creator_pro'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['url'], 'https://stripe.test/cs_test_123')

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    def test_checkout_rejects_plan_without_price_id(self):
        # Free plan has no stripe_price_id
        resp = self.client.post('/api/v1/billing/checkout-session', {'plan_slug': 'free'})
        self.assertEqual(resp.status_code, 422)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    def test_checkout_unknown_plan_404(self):
        resp = self.client.post('/api/v1/billing/checkout-session', {'plan_slug': 'nonexistent'})
        self.assertEqual(resp.status_code, 404)

    def test_checkout_unauthenticated_401(self):
        self.client.force_authenticate(None)
        resp = self.client.post('/api/v1/billing/checkout-session', {'plan_slug': 'creator_pro'})
        self.assertEqual(resp.status_code, 401)


class PortalTests(APITestCase):
    """Portal session with mocked Stripe."""

    def setUp(self):
        self.user = User.objects.create_user(username='portal@example.com', email='portal@example.com', password='pw')
        self.client.force_authenticate(self.user)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('billing.stripe_gateway.stripe')
    def test_portal_returns_url(self, mstripe):
        from billing.models import Plan, Subscription
        free_plan = Plan.objects.get(is_default=True)
        Subscription.objects.create(
            user=self.user,
            plan=free_plan,
            stripe_customer_id='cus_test_456',
            status='active',
        )
        mock_portal = MagicMock()
        mock_portal.url = 'https://billing.stripe.com/p/session/test'
        mstripe.billing_portal.Session.create.return_value = mock_portal

        resp = self.client.post('/api/v1/billing/portal-session')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['url'], 'https://billing.stripe.com/p/session/test')

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    def test_portal_no_subscription_404(self):
        resp = self.client.post('/api/v1/billing/portal-session')
        self.assertEqual(resp.status_code, 404)


class MySubscriptionTests(APITestCase):
    """my-subscription endpoint."""

    def setUp(self):
        self.user = User.objects.create_user(username='mysub@example.com', email='mysub@example.com', password='pw')
        self.client.force_authenticate(self.user)

    def test_my_subscription_no_sub_returns_free(self):
        resp = self.client.get('/api/v1/billing/my-subscription')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['plan_slug'], 'free')
        self.assertEqual(resp.data['status'], 'free')

    def test_my_subscription_with_active_sub(self):
        from billing.models import Plan, Subscription
        plan = Plan.objects.get(slug='creator_pro')
        Subscription.objects.create(user=self.user, plan=plan, status='active')
        resp = self.client.get('/api/v1/billing/my-subscription')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['plan_slug'], 'creator_pro')
        self.assertEqual(resp.data['status'], 'active')


class EntitlementsViewTests(APITestCase):
    """entitlements endpoint."""

    def setUp(self):
        self.user = User.objects.create_user(username='ent@example.com', email='ent@example.com', password='pw')
        self.client.force_authenticate(self.user)

    def test_entitlements_returns_shape(self):
        resp = self.client.get('/api/v1/billing/entitlements')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('plan', resp.data)
        self.assertIn('features', resp.data)
        self.assertIn('limits', resp.data)
        self.assertIn('creator_analytics', resp.data['features'])
        self.assertIn('mystery_box_rolls_per_day', resp.data['limits'])

    def test_entitlements_free_user_plan_is_free(self):
        resp = self.client.get('/api/v1/billing/entitlements')
        self.assertEqual(resp.data['plan'], 'free')


class PlansViewTests(APITestCase):
    """plans endpoint — public."""

    def test_plans_public_returns_active_public_plans(self):
        resp = self.client.get('/api/v1/billing/plans')
        self.assertEqual(resp.status_code, 200)
        slugs = [p['slug'] for p in resp.data]
        self.assertIn('free', slugs)
        self.assertIn('creator_pro', slugs)
        self.assertIn('supporter', slugs)
