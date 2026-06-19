from django.urls import path

from billing.views import (
    CheckoutSessionView,
    EntitlementsView,
    MySubscriptionView,
    PlansView,
    PortalSessionView,
    StripeWebhookView,
)

urlpatterns = [
    path('checkout-session', CheckoutSessionView.as_view(), name='billing-checkout-session'),
    path('portal-session', PortalSessionView.as_view(), name='billing-portal-session'),
    path('webhook', StripeWebhookView.as_view(), name='billing-webhook'),
    path('my-subscription', MySubscriptionView.as_view(), name='billing-my-subscription'),
    path('entitlements', EntitlementsView.as_view(), name='billing-entitlements'),
    path('plans', PlansView.as_view(), name='billing-plans'),
]
