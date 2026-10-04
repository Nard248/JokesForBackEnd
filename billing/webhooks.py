"""Stripe webhook handler — synchronous, idempotent, no worker required.

Flow: verify signature -> claim event atomically -> retrieve current subscription
under the account lock -> reconcile -> commit. Stripe HTTP calls use bounded
timeouts; any failure rolls back the event claim so Stripe can retry.
"""
import logging
from collections.abc import Mapping
from datetime import UTC

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from billing.models import Plan, PlanPrice, ProcessedStripeEvent, Subscription, Tip

logger = logging.getLogger('jokesfor')

User = get_user_model()


def _field(obj, name, default=None):
    """StripeObject is a dict; attributes such as ``items`` collide with methods."""
    return obj.get(name, default) if isinstance(obj, Mapping) else getattr(obj, name, default)


def _free_plan():
    return Plan.objects.filter(is_default=True).first()


def _plan_from_price_id(price_id: str):
    """Resolve our Plan from a Stripe price_id. Falls back to FREE."""
    if not price_id:
        return _free_plan()
    plan = Plan.objects.filter(stripe_price_id=price_id).first()
    if plan is None:
        historical = PlanPrice.objects.select_related('plan').filter(stripe_price_id=price_id).first()
        plan = historical.plan if historical else None
    return plan or _free_plan()


def _sync_is_premium(user, entitled: bool):
    """Keep UserProfile.is_premium in sync as a denormalized read-cache."""
    try:
        profile = user.profile
        if profile.is_premium != entitled:
            profile.is_premium = entitled
            profile.save(update_fields=['is_premium'])
    except ObjectDoesNotExist:
        logger.warning('billing.webhook: subscription owner has no profile')


def _object_id(value):
    return value if isinstance(value, str) else _field(value, 'id', '')


def _user_from_event(event_obj):
    """Prefer our persisted customer ownership; metadata must agree below."""
    customer_id = _object_id(_field(event_obj, 'customer'))
    if customer_id:
        sub = Subscription.objects.filter(stripe_customer_id=customer_id).first()
        if sub:
            return sub.user
    user_id = (_field(event_obj, 'metadata', {}) or {}).get('user_id')
    user_id = user_id or _field(event_obj, 'client_reference_id')
    if user_id:
        try:
            return User.objects.filter(pk=user_id).first()
        except (ValueError, TypeError):
            return None
    return None


def _reconcile_subscription(event_obj, subscription_id):
    from billing.stripe_gateway import retrieve_subscription

    user = _user_from_event(event_obj)
    if not user or not subscription_id:
        logger.warning('billing.webhook: subscription has no local owner')
        return None
    # All checkout and reconciliation paths lock User, including first creation.
    # Retrieve AFTER locking so concurrently delivered snapshots cannot regress us.
    user = User.objects.select_for_update().get(pk=user.pk)
    current = retrieve_subscription(subscription_id)
    customer_id = _object_id(_field(current, 'customer'))
    metadata_user = (_field(current, 'metadata', {}) or {}).get('user_id')
    event_user = (_field(event_obj, 'metadata', {}) or {}).get('user_id')
    event_customer = _object_id(_field(event_obj, 'customer'))
    sub = Subscription.objects.filter(user=user).first()
    if (not customer_id or _field(current, 'id') != subscription_id
            or (event_customer and event_customer != customer_id)
            or (metadata_user and str(metadata_user) != str(user.pk))
            or (event_user and str(event_user) != str(user.pk))
            or (sub and sub.stripe_customer_id and sub.stripe_customer_id != customer_id)):
        raise ValueError('Stripe subscription ownership mismatch')
    terminal = {'canceled', 'incomplete_expired'}
    state = _field(current, 'status')
    if state not in Subscription.LIVE_PAID_STATUSES | terminal:
        raise ValueError('Unknown Stripe subscription state')
    if sub and sub.stripe_subscription_id and sub.stripe_subscription_id != subscription_id:
        # A canceled OLD subscription or its invoice must never replace a new one.
        if state in terminal:
            return None
        previous = retrieve_subscription(sub.stripe_subscription_id)
        if (_field(previous, 'status') not in terminal
                or _field(current, 'created', 0) < _field(previous, 'created', 0)):
            logger.warning('billing.webhook: conflicting live subscriptions need reconciliation')
            return None
    items = _field(_field(current, 'items'), 'data', [])
    # This catalog sells exactly one recurring item. Unknown multi-item products
    # must not acquire paid entitlements accidentally.
    item = items[0] if len(items) == 1 else None
    price_id = _object_id(_field(item, 'price'))
    plan = _free_plan() if state in terminal else _plan_from_price_id(price_id)
    if sub is None:
        sub = Subscription(user=user)
    sub.plan = plan
    sub.status = state
    sub.stripe_subscription_id = subscription_id
    sub.stripe_customer_id = customer_id
    sub.stripe_price_id = price_id
    for field in ('current_period_start', 'current_period_end'):
        timestamp = _field(current, field) or _field(item, field)
        setattr(sub, field, timezone.datetime.fromtimestamp(timestamp, tz=UTC) if timestamp else None)
    sub.cancel_at_period_end = bool(_field(current, 'cancel_at_period_end', False))
    sub.save()
    _sync_is_premium(user, sub.is_entitled() and not plan.is_default)
    return sub


def _handle_tip_completed(session, metadata):
    """Mark a Tip succeeded for a tip-mode checkout.session.completed.

    Idempotent two ways: (1) the outer handle_event() dedups on event.id, so a
    replayed Stripe delivery never reaches here at all; (2) this function ALSO
    no-ops when the Tip is already succeeded, so a second completion for the
    same session/tip (e.g. a distinct event.id for the same underlying
    session) can never re-stamp completed_at or overwrite the payment_intent.
    """
    tip_id = metadata.get('tip_id')
    session_id = getattr(session, 'id', '') or ''

    tip_qs = Tip.objects.select_for_update()
    tip = None
    if tip_id:
        tip = tip_qs.filter(pk=tip_id).first()
    if not tip and session_id:
        tip = tip_qs.filter(stripe_checkout_session_id=session_id).first()

    if not tip:
        logger.warning('billing.webhook: no Tip for checkout.session %s', session_id)
        return

    if tip.status == 'succeeded':
        return  # Already processed — idempotent no-op.

    # Money-truth guard: checkout.session.completed fires as soon as the
    # customer finishes Checkout, which for a delayed-notification payment
    # method (e.g. ACH debit) is BEFORE the payment actually settles —
    # payment_status is 'unpaid'/'processing' until a later async event.
    # Marking the tip succeeded here would let the public tips-received
    # total overstate money that may never arrive if the async payment
    # later fails. Understating (leaving it pending) is the safe default;
    # we don't yet handle checkout.session.async_payment_succeeded, so a
    # non-'paid' session just stays pending rather than being completed by
    # a handler we don't have (a later wave can add that event).
    payment_status = getattr(session, 'payment_status', 'paid')
    if payment_status != 'paid':
        logger.info(
            'billing.webhook: tip %s checkout.session %s completed with '
            'payment_status=%s (not settled) — leaving pending',
            tip.id, session_id, payment_status,
        )
        return

    tip.status = 'succeeded'
    tip.stripe_payment_intent_id = getattr(session, 'payment_intent', '') or ''
    tip.completed_at = timezone.now()
    tip.save(update_fields=['status', 'stripe_payment_intent_id', 'completed_at'])


def _handle_checkout_completed(session):
    metadata = getattr(session, 'metadata', {}) or {}
    # Tip completion runs only for a genuine payment-mode tip session (mode is
    # set at creation, billing/stripe_gateway.py:create_tip_checkout_session).
    # Requiring mode=='payment' here keeps a corrupted subscription-mode
    # session that carried a stray type='tip' out of the tip handler; the
    # anti-downgrade protection for the reverse case lives in the guard below.
    mode = getattr(session, 'mode', '')
    if metadata.get('type') == 'tip' and mode == 'payment':
        _handle_tip_completed(session, metadata)
        return

    if mode != 'subscription':
        return
    _reconcile_subscription(session, _object_id(_field(session, 'subscription')))


def _handle_subscription_event(subscription, event_type):
    _reconcile_subscription(subscription, _field(subscription, 'id'))


def _invoice_subscription_id(invoice):
    # Basil+ moved subscription references under parent.subscription_details.
    parent = _field(invoice, 'parent')
    details = _field(parent, 'subscription_details')
    return _object_id(_field(invoice, 'subscription') or _field(details, 'subscription'))


def _handle_invoice_paid(invoice):
    subscription_id = _invoice_subscription_id(invoice)
    if subscription_id:
        _reconcile_subscription(invoice, subscription_id)


def _handle_payment_failed(invoice):
    # The invoice may concern an old or one-off payment. Its event name alone
    # says nothing about the current subscription's entitlement.
    subscription_id = _invoice_subscription_id(invoice)
    if not subscription_id:
        return
    sub = _reconcile_subscription(invoice, subscription_id)
    if sub is None or sub.status != 'past_due':
        return
    try:
        from notifications.service import send_email
        send_email(
            to_email=sub.user.email, template_name='payment_failed',
            context={'user': sub.user, 'plan': sub.plan}, user=sub.user,
        )
    except Exception:
        logger.warning('billing.webhook: payment notification could not be sent')


@transaction.atomic
def handle_event(event):
    """Main entry point. Idempotent on event.id — safe for Stripe re-delivery."""
    event_id = event.id
    event_type = event.type

    # Unique insertion serializes concurrent duplicate deliveries BEFORE effects.
    # The encompassing transaction rolls this back if reconciliation fails.
    _, created = ProcessedStripeEvent.objects.get_or_create(
        event_id=event_id, defaults={'event_type': event_type},
    )
    if not created:
        return

    obj = event.data.object

    if event_type == 'checkout.session.completed':
        _handle_checkout_completed(obj)
    elif event_type in ('customer.subscription.created', 'customer.subscription.updated',
                         'customer.subscription.deleted'):
        _handle_subscription_event(obj, event_type)
    elif event_type == 'invoice.paid':
        _handle_invoice_paid(obj)
    elif event_type == 'invoice.payment_failed':
        _handle_payment_failed(obj)
    # Other event types are ignored — future handlers can be added here
