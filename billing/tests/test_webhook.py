"""Tests for Stripe webhook: signature verify, idempotency, UPSERT handlers."""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from billing.models import Plan, ProcessedStripeEvent, Subscription, Tip

User = get_user_model()


def _make_stripe_event(event_type: str, obj_data: dict, event_id='evt_test_001') -> MagicMock:
    """Build a minimal fake Stripe event object."""
    event = MagicMock()
    event.id = event_id
    event.type = event_type
    obj = MagicMock()
    for k, v in obj_data.items():
        setattr(obj, k, v)
    obj.metadata = obj_data.get('metadata', {})
    event.data = MagicMock()
    event.data.object = obj
    return event


class WebhookSignatureTests(APITestCase):
    """Bad signature -> 400; valid -> 200."""

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake', STRIPE_WEBHOOK_SECRET='whsec_test')
    @patch('billing.stripe_gateway.stripe')
    def test_bad_signature_returns_400(self, mstripe):
        import stripe as _stripe
        mstripe.Webhook.construct_event.side_effect = _stripe.error.SignatureVerificationError(
            'bad sig', 'sig_header'
        )
        resp = self.client.post(
            '/api/v1/billing/webhook',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='bad_sig',
        )
        self.assertEqual(resp.status_code, 400)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake', STRIPE_WEBHOOK_SECRET='whsec_test')
    @patch('billing.stripe_gateway.stripe')
    def test_valid_unknown_event_returns_200(self, mstripe):
        fake_event = _make_stripe_event('some.unknown.event', {})
        mstripe.Webhook.construct_event.return_value = fake_event
        resp = self.client.post(
            '/api/v1/billing/webhook',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=1,v1=valid',
        )
        self.assertEqual(resp.status_code, 200)


class WebhookIdempotencyTests(TestCase):
    """Same event.id twice -> second call is a no-op (no second UPSERT)."""

    def setUp(self):
        self.user = User.objects.create_user(username='idem@example.com', email='idem@example.com', password='pw')
        self.free_plan = Plan.objects.get(is_default=True)

    def test_duplicate_event_id_no_second_upsert(self):
        from billing.webhooks import handle_event

        ProcessedStripeEvent.objects.create(event_id='evt_dup_001', event_type='checkout.session.completed')
        pre_count = Subscription.objects.filter(user=self.user).count()

        event = _make_stripe_event('checkout.session.completed', {'metadata': {'user_id': str(self.user.pk)}}, 'evt_dup_001')
        handle_event(event)

        post_count = Subscription.objects.filter(user=self.user).count()
        self.assertEqual(pre_count, post_count, 'Duplicate event should not create a Subscription')


class WebhookCheckoutCompletedTests(TestCase):
    """checkout.session.completed links customer + sub to user."""

    def setUp(self):
        self.user = User.objects.create_user(username='chk@example.com', email='chk@example.com', password='pw')
        self.free_plan = Plan.objects.get(is_default=True)
        self.pro_plan = Plan.objects.get(slug='creator_pro')

    def test_checkout_completed_creates_subscription(self):
        from billing.webhooks import handle_event

        event = _make_stripe_event('checkout.session.completed', {
            'metadata': {'user_id': str(self.user.pk), 'plan_slug': 'creator_pro'},
            'customer': 'cus_webhook_001',
            'subscription': 'sub_webhook_001',
            'client_reference_id': str(self.user.pk),
        })

        handle_event(event)

        sub = Subscription.objects.get(user=self.user)
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.stripe_customer_id, 'cus_webhook_001')
        self.assertEqual(sub.plan.slug, 'creator_pro')

        # Denormalized is_premium cache must be synced (regression: the sync
        # used the wrong reverse accessor and silently no-op'd).
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.is_premium)

        evt = ProcessedStripeEvent.objects.get(event_id=event.id)
        self.assertEqual(evt.event_type, 'checkout.session.completed')


class WebhookSubscriptionEventTests(TestCase):
    """customer.subscription.* events UPSERT correctly."""

    def setUp(self):
        self.user = User.objects.create_user(username='subevent@example.com', email='subevent@example.com', password='pw')
        self.free_plan = Plan.objects.get(is_default=True)
        self.pro_plan = Plan.objects.get(slug='creator_pro')
        # Pre-create a Subscription so customer_id lookup works
        Subscription.objects.create(
            user=self.user,
            plan=self.free_plan,
            stripe_customer_id='cus_sub_001',
            status='free',
        )

    def _make_sub_obj(self, status, price_id='', event_id='evt_sub_001'):
        items_mock = MagicMock()
        price_mock = MagicMock()
        price_mock.id = price_id
        item_mock = MagicMock()
        item_mock.price = price_mock
        items_mock.data = [item_mock]

        return _make_stripe_event(
            'customer.subscription.created',
            {
                'id': 'sub_stripe_001',
                'customer': 'cus_sub_001',
                'status': status,
                'current_period_start': 1700000000,
                'current_period_end': 1702592000,
                'cancel_at_period_end': False,
                'items': items_mock,
            },
            event_id=event_id,
        )

    def test_subscription_created_sets_status(self):
        from billing.webhooks import handle_event

        pro_price_id = self.pro_plan.stripe_price_id or ''
        event = self._make_sub_obj('active', pro_price_id)
        handle_event(event)

        sub = Subscription.objects.get(user=self.user)
        self.assertEqual(sub.status, 'active')

    def test_subscription_deleted_downgrades_to_free(self):
        from billing.webhooks import handle_event

        event = _make_stripe_event('customer.subscription.deleted', {
            'id': 'sub_stripe_001',
            'customer': 'cus_sub_001',
            'status': 'canceled',
        }, event_id='evt_del_001')
        handle_event(event)

        sub = Subscription.objects.get(user=self.user)
        self.assertEqual(sub.status, 'canceled')
        self.assertEqual(sub.plan.slug, 'free')

    def test_subscription_updated_resolves_plan_from_price_id(self):
        from billing.webhooks import handle_event

        # Set a real price_id on creator_pro so the resolver can match it
        self.pro_plan.stripe_price_id = 'price_pro_001'
        self.pro_plan.save()

        items_mock = MagicMock()
        price_mock = MagicMock()
        price_mock.id = 'price_pro_001'
        item_mock = MagicMock()
        item_mock.price = price_mock
        items_mock.data = [item_mock]

        event = _make_stripe_event('customer.subscription.updated', {
            'id': 'sub_stripe_001',
            'customer': 'cus_sub_001',
            'status': 'active',
            'current_period_start': 1700000000,
            'current_period_end': 1702592000,
            'cancel_at_period_end': False,
            'items': items_mock,
        }, event_id='evt_upd_001')
        handle_event(event)

        sub = Subscription.objects.get(user=self.user)
        self.assertEqual(sub.plan.slug, 'creator_pro')


class WebhookTipCompletedTests(TestCase):
    """checkout.session.completed with tip metadata marks the Tip succeeded.

    Creator-Tips-Wave Task 2. Idempotency is security-critical here (unlike
    the subscription UPSERT, re-running this handler is NOT naturally
    idempotent — stamping completed_at twice would be a real bug), so this
    covers both the outer event.id dedup AND the inner already-succeeded
    guard (belt-and-suspenders — see billing/webhooks.py:_handle_tip_completed).
    """

    def setUp(self):
        self.sender = User.objects.create_user(
            username='tipsender@example.com', email='tipsender@example.com', password='pw',
        )
        self.creator = User.objects.create_user(
            username='tipcreator@example.com', email='tipcreator@example.com', password='pw',
        )

    def _make_pending_tip(self, session_id):
        return Tip.objects.create(
            sender=self.sender,
            creator=self.creator,
            amount_cents=500,
            status='pending',
            stripe_checkout_session_id=session_id,
        )

    def _tip_event(self, tip, session_id, event_id, payment_intent='pi_test'):
        return _make_stripe_event('checkout.session.completed', {
            'id': session_id,
            'payment_intent': payment_intent,
            'metadata': {
                'type': 'tip',
                'tip_id': str(tip.id),
                'creator_id': str(self.creator.id),
                'joke_id': '',
            },
        }, event_id=event_id)

    def test_tip_checkout_completed_marks_succeeded(self):
        from billing.webhooks import handle_event

        tip = self._make_pending_tip('cs_test_tip_001')
        event = self._tip_event(tip, 'cs_test_tip_001', 'evt_tip_001', payment_intent='pi_test_tip_001')

        handle_event(event)

        tip.refresh_from_db()
        self.assertEqual(tip.status, 'succeeded')
        self.assertEqual(tip.stripe_payment_intent_id, 'pi_test_tip_001')
        self.assertIsNotNone(tip.completed_at)

    def test_replayed_event_is_a_no_op(self):
        """Same event.id delivered twice -> second delivery never re-processes
        (outer ProcessedStripeEvent dedup, same mechanism the subscription
        path relies on)."""
        from billing.webhooks import handle_event

        tip = self._make_pending_tip('cs_test_tip_002')
        event = self._tip_event(tip, 'cs_test_tip_002', 'evt_tip_002', payment_intent='pi_test_tip_002')

        handle_event(event)
        tip.refresh_from_db()
        first_completed_at = tip.completed_at
        self.assertEqual(tip.status, 'succeeded')

        handle_event(event)  # Replay: identical event object, same event.id.

        tip.refresh_from_db()
        self.assertEqual(tip.status, 'succeeded')
        self.assertEqual(tip.completed_at, first_completed_at, 'Replay must not re-stamp completed_at')
        self.assertEqual(ProcessedStripeEvent.objects.filter(event_id='evt_tip_002').count(), 1)

    def test_second_completion_for_already_succeeded_tip_is_a_no_op(self):
        """Defense-in-depth: even a genuinely distinct event.id for the same
        underlying session/tip must not double-stamp completed_at or
        overwrite the payment_intent once the Tip is already succeeded."""
        from billing.webhooks import handle_event

        tip = self._make_pending_tip('cs_test_tip_003')
        event1 = self._tip_event(tip, 'cs_test_tip_003', 'evt_tip_003a', payment_intent='pi_test_tip_003')
        handle_event(event1)
        tip.refresh_from_db()
        first_completed_at = tip.completed_at
        self.assertEqual(tip.status, 'succeeded')

        event2 = self._tip_event(tip, 'cs_test_tip_003', 'evt_tip_003b', payment_intent='pi_test_tip_003_dup')
        handle_event(event2)

        tip.refresh_from_db()
        self.assertEqual(tip.status, 'succeeded')
        self.assertEqual(tip.completed_at, first_completed_at, 'Must not re-stamp completed_at')
        self.assertEqual(
            tip.stripe_payment_intent_id, 'pi_test_tip_003',
            'Must not overwrite payment_intent_id from a duplicate completion',
        )

    def test_non_tip_checkout_session_unaffected_regression(self):
        """A subscription checkout.session.completed must never touch the tip
        path — regression guard for the metadata-type branch added in Task 2."""
        from billing.webhooks import handle_event

        event = _make_stripe_event('checkout.session.completed', {
            'metadata': {'user_id': str(self.sender.pk), 'plan_slug': 'creator_pro'},
            'customer': 'cus_webhook_notip',
            'subscription': 'sub_webhook_notip',
            'client_reference_id': str(self.sender.pk),
        }, event_id='evt_notip_001')

        handle_event(event)

        self.assertEqual(Tip.objects.count(), 0)
        sub = Subscription.objects.get(user=self.sender)
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan.slug, 'creator_pro')


class WebhookInvoiceTests(TestCase):
    """invoice.paid clears past_due; invoice.payment_failed marks past_due."""

    def setUp(self):
        self.user = User.objects.create_user(username='invoice@example.com', email='invoice@example.com', password='pw')
        self.pro_plan = Plan.objects.get(slug='creator_pro')
        Subscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            stripe_customer_id='cus_inv_001',
            status='past_due',
        )

    def test_invoice_paid_clears_past_due(self):
        from billing.webhooks import handle_event

        event = _make_stripe_event('invoice.paid', {
            'customer': 'cus_inv_001',
            'period_end': 1702592000,
        }, event_id='evt_inv_paid_001')
        handle_event(event)

        sub = Subscription.objects.get(user=self.user)
        self.assertEqual(sub.status, 'active')

    def test_invoice_payment_failed_marks_past_due(self):
        from billing.webhooks import handle_event

        # Start as active
        sub = Subscription.objects.get(user=self.user)
        sub.status = 'active'
        sub.save()

        event = _make_stripe_event('invoice.payment_failed', {
            'customer': 'cus_inv_001',
        }, event_id='evt_inv_fail_001')

        with patch('notifications.service.send_email', side_effect=Exception('email down')):
            # Email failure should not prevent the status update
            handle_event(event)

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'past_due')
