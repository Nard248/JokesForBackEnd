import logging

from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from billing import entitlements
from billing.models import Plan, Subscription
from billing.serializers import (
    PlanPublicSerializer, MySubscriptionSerializer, EntitlementsSerializer,
)
from billing.stripe_gateway import BillingUnavailable, is_enabled

logger = logging.getLogger('jokesfor')


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

        try:
            session = create_checkout_session(request.user, plan)
            return Response({'url': session.url})
        except BillingUnavailable:
            return _billing_unavailable()
        except Exception as exc:
            logger.exception('billing.checkout error: %s', exc)
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
