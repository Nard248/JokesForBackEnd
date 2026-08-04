from django.urls import path

from billing.views import TipCheckoutView

urlpatterns = [
    path('checkout/', TipCheckoutView.as_view(), name='tip-checkout'),
]
