from django.conf import settings
from django.db import models


class Plan(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    interval = models.CharField(
        max_length=10,
        choices=[('month', 'month'), ('year', 'year')],
        blank=True,
    )
    amount_cents = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default='usd')
    stripe_product_id = models.CharField(max_length=80, blank=True)
    stripe_price_id = models.CharField(max_length=80, blank=True)

    features = models.JSONField(default=dict, blank=True)
    limits = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name

    @property
    def amount_display(self):
        if self.amount_cents is None:
            return 'Free'
        return f'${self.amount_cents / 100:.2f}/{self.interval}'


class Subscription(models.Model):
    ACTIVE_STATUSES = {'active', 'trialing'}
    # Statuses that represent a LIVE Stripe subscription that bills (or will bill).
    # Used to guard checkout: opening a second Stripe subscription while one of
    # these is live double-bills the customer. past_due is included because the
    # subscription is still live in Stripe (payment retries in progress) — it is
    # NOT canceled, so a fresh checkout would create a parallel paying sub.
    # (Deliberately excludes free / canceled / incomplete_expired: no live sub.)
    LIVE_PAID_STATUSES = {'active', 'trialing', 'past_due'}

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscription',
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions')
    stripe_customer_id = models.CharField(max_length=80, blank=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=80, blank=True, db_index=True)
    stripe_price_id = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=24, default='free')
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user_id} / {self.plan.slug} / {self.status}'

    def is_entitled(self):
        return self.status in self.ACTIVE_STATUSES


class UsageCounter(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='usage_counters',
    )
    key = models.CharField(max_length=64)
    period_key = models.CharField(max_length=16)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('user', 'key', 'period_key')

    def __str__(self):
        return f'{self.user_id}/{self.key}/{self.period_key}={self.count}'


class ProcessedStripeEvent(models.Model):
    event_id = models.CharField(max_length=80, unique=True)
    event_type = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.event_type} / {self.event_id}'
