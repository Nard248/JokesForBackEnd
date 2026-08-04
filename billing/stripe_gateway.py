"""Thin env-gated wrapper around the Stripe SDK.

Dormant when STRIPE_SECRET_KEY is not set — exactly like the Sentry integration.
Views check is_enabled() and return 503 billing_unavailable if False.
The webhook handler returns 200-noop when dormant (Stripe stops retrying).
"""
import stripe
from django.conf import settings


class BillingUnavailable(Exception):
    """Raised when stripe gateway is accessed without STRIPE_SECRET_KEY."""


def is_enabled() -> bool:
    return bool(getattr(settings, 'STRIPE_SECRET_KEY', ''))


def _client():
    if not is_enabled():
        raise BillingUnavailable('Stripe is not configured (STRIPE_SECRET_KEY unset).')
    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = settings.STRIPE_API_VERSION
    return stripe


def get_or_create_customer(user) -> str:
    """Return the Stripe customer_id for user, creating it if needed.

    Persists stripe_customer_id on the user's Subscription row.
    """
    from billing.models import Plan, Subscription

    s = _client()

    try:
        sub = user.subscription
        if sub.stripe_customer_id:
            return sub.stripe_customer_id
    except Exception:
        sub = None

    customer = s.Customer.create(
        email=user.email,
        metadata={'user_id': str(user.pk)},
    )
    cid = customer.id

    if sub is None:
        free_plan = Plan.objects.filter(is_default=True).first()
        sub = Subscription.objects.create(
            user=user,
            plan=free_plan,
            stripe_customer_id=cid,
            status='free',
        )
    else:
        sub.stripe_customer_id = cid
        sub.save(update_fields=['stripe_customer_id'])

    return cid


def create_checkout_session(user, plan):
    """Create a Stripe Checkout Session for the given Plan."""
    s = _client()
    customer_id = get_or_create_customer(user)
    return s.checkout.Session.create(
        mode='subscription',
        customer=customer_id,
        line_items=[{'price': plan.stripe_price_id, 'quantity': 1}],
        success_url=settings.BILLING_SUCCESS_URL,
        cancel_url=settings.BILLING_CANCEL_URL,
        client_reference_id=str(user.pk),
        metadata={'user_id': str(user.pk), 'plan_slug': plan.slug},
    )


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
        existing_price = s.Price.retrieve(plan.stripe_price_id)
        if existing_price.unit_amount == plan.amount_cents:
            plan.save(update_fields=['stripe_product_id'])
            return product.id, plan.stripe_price_id

        s.Price.modify(plan.stripe_price_id, active=False)

    price = s.Price.create(
        product=product.id,
        unit_amount=plan.amount_cents,
        currency=plan.currency,
        recurring={'interval': plan.interval},
    )
    plan.stripe_price_id = price.id
    plan.save(update_fields=['stripe_product_id', 'stripe_price_id'])
    return product.id, price.id
