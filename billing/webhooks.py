"""Stripe webhook handler — synchronous, idempotent, no worker required.

Flow: verify signature -> dedupe on event.id -> dispatch -> one UPSERT -> 200.
The whole handler is a few ms (no blocking I/O before the return), compliant
with the no-worker, single-Cloud-Run-app architecture.
"""
import logging
from datetime import timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from billing.models import Plan, ProcessedStripeEvent, Subscription, Tip

logger = logging.getLogger('jokesfor')

User = get_user_model()


def _free_plan():
    return Plan.objects.filter(is_default=True).first()


def _plan_from_price_id(price_id: str):
    """Resolve our Plan from a Stripe price_id. Falls back to FREE."""
    if not price_id:
        return _free_plan()
    plan = Plan.objects.filter(stripe_price_id=price_id).first()
    return plan or _free_plan()


def _sync_is_premium(user, entitled: bool):
    """Keep UserProfile.is_premium in sync as a denormalized read-cache."""
    try:
        profile = user.profile
        if profile.is_premium != entitled:
            profile.is_premium = entitled
            profile.save(update_fields=['is_premium'])
    except Exception:
        pass


@transaction.atomic
def _upsert_subscription(user, *, plan, stripe_subscription_id='', stripe_customer_id='',
                          stripe_price_id='', status, period_start=None, period_end=None,
                          cancel_at_period_end=False):
    sub, _ = Subscription.objects.select_for_update().get_or_create(
        user=user,
        defaults={'plan': plan, 'status': status},
    )
    sub.plan = plan
    sub.status = status
    if stripe_subscription_id:
        sub.stripe_subscription_id = stripe_subscription_id
    if stripe_customer_id:
        sub.stripe_customer_id = stripe_customer_id
    if stripe_price_id:
        sub.stripe_price_id = stripe_price_id
    if period_start is not None:
        sub.current_period_start = timezone.datetime.fromtimestamp(period_start, tz=dt_timezone.utc)
    if period_end is not None:
        sub.current_period_end = timezone.datetime.fromtimestamp(period_end, tz=dt_timezone.utc)
    sub.cancel_at_period_end = cancel_at_period_end
    sub.save()
    _sync_is_premium(user, sub.is_entitled())
    return sub


def _user_from_event(event_obj):
    """Resolve User from a Stripe object's metadata or client_reference_id."""
    metadata = getattr(event_obj, 'metadata', {}) or {}
    user_id = metadata.get('user_id')
    if user_id:
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            pass
    client_ref = getattr(event_obj, 'client_reference_id', None)
    if client_ref:
        try:
            return User.objects.get(pk=client_ref)
        except User.DoesNotExist:
            pass
    # Fall back: look up by Stripe customer id
    customer_id = getattr(event_obj, 'customer', None)
    if customer_id:
        sub = Subscription.objects.filter(stripe_customer_id=customer_id).first()
        if sub:
            return sub.user
    return None


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

    tip.status = 'succeeded'
    tip.stripe_payment_intent_id = getattr(session, 'payment_intent', '') or ''
    tip.completed_at = timezone.now()
    tip.save(update_fields=['status', 'stripe_payment_intent_id', 'completed_at'])


def _handle_checkout_completed(session):
    metadata = getattr(session, 'metadata', {}) or {}
    if metadata.get('type') == 'tip':
        _handle_tip_completed(session, metadata)
        return

    user = _user_from_event(session)
    if not user:
        logger.warning('billing.webhook: no user for checkout.session %s', session.id)
        return

    price_id = None
    if hasattr(session, 'line_items'):
        pass  # Not available in webhook payload; resolved via subscription event
    subscription_id = getattr(session, 'subscription', '')
    customer_id = getattr(session, 'customer', '')
    plan_slug = metadata.get('plan_slug', '')
    plan = Plan.objects.filter(slug=plan_slug).first() if plan_slug else None
    if not plan:
        plan = _free_plan()

    _upsert_subscription(
        user,
        plan=plan,
        stripe_subscription_id=subscription_id or '',
        stripe_customer_id=customer_id or '',
        status='active',
    )


def _handle_subscription_event(subscription, event_type: str):
    customer_id = getattr(subscription, 'customer', '') or ''
    sub_db = Subscription.objects.filter(stripe_customer_id=customer_id).first()
    user = sub_db.user if sub_db else None

    if not user:
        # Try metadata
        metadata = getattr(subscription, 'metadata', {}) or {}
        user_id = metadata.get('user_id')
        if user_id:
            try:
                user = User.objects.get(pk=user_id)
            except User.DoesNotExist:
                pass

    if not user:
        logger.warning('billing.webhook: no user for subscription %s', subscription.id)
        return

    if event_type == 'customer.subscription.deleted':
        free = _free_plan()
        _upsert_subscription(
            user,
            plan=free,
            stripe_subscription_id=subscription.id,
            stripe_customer_id=customer_id,
            status='canceled',
        )
        return

    price_id = ''
    items = getattr(subscription, 'items', None)
    if items and hasattr(items, 'data') and items.data:
        price_id = items.data[0].price.id

    plan = _plan_from_price_id(price_id)
    status = getattr(subscription, 'status', 'active')
    period_start = getattr(subscription, 'current_period_start', None)
    period_end = getattr(subscription, 'current_period_end', None)
    cancel_at = getattr(subscription, 'cancel_at_period_end', False)

    _upsert_subscription(
        user,
        plan=plan,
        stripe_subscription_id=subscription.id,
        stripe_customer_id=customer_id,
        stripe_price_id=price_id,
        status=status,
        period_start=period_start,
        period_end=period_end,
        cancel_at_period_end=cancel_at,
    )


def _handle_invoice_paid(invoice):
    customer_id = getattr(invoice, 'customer', '') or ''
    sub_db = Subscription.objects.filter(stripe_customer_id=customer_id).first()
    if not sub_db:
        return
    # Clear past_due, stamp period anchor
    if sub_db.status == 'past_due':
        sub_db.status = 'active'
    period_end = getattr(invoice, 'period_end', None)
    if period_end:
        sub_db.current_period_end = timezone.datetime.fromtimestamp(period_end, tz=dt_timezone.utc)
    sub_db.save(update_fields=['status', 'current_period_end'])
    _sync_is_premium(sub_db.user, sub_db.is_entitled())


def _handle_payment_failed(invoice):
    customer_id = getattr(invoice, 'customer', '') or ''
    sub_db = Subscription.objects.filter(stripe_customer_id=customer_id).first()
    if not sub_db:
        return
    sub_db.status = 'past_due'
    sub_db.save(update_fields=['status'])
    _sync_is_premium(sub_db.user, False)

    # Send dunning email via notification engine (quick, non-blocking)
    try:
        from notifications.service import send_email
        send_email(
            to_email=sub_db.user.email,
            template_name='payment_failed',
            context={'user': sub_db.user, 'plan': sub_db.plan},
            user=sub_db.user,
        )
    except Exception:
        pass  # Never risk the 200 on email failure


@transaction.atomic
def handle_event(event):
    """Main entry point. Idempotent on event.id — safe for Stripe re-delivery."""
    event_id = event.id
    event_type = event.type

    # Idempotency check
    if ProcessedStripeEvent.objects.filter(event_id=event_id).exists():
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

    ProcessedStripeEvent.objects.create(event_id=event_id, event_type=event_type)
