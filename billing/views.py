import logging

from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from billing import entitlements
from billing.models import Plan, Subscription, Tip
from billing.serializers import (
    PlanPublicSerializer, MySubscriptionSerializer, EntitlementsSerializer,
)
from billing.stripe_gateway import BillingUnavailable, is_enabled

logger = logging.getLogger('jokesfor')

# Fixed tip tiers, in cents — abuse/laundering guard: no arbitrary amounts.
TIP_AMOUNT_TIERS_CENTS = {100, 300, 500, 1000}


def _billing_unavailable():
    return Response(
        {'detail': 'Billing is not configured.', 'code': 'billing_unavailable'},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


class PlansView(APIView):
    """GET /api/v1/billing/plans — public pricing page data."""
    permission_classes = [AllowAny]

    def get(self, request):
        plans = Plan.objects.filter(is_active=True, is_public=True).order_by('sort_order')
        return Response(PlanPublicSerializer(plans, many=True).data)


class CheckoutSessionView(APIView):
    """POST /api/v1/billing/checkout-session — create a Stripe Checkout Session."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not is_enabled():
            return _billing_unavailable()

        from billing.stripe_gateway import create_checkout_session

        plan_slug = request.data.get('plan_slug', '')
        try:
            plan = Plan.objects.get(slug=plan_slug, is_active=True)
        except Plan.DoesNotExist:
            return Response({'detail': 'Plan not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not plan.stripe_price_id:
            return Response(
                {'detail': 'This plan is not yet available for purchase.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Payment-integrity guard: never open a SECOND subscription checkout while
        # the user already has a live paid subscription — that orphans the first
        # sub (webhook overwrites stripe_subscription_id) and double-bills them.
        # Send them to the Customer Portal to change/cancel their plan instead.
        active_sub = (
            Subscription.objects
            .filter(user=request.user, status__in=Subscription.LIVE_PAID_STATUSES)
            .exclude(stripe_subscription_id='', stripe_customer_id='')
            .first()
        )
        if active_sub:
            body = {
                'detail': 'You already have an active subscription — manage or change '
                          'your plan from the billing portal.',
                'code': 'active_subscription',
            }
            if active_sub.stripe_customer_id:
                try:
                    from billing.stripe_gateway import create_portal_session
                    portal = create_portal_session(active_sub.stripe_customer_id)
                    body['portal_url'] = portal.url
                except Exception as exc:  # portal is a convenience — never block the 409 on it
                    logger.warning('billing.checkout: portal_url unavailable for guard: %s', exc)
            return Response(body, status=status.HTTP_409_CONFLICT)

        try:
            session = create_checkout_session(request.user, plan)
            return Response({'url': session.url})
        except BillingUnavailable:
            return _billing_unavailable()
        except Exception as exc:
            logger.exception('billing.checkout error: %s', exc)
            return Response({'detail': 'Checkout error.'}, status=status.HTTP_502_BAD_GATEWAY)


class TipCheckoutView(APIView):
    """POST /api/v1/tips/checkout/ — create a Stripe Checkout Session (payment
    mode) for a one-off tip to a creator.

    Security: amount must be one of the fixed tiers (server-validated — the
    client can't send arbitrary cents); creator must exist and be a real
    creator (has published jokes); self-tipping is rejected.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not is_enabled():
            return _billing_unavailable()

        from django.contrib.auth import get_user_model

        from jokes.models import Joke

        User = get_user_model()

        raw_amount = request.data.get('amount_cents')
        try:
            amount_cents = int(raw_amount)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'amount_cents must be an integer.', 'code': 'invalid_amount'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if amount_cents not in TIP_AMOUNT_TIERS_CENTS:
            return Response(
                {'detail': 'Amount must be one of the fixed tip tiers.', 'code': 'invalid_amount'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        creator_id = request.data.get('creator_id')
        if not creator_id:
            return Response(
                {'detail': 'creator_id is required.', 'code': 'creator_required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            creator = User.objects.get(pk=creator_id)
        except (User.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'Creator not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not Joke.objects.filter(creator=creator).exists():
            return Response(
                {'detail': 'This user is not a creator.', 'code': 'not_a_creator'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if creator.pk == request.user.pk:
            return Response(
                {'detail': 'You cannot tip yourself.', 'code': 'self_tip'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        joke = None
        joke_id = request.data.get('joke_id')
        if joke_id:
            try:
                joke = Joke.objects.get(pk=joke_id)
            except (Joke.DoesNotExist, ValueError, TypeError):
                return Response({'detail': 'Joke not found.'}, status=status.HTTP_400_BAD_REQUEST)
            if joke.creator_id != creator.pk:
                return Response(
                    {'detail': 'Joke does not belong to this creator.', 'code': 'joke_creator_mismatch'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        from billing.stripe_gateway import create_tip_checkout_session

        try:
            session = create_tip_checkout_session(request.user, creator, joke, amount_cents)
            tip = Tip.objects.get(stripe_checkout_session_id=session.id)
            return Response({'checkout_url': session.url, 'tip_id': tip.id})
        except BillingUnavailable:
            return _billing_unavailable()
        except Exception as exc:
            logger.exception('billing.tip_checkout error: %s', exc)
            return Response({'detail': 'Checkout error.'}, status=status.HTTP_502_BAD_GATEWAY)


class PortalSessionView(APIView):
    """POST /api/v1/billing/portal-session — create a Stripe Customer Portal Session."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not is_enabled():
            return _billing_unavailable()

        from billing.stripe_gateway import create_portal_session

        try:
            sub = request.user.subscription
            if not sub.stripe_customer_id:
                return Response(
                    {'detail': 'No billing account found.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
            session = create_portal_session(sub.stripe_customer_id)
            return Response({'url': session.url})
        except Subscription.DoesNotExist:
            return Response(
                {'detail': 'No billing account found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        except BillingUnavailable:
            return _billing_unavailable()
        except Exception as exc:
            logger.exception('billing.portal error: %s', exc)
            return Response({'detail': 'Portal error.'}, status=status.HTTP_502_BAD_GATEWAY)


@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(APIView):
    """POST /api/v1/billing/webhook — Stripe webhook receiver.

    Public, CSRF-exempt, signature-verified, idempotent on event.id.
    Reads raw request.body (never request.data — re-parsing breaks the sig).
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # No auth — public endpoint

    def post(self, request):
        if not is_enabled():
            # Dormant: return 200 so Stripe doesn't retry
            return Response({'detail': 'billing_dormant'})

        from billing import webhooks
        from billing.stripe_gateway import construct_event
        import stripe

        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

        try:
            event = construct_event(payload, sig_header)
        except stripe.error.SignatureVerificationError:
            return Response({'detail': 'Invalid signature.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception('billing.webhook construct_event error: %s', exc)
            return Response({'detail': 'Webhook error.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            webhooks.handle_event(event)
        except Exception as exc:
            logger.exception('billing.webhook handle_event error: %s', exc)
            return Response({'detail': 'Handler error.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({'received': True})


class MySubscriptionView(APIView):
    """GET /api/v1/billing/my-subscription — current plan + status for the authenticated user."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            sub = request.user.subscription
            return Response(MySubscriptionSerializer(sub).data)
        except Subscription.DoesNotExist:
            plan = entitlements.effective_plan(request.user)
            return Response({
                'plan_slug': plan.slug if plan else 'free',
                'plan_name': plan.name if plan else 'Free',
                'status': 'free',
                'current_period_end': None,
                'cancel_at_period_end': False,
                'stripe_customer_id': '',
            })


class EntitlementsView(APIView):
    """GET /api/v1/billing/entitlements — resolved features/limits for the frontend."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        plan = entitlements.effective_plan(request.user)
        features = {k: entitlements.has_feature(request.user, k) for k in entitlements.KNOWN_FEATURES}
        limits = {k: entitlements.get_limit(request.user, k) for k in entitlements.KNOWN_LIMITS}
        data = {
            'plan': plan.slug if plan else 'free',
            'features': features,
            'limits': limits,
        }
        return Response(data)
