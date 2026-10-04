"""Money-boundary regressions for the creator subscription rollout."""
from types import SimpleNamespace
from unittest.mock import patch

import stripe
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from billing.models import Plan, Subscription
from billing.stripe_gateway import create_checkout_session, push_plan_to_stripe
from billing.webhooks import _plan_from_price_id, handle_event

User = get_user_model()


class CreatorPaymentBoundaryTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='creator-payments', password='pw')
        self.client.force_authenticate(self.user)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake', TIPS_ENABLED=False)
    @patch('billing.stripe_gateway.create_tip_checkout_session')
    def test_subscription_billing_does_not_enable_tips(self, checkout):
        response = self.client.post('/api/v1/tips/checkout/', {'amount_cents': 500})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'tips_unavailable')
        checkout.assert_not_called()

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake', STRIPE_WEBHOOK_SECRET='')
    @patch('billing.stripe_gateway.stripe.Webhook.construct_event')
    def test_missing_webhook_secret_fails_closed(self, construct_event):
        response = self.client.post('/api/v1/billing/webhook', {}, format='json')
        self.assertEqual(response.status_code, 503)
        construct_event.assert_not_called()

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake', CREATOR_CHECKOUT_ENABLED=True, STRIPE_WEBHOOK_SECRET='whsec_test')
    @patch('billing.stripe_gateway.stripe')
    def test_checkout_propagates_identity_to_subscription(self, gateway):
        plan = Plan.objects.get(slug='creator_pro')
        plan.stripe_price_id = 'price_pro'
        gateway.Customer.create.return_value = SimpleNamespace(id='cus_new')
        gateway.Subscription.list.return_value = stripe.StripeObject.construct_from({'data': [], 'has_more': False}, None)
        gateway.checkout.Session.create.return_value = stripe.StripeObject.construct_from({'id': 'cs_new', 'url': 'https://checkout.stripe.test/new'}, None)
        create_checkout_session(self.user, plan)
        self.assertEqual(
            gateway.checkout.Session.create.call_args.kwargs['subscription_data'],
            {'metadata': {'user_id': str(self.user.pk), 'plan_slug': 'creator_pro'}},
        )


class StripePriceIdentityTests(TestCase):
    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('billing.stripe_gateway.stripe')
    def test_same_amount_different_interval_creates_price(self, gateway):
        plan = Plan.objects.get(slug='creator_pro')
        plan.stripe_product_id = 'prod_creator'
        plan.stripe_price_id = 'price_month'
        plan.interval = 'year'
        gateway.Product.retrieve.return_value = SimpleNamespace(id='prod_creator')
        gateway.Price.retrieve.return_value = stripe.StripeObject.construct_from({
            'id': 'price_month', 'unit_amount': plan.amount_cents, 'currency': 'usd',
            'product': 'prod_creator', 'active': True,
            'recurring': {'interval': 'month', 'interval_count': 1},
        }, None)
        gateway.Price.create.return_value = SimpleNamespace(id='price_year')
        self.assertEqual(push_plan_to_stripe(plan), ('prod_creator', 'price_year'))
        self.assertEqual(gateway.Price.create.call_args.kwargs['recurring'], {'interval': 'year'})
        self.assertEqual(_plan_from_price_id('price_month'), plan)
        self.assertEqual(_plan_from_price_id('price_year'), plan)


class RealStripeSubscriptionPayloadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='stripe-payload', password='pw')
        self.plan = Plan.objects.get(slug='creator_pro')
        self.plan.stripe_price_id = 'price_creator'
        self.plan.save(update_fields=['stripe_price_id'])
        Subscription.objects.create(
            user=self.user, plan=Plan.objects.get(slug='free'), status='free',
            stripe_customer_id='cus_payload',
        )

    def test_dictionary_items_and_item_periods_resolve_real_payload(self):
        event = stripe.Event.construct_from({
            'id': 'evt_actual_shape', 'type': 'customer.subscription.updated',
            'data': {'object': {
                'id': 'sub_payload', 'customer': 'cus_payload', 'status': 'active',
                'metadata': {'user_id': str(self.user.pk)}, 'cancel_at_period_end': False,
                'items': {'data': [{
                    'price': {'id': 'price_creator'},
                    'current_period_start': 1790467200,
                    'current_period_end': 1793059200,
                }]},
            }},
        }, None)
        with patch('billing.stripe_gateway.retrieve_subscription', return_value=event.data.object):
            handle_event(event)
        subscription = Subscription.objects.get(user=self.user)
        self.assertEqual(subscription.plan, self.plan)
        self.assertEqual(int(subscription.current_period_end.timestamp()), 1793059200)

    def test_late_checkout_does_not_reactivate_canceled_subscription(self):
        subscription = Subscription.objects.get(user=self.user)
        subscription.stripe_subscription_id = 'sub_payload'
        subscription.status = 'canceled'
        subscription.save()
        event = stripe.Event.construct_from({
            'id': 'evt_late_checkout', 'type': 'checkout.session.completed',
            'data': {'object': {
                'id': 'cs_late', 'mode': 'subscription', 'payment_status': 'paid',
                'metadata': {'user_id': str(self.user.pk), 'plan_slug': self.plan.slug},
                'customer': 'cus_payload', 'subscription': 'sub_payload',
            }},
        }, None)
        current = stripe.StripeObject.construct_from({'id': 'sub_payload', 'customer': 'cus_payload', 'status': 'canceled', 'items': {'data': []}}, None)
        with patch('billing.stripe_gateway.retrieve_subscription', return_value=current):
            handle_event(event)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, 'canceled')


def stripe_object(data):
    return stripe.StripeObject.construct_from(data, None)


class AuthoritativeSubscriptionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='authoritative', password='pw')
        self.plan = Plan.objects.get(slug='creator_pro')
        self.plan.stripe_price_id = 'price_current'
        self.plan.save()
        self.sub = Subscription.objects.create(
            user=self.user, plan=self.plan, status='active',
            stripe_customer_id='cus_current', stripe_subscription_id='sub_current',
        )
        self.gateway = patch('billing.stripe_gateway.retrieve_subscription').start()
        self.addCleanup(patch.stopall)
        self.current = {
            'id': 'sub_current', 'customer': 'cus_current', 'status': 'active', 'created': 200,
            'metadata': {'user_id': str(self.user.pk)},
            'items': {'data': [{'price': {'id': 'price_current'}, 'current_period_end': 1793059200}]},
        }
        self.gateway.return_value = stripe_object(self.current)

    def event(self, kind, obj, event_id='evt_current'):
        return stripe.Event.construct_from({'id': event_id, 'type': kind, 'data': {'object': obj}}, None)

    def test_unpaid_checkout_does_not_grant_access(self):
        self.sub.status = 'free'
        self.sub.stripe_subscription_id = ''
        self.sub.save()
        self.gateway.return_value = stripe_object({**self.current, 'status': 'incomplete'})
        handle_event(self.event('checkout.session.completed', {
            'id': 'cs_unpaid', 'customer': 'cus_current', 'subscription': 'sub_current',
            'mode': 'subscription', 'payment_status': 'unpaid',
            'metadata': {'user_id': str(self.user.pk), 'plan_slug': 'creator_pro'},
        }))
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'incomplete')
        self.assertFalse(self.sub.is_entitled())

    def test_paid_failed_recovered_and_canceled_follow_current_state(self):
        for state in ['active', 'past_due', 'active', 'canceled']:
            with self.subTest(state=state):
                self.gateway.return_value = stripe_object({**self.current, 'status': state})
                # The incoming snapshot remains active throughout; only the
                # retrieved resource is allowed to determine entitlement.
                handle_event(self.event('customer.subscription.updated', self.current, f'evt_{state}_{self.gateway.call_count}'))
                self.sub.refresh_from_db()
                self.assertEqual(self.sub.status, state)
                self.assertEqual(self.sub.is_entitled(), state == 'active')
        self.assertEqual(self.sub.plan.slug, 'free')

    def test_stale_failure_invoice_does_not_revoke_recovered_subscription(self):
        handle_event(self.event('invoice.payment_failed', {
            'customer': 'cus_current',
            'parent': {'subscription_details': {'subscription': 'sub_current'}},
        }))
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'active')

    def test_one_off_invoice_cannot_mutate_subscription(self):
        handle_event(self.event('invoice.payment_failed', {'customer': 'cus_current'}))
        self.gateway.assert_not_called()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'active')

    def test_old_subscription_cancellation_and_paid_invoice_cannot_replace_new(self):
        self.gateway.return_value = stripe_object({**self.current, 'id': 'sub_old', 'created': 100, 'status': 'canceled'})
        handle_event(self.event('customer.subscription.deleted', {
            'id': 'sub_old', 'customer': 'cus_current', 'status': 'canceled',
        }, 'evt_old_cancel'))
        handle_event(self.event('invoice.paid', {
            'customer': 'cus_current', 'subscription': 'sub_old',
        }, 'evt_old_invoice'))
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'active')
        self.assertEqual(self.sub.stripe_subscription_id, 'sub_current')

    def test_distinct_live_subscription_cannot_overwrite_existing(self):
        old = stripe_object({**self.current, 'id': 'sub_old', 'created': 100})
        self.gateway.side_effect = lambda sid: old if sid == 'sub_old' else stripe_object(self.current)
        handle_event(self.event('customer.subscription.updated', {'id': 'sub_old', 'customer': 'cus_current'}))
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.stripe_subscription_id, 'sub_current')

    def test_unknown_price_cannot_inherit_metadata_entitlements(self):
        self.gateway.return_value = stripe_object({**self.current, 'items': {'data': [{'price': {'id': 'price_unknown'}}]}})
        handle_event(self.event('customer.subscription.updated', self.current))
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.plan.slug, 'free')
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.is_premium)

    def test_ownership_mismatch_rolls_back_event_claim(self):
        from billing.models import ProcessedStripeEvent
        self.gateway.return_value = stripe_object({**self.current, 'customer': 'cus_other'})
        with self.assertRaisesRegex(ValueError, 'ownership mismatch'):
            handle_event(self.event('customer.subscription.updated', self.current))
        self.assertFalse(ProcessedStripeEvent.objects.filter(event_id='evt_current').exists())

    def test_api_failure_is_retryable_and_successful_delivery_deduplicates(self):
        from billing.models import ProcessedStripeEvent
        event = self.event('customer.subscription.updated', self.current)
        self.gateway.side_effect = TimeoutError('simulated timeout')
        with self.assertRaises(TimeoutError):
            handle_event(event)
        self.assertFalse(ProcessedStripeEvent.objects.filter(event_id='evt_current').exists())
        self.gateway.side_effect = None
        handle_event(event)
        handle_event(event)
        self.assertEqual(self.gateway.call_count, 2)
        self.assertEqual(ProcessedStripeEvent.objects.filter(event_id='evt_current').count(), 1)


@override_settings(STRIPE_SECRET_KEY='sk_test_fake', CREATOR_CHECKOUT_ENABLED=True, STRIPE_WEBHOOK_SECRET='whsec_test')
class DurableCheckoutTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='durable-checkout', password='pw')
        self.client.force_authenticate(self.user)
        self.plan = Plan.objects.get(slug='creator_pro')
        self.plan.stripe_price_id = 'price_checkout'
        self.plan.save()
        self.gateway = patch('billing.stripe_gateway.stripe').start()
        self.addCleanup(patch.stopall)
        self.gateway.Customer.create.return_value = stripe_object({'id': 'cus_checkout'})
        self.gateway.Subscription.list.return_value = stripe_object({'data': [], 'has_more': False})
        self.session = stripe_object({'id': 'cs_durable', 'status': 'open', 'url': 'https://checkout.stripe.test/durable'})
        self.gateway.checkout.Session.create.return_value = self.session
        self.gateway.checkout.Session.retrieve.return_value = self.session
        self.gateway.billing_portal.Session.create.return_value = stripe_object({'url': 'https://billing.stripe.test/portal'})

    def test_repeated_checkout_reuses_open_session(self):
        self.assertEqual(create_checkout_session(self.user, self.plan).id, 'cs_durable')
        self.assertEqual(create_checkout_session(self.user, self.plan).id, 'cs_durable')
        self.gateway.checkout.Session.create.assert_called_once()
        self.gateway.Customer.create.assert_called_once()

    def test_uncertain_create_retries_with_identical_durable_key(self):
        from billing.models import SubscriptionCheckout
        self.gateway.checkout.Session.create.side_effect = [TimeoutError('lost response'), self.session]
        with self.assertRaises(TimeoutError):
            create_checkout_session(self.user, self.plan)
        self.assertEqual(SubscriptionCheckout.objects.get(user=self.user).stripe_session_id, '')
        create_checkout_session(self.user, self.plan)
        first, second = self.gateway.checkout.Session.create.call_args_list
        self.assertEqual(first.kwargs, second.kwargs)
        self.gateway.Customer.create.assert_called_once()

    def test_expired_checkout_gets_new_key_after_confirmation(self):
        create_checkout_session(self.user, self.plan)
        self.gateway.checkout.Session.retrieve.return_value = stripe_object({'id': 'cs_durable', 'status': 'expired'})
        create_checkout_session(self.user, self.plan)
        first, second = self.gateway.checkout.Session.create.call_args_list
        self.assertNotEqual(first.kwargs['idempotency_key'], second.kwargs['idempotency_key'])

    def test_remote_live_subscription_blocks_even_before_webhook(self):
        from billing.stripe_gateway import CheckoutConflict
        for state in ['active', 'trialing', 'past_due', 'incomplete', 'unpaid', 'paused']:
            with self.subTest(state=state):
                self.gateway.Subscription.list.return_value = stripe_object({'data': [{'id': 'sub_remote', 'status': state}], 'has_more': False})
                with self.assertRaises(CheckoutConflict):
                    create_checkout_session(self.user, self.plan)
        self.gateway.checkout.Session.create.assert_not_called()

    def test_local_incomplete_unpaid_paused_subscriptions_return_conflict(self):
        sub = Subscription.objects.create(user=self.user, plan=self.plan, stripe_customer_id='cus_checkout', stripe_subscription_id='sub_live')
        for state in ['incomplete', 'unpaid', 'paused']:
            sub.status = state
            sub.save()
            response = self.client.post('/api/v1/billing/checkout-session', {'plan_slug': 'creator_pro'})
            self.assertEqual(response.status_code, 409)
        self.gateway.checkout.Session.create.assert_not_called()

    @override_settings(CREATOR_CHECKOUT_ENABLED=False)
    def test_sales_gate_keeps_portal_usable(self):
        Subscription.objects.create(user=self.user, plan=self.plan, stripe_customer_id='cus_checkout')
        self.gateway.billing_portal.Session.create.return_value = stripe_object({'url': 'https://billing.stripe.test/portal'})
        response = self.client.post('/api/v1/billing/checkout-session', {'plan_slug': 'creator_pro'})
        self.assertEqual(response.status_code, 503)
        response = self.client.post('/api/v1/billing/portal-session')
        self.assertEqual(response.status_code, 200)
        self.gateway.checkout.Session.create.assert_not_called()


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections, connection
from django.test import TransactionTestCase


@override_settings(STRIPE_SECRET_KEY='sk_test_fake', CREATOR_CHECKOUT_ENABLED=True, STRIPE_WEBHOOK_SECRET='whsec_test')
class ConcurrentPaymentTests(TransactionTestCase):
    """Exercise PostgreSQL row locks with two real database connections."""

    serialized_rollback = True

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        # TransactionTestCase flushes migration-created catalog/taxonomy data.
        # Restore the original serialized baseline after this class as well as
        # before each test, so later classes and --keepdb runs retain the seeds.
        connection.creation.deserialize_db_from_string(connection._test_serialized_contents)

    def setUp(self):
        self.free, _ = Plan.objects.get_or_create(slug='free', defaults={'name': 'Free', 'is_default': True})
        self.plan, _ = Plan.objects.get_or_create(slug='creator_pro', defaults={'name': 'Pro'})
        self.plan.stripe_price_id = 'price_concurrent'
        self.plan.save()
        self.user = User.objects.create_user(username='parallel-checkout', password='pw')

    def parallel(self, callback):
        barrier = Barrier(2)

        def invoke():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return callback()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(invoke) for _ in range(2)]
            return [future.result(timeout=15) for future in futures]

    @patch('billing.stripe_gateway.stripe')
    def test_concurrent_checkout_creates_one_customer_and_one_session(self, gateway):
        gateway.Customer.create.return_value = stripe_object({'id': 'cus_concurrent'})
        gateway.Subscription.list.return_value = stripe_object({'data': [], 'has_more': False})
        session = stripe_object({'id': 'cs_concurrent', 'status': 'open', 'url': 'https://checkout.stripe.test/concurrent'})
        gateway.checkout.Session.create.return_value = session
        gateway.checkout.Session.retrieve.return_value = session
        result = self.parallel(lambda: create_checkout_session(self.user, self.plan).id)
        self.assertEqual(result, ['cs_concurrent', 'cs_concurrent'])
        gateway.Customer.create.assert_called_once()
        gateway.checkout.Session.create.assert_called_once()

    @patch('billing.stripe_gateway.retrieve_subscription')
    def test_concurrent_event_delivery_claims_once(self, retrieve):
        from billing.models import ProcessedStripeEvent
        Subscription.objects.create(user=self.user, plan=self.free, stripe_customer_id='cus_concurrent')
        current = stripe_object({
            'id': 'sub_concurrent', 'customer': 'cus_concurrent', 'status': 'active',
            'items': {'data': [{'price': {'id': 'price_concurrent'}}]},
        })
        retrieve.return_value = current
        event = stripe.Event.construct_from({
            'id': 'evt_concurrent', 'type': 'customer.subscription.updated', 'data': {'object': current},
        }, None)
        self.parallel(lambda: handle_event(event))
        retrieve.assert_called_once()
        self.assertEqual(ProcessedStripeEvent.objects.filter(event_id='evt_concurrent').count(), 1)
        self.assertEqual(Subscription.objects.get(user=self.user).status, 'active')


from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError


@override_settings(
    STRIPE_SECRET_KEY='sk_test_fake', STRIPE_WEBHOOK_SECRET='whsec_test',
    CREATOR_CHECKOUT_ENABLED=False, TIPS_ENABLED=False,
)
class SalesReadinessCommandTests(TestCase):
    @patch('billing.management.commands.check_sales_readiness._client')
    def test_read_only_check_validates_catalog_without_resource_mutations(self, client_factory):
        plan = Plan.objects.get(slug='creator_pro')
        plan.stripe_product_id = 'prod_not_printed'
        plan.stripe_price_id = 'price_not_printed'
        plan.save()
        gateway = client_factory.return_value
        gateway.Account.retrieve.return_value = stripe_object({
            'id': 'acct_not_printed', 'country': 'US', 'details_submitted': True,
            'charges_enabled': True, 'payouts_enabled': True,
        })
        gateway.Price.retrieve.return_value = stripe_object({
            'active': True, 'livemode': False, 'product': plan.stripe_product_id,
            'unit_amount': plan.amount_cents, 'currency': plan.currency,
            'recurring': {'interval': plan.interval, 'interval_count': 1},
        })
        gateway.Product.retrieve.return_value = stripe_object({'active': True})
        output = StringIO()
        call_command('check_sales_readiness', stdout=output)
        self.assertIn('Read-only checks passed', output.getvalue())
        self.assertNotIn('not_printed', output.getvalue())
        self.assertNotIn('sk_test_fake', output.getvalue())
        self.assertEqual([call[0] for call in gateway.mock_calls], [
            'Account.retrieve', 'Price.retrieve', 'Product.retrieve',
        ])

    @patch('billing.management.commands.check_sales_readiness._client')
    def test_incomplete_merchant_fails(self, client_factory):
        client_factory.return_value.Account.retrieve.return_value = stripe_object({
            'country': 'US', 'details_submitted': False, 'charges_enabled': False, 'payouts_enabled': False,
        })
        with self.assertRaises(CommandError):
            call_command('check_sales_readiness', stdout=StringIO())

    @patch('billing.management.commands.check_sales_readiness._client')
    def test_live_check_rejects_test_key_before_network(self, client_factory):
        with self.assertRaisesRegex(CommandError, 'key mode is wrong'):
            call_command('check_sales_readiness', live=True, stdout=StringIO())
        client_factory.assert_not_called()


class PublicPurchaseAvailabilityTests(APITestCase):
    @override_settings(CREATOR_CHECKOUT_ENABLED=False, STRIPE_SECRET_KEY='sk_test_fake')
    def test_disabled_sales_exposed_on_public_plan(self):
        pro = Plan.objects.get(slug='creator_pro')
        pro.stripe_price_id = 'price_configured'
        pro.save()
        result = self.client.get('/api/v1/billing/plans')
        self.assertTrue(all(plan['purchase_available'] is False for plan in result.data))

    @override_settings(CREATOR_CHECKOUT_ENABLED=True, STRIPE_SECRET_KEY='sk_test_fake', STRIPE_WEBHOOK_SECRET='whsec_test')
    def test_available_only_for_configured_paid_plan(self):
        pro = Plan.objects.get(slug='creator_pro')
        pro.stripe_price_id = 'price_configured'
        pro.save()
        result = self.client.get('/api/v1/billing/plans')
        values = {plan['slug']: plan['purchase_available'] for plan in result.data}
        self.assertEqual(values, {'free': False, 'creator_pro': True})
