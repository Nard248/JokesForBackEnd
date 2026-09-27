"""Thin env-gated wrapper around the Stripe SDK.

Transport is dormant without STRIPE_SECRET_KEY. New subscription sales also
require CREATOR_CHECKOUT_ENABLED and a signing secret; portal and webhook
reconciliation remain available when only the sales gate is off.
"""
import uuid
from datetime import timedelta

import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone


class BillingUnavailable(Exception):
    """Raised when stripe gateway is accessed without STRIPE_SECRET_KEY."""


class CheckoutConflict(Exception):
    """The account already has a checkout or a live subscription."""


def is_enabled() -> bool:
    return bool(getattr(settings, 'STRIPE_SECRET_KEY', ''))


def is_checkout_enabled() -> bool:
    return bool(settings.CREATOR_CHECKOUT_ENABLED and is_enabled() and settings.STRIPE_WEBHOOK_SECRET)


def _client():
    if not is_enabled():
        raise BillingUnavailable('Stripe is not configured (STRIPE_SECRET_KEY unset).')
    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = settings.STRIPE_API_VERSION
    stripe.default_http_client = stripe.RequestsClient(timeout=5)
    stripe.max_network_retries = 0
    return stripe


@transaction.atomic
def get_or_create_customer(user) -> str:
    """Serialize customer creation even before the first Subscription row exists."""
    from billing.models import Plan, Subscription

    get_user_model().objects.select_for_update().get(pk=user.pk)
    sub = Subscription.objects.filter(user=user).first()
    if sub and sub.stripe_customer_id:
        return sub.stripe_customer_id
    customer = _client().Customer.create(
        metadata={'user_id': str(user.pk)},
        idempotency_key=f'jokesfor-customer-{user.pk}',
    )
    if sub is None:
        Subscription.objects.create(
            user=user, plan=Plan.objects.get(is_default=True),
            stripe_customer_id=customer.id, status='free',
        )
    else:
        sub.stripe_customer_id = customer.id
        sub.save(update_fields=['stripe_customer_id'])
    return customer.id


def retrieve_subscription(subscription_id):
    return _client().Subscription.retrieve(subscription_id)


def create_checkout_session(user, plan):
    """Reuse one open session per account; persist its key before any Stripe I/O.

    A failed HTTP request may have succeeded remotely. Keep the same parameters
    and idempotency key for the retry. Never replay an unresolved request after
    Stripe's 24-hour idempotency window; reconciliation then needs an operator.
    """
    from billing.models import Subscription, SubscriptionCheckout

    if not is_checkout_enabled():
        raise BillingUnavailable('Creator checkout is disabled.')
    s = _client()
    parameters = {
        'mode': 'subscription',
        'line_items': [{'price': plan.stripe_price_id, 'quantity': 1}],
        'success_url': settings.BILLING_SUCCESS_URL,
        'cancel_url': settings.BILLING_CANCEL_URL,
        'client_reference_id': str(user.pk),
        'metadata': {'user_id': str(user.pk), 'plan_slug': plan.slug},
        'subscription_data': {'metadata': {'user_id': str(user.pk), 'plan_slug': plan.slug}},
    }
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        SubscriptionCheckout.objects.get_or_create(user=user, defaults={'parameters': parameters})
    # This separate transaction persists a newly created customer even if the
    # later Checkout request times out and its transaction rolls back.
    customer_id = get_or_create_customer(user)
    for _ in range(3):
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=user.pk)
            sub = Subscription.objects.get(user=user)
            if sub.status in Subscription.LIVE_PAID_STATUSES and sub.stripe_subscription_id:
                raise CheckoutConflict('Manage your existing subscription in the billing portal.')
            attempt = SubscriptionCheckout.objects.get(user=user)
            if attempt.stripe_session_id:
                session = s.checkout.Session.retrieve(attempt.stripe_session_id)
                if session.status == 'open':
                    if attempt.parameters['line_items'] != parameters['line_items']:
                        raise CheckoutConflict('Finish or expire your existing checkout before changing plans.')
                    return session
                if session.status == 'complete':
                    remote_sub = retrieve_subscription(session.subscription)
                    if remote_sub.status not in {'canceled', 'incomplete_expired'}:
                        raise CheckoutConflict('Your checkout is complete. Manage billing in the portal.')
                elif session.status != 'expired':
                    raise BillingUnavailable('Checkout state needs reconciliation.')
                # Commit a replacement key before making the replacement request.
                attempt.request_key = uuid.uuid4()
                attempt.parameters = parameters
                attempt.stripe_session_id = ''
                attempt.created_at = timezone.now()
                attempt.save()
                continue
            if attempt.created_at < timezone.now() - timedelta(hours=23):
                raise BillingUnavailable('An unresolved checkout needs reconciliation before retrying.')
            if attempt.parameters['line_items'] != parameters['line_items']:
                raise CheckoutConflict('Retry your existing checkout before changing plans.')
            # Also catch Stripe subscriptions whose webhook has not arrived yet.
            remote = s.Subscription.list(customer=customer_id, status='all', limit=100)
            if remote.has_more or any(item.status not in {'canceled', 'incomplete_expired'} for item in remote.data):
                raise CheckoutConflict('Manage your existing subscription in the billing portal.')
            session = s.checkout.Session.create(
                **attempt.parameters, customer=customer_id,
                idempotency_key=f'jokesfor-checkout-{attempt.request_key}',
            )
            attempt.stripe_session_id = session.id
            attempt.save(update_fields=['stripe_session_id'])
            return session
    raise BillingUnavailable('Checkout changed concurrently; retry shortly.')


def create_tip_checkout_session(sender, creator, joke, amount_cents: int):
    """Create a Stripe Checkout Session (payment mode) for a one-off tip.

    Creates the Tip(pending) row first, then the Stripe session, then stamps
    stripe_checkout_session_id on the Tip. Returns the Stripe session (has .url).
    """
    from billing.models import Tip
    from jokes.identity import public_display_name

    s = _client()
    customer_id = get_or_create_customer(sender)

    tip = Tip.objects.create(
        sender=sender,
        creator=creator,
        joke=joke,
        amount_cents=amount_cents,
        status='pending',
    )

    session = s.checkout.Session.create(
        mode='payment',
        customer=customer_id,
        # Card-only (belt-and-suspenders with the webhook's payment_status
        # guard, see billing/webhooks.py:_handle_tip_completed): cards settle
        # synchronously, so checkout.session.completed always carries
        # payment_status='paid'. Without this, live-mode dashboard config
        # could enable a delayed-notification method (e.g. ACH debit), whose
        # completed event fires with payment_status='unpaid'/'processing' —
        # money that may still fail to arrive. Card-only is fine for tips v1.
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': tip.currency,
                'unit_amount': amount_cents,
                'product_data': {
                    'name': f'Tip for {public_display_name(creator)}',
                },
            },
            'quantity': 1,
        }],
        success_url=settings.BILLING_SUCCESS_URL,
        cancel_url=settings.BILLING_CANCEL_URL,
        metadata={
            'type': 'tip',
            'tip_id': str(tip.id),
            'creator_id': str(creator.id),
            'joke_id': str(joke.id) if joke else '',
        },
    )

    tip.stripe_checkout_session_id = session.id
    tip.save(update_fields=['stripe_checkout_session_id'])

    return session


def create_portal_session(stripe_customer_id: str):
    """Create a Stripe Customer Portal Session."""
    s = _client()
    return s.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=settings.BILLING_PORTAL_RETURN_URL,
    )


def construct_event(payload: bytes, sig_header: str):
    """Verify and construct a Stripe event from raw webhook payload."""
    s = _client()
    return s.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )


def push_plan_to_stripe(plan):
    """Idempotent: create/update Stripe Product + Price for a Plan.

    - Creates Product once (stores stripe_product_id).
    - If amount_cents changed: creates new Price, archives old.
    - Returns (product_id, price_id).
    """
    from billing.models import PlanPrice

    def remember_price(price_id):
        mapping, _ = PlanPrice.objects.get_or_create(
            stripe_price_id=price_id, defaults={'plan': plan},
        )
        if mapping.plan_id != plan.pk:
            raise BillingUnavailable('This Stripe price is already assigned to another plan.')

    s = _client()

    if plan.stripe_product_id:
        product = s.Product.retrieve(plan.stripe_product_id)
    else:
        product = s.Product.create(
            name=plan.name,
            metadata={'plan_slug': plan.slug},
        )
        plan.stripe_product_id = product.id

    if plan.stripe_price_id:
        remember_price(plan.stripe_price_id)
        existing_price = s.Price.retrieve(plan.stripe_price_id)
        recurring = existing_price.get('recurring') or {}
        if (existing_price.unit_amount == plan.amount_cents
                and existing_price.currency == plan.currency.lower()
                and existing_price.product == product.id
                and existing_price.active
                and recurring.get('interval') == plan.interval
                and recurring.get('interval_count', 1) == 1):
            plan.save(update_fields=['stripe_product_id'])
            return product.id, plan.stripe_price_id

    price = s.Price.create(
        product=product.id,
        unit_amount=plan.amount_cents,
        currency=plan.currency,
        recurring={'interval': plan.interval},
    )
    # Persist both mappings before retiring the previous price. Existing
    # subscribers keep its entitlement mapping after the public price changes.
    remember_price(price.id)
    old_price_id = plan.stripe_price_id
    plan.stripe_price_id = price.id
    plan.save(update_fields=['stripe_product_id', 'stripe_price_id'])
    if old_price_id:
        s.Price.modify(old_price_id, active=False)
    return product.id, price.id
