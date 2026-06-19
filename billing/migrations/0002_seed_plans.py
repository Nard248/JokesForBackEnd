"""Seed EXAMPLE plans with PLACEHOLDER prices.

These are examples to demonstrate the engine — NOT the final pricing catalog.
Amounts are PLACEHOLDER; stripe_* ids are blank until admin runs Push to Stripe
with real keys. Edit in admin before launch.
"""
from django.db import migrations

PLANS = [
    dict(
        slug='free',
        name='Free',
        description='Get started with JokesFor at no cost.',
        is_default=True,
        is_active=True,
        is_public=True,
        interval='',
        amount_cents=None,
        currency='usd',
        sort_order=0,
        features={
            'creator_analytics': True,   # True until business decides paid — flip in admin, no deploy
            'daily_joke_preview': False,
            'mature_content_addon': False,
        },
        limits={
            'mystery_box_rolls_per_day': 3,
            'submissions_per_day': 5,
            'daily_jokes_per_day': 1,
            'daily_joke_history_days': 30,
        },
    ),
    dict(
        slug='supporter',
        name='Supporter (PLACEHOLDER)',
        description='Support the platform — PLACEHOLDER price, edit before launch.',
        is_default=False,
        is_active=True,
        is_public=True,
        interval='month',
        amount_cents=500,   # $5/mo PLACEHOLDER — EDIT BEFORE LAUNCH
        currency='usd',
        sort_order=5,
        features={
            'creator_analytics': True,
            'daily_joke_preview': True,
            'mature_content_addon': False,
        },
        limits={
            'mystery_box_rolls_per_day': 10,
            'submissions_per_day': 15,
            'daily_jokes_per_day': 3,
            'daily_joke_history_days': 90,
        },
    ),
    dict(
        slug='creator_pro',
        name='Creator Pro (PLACEHOLDER)',
        description='Power-user tier — PLACEHOLDER price, edit before launch.',
        is_default=False,
        is_active=True,
        is_public=True,
        interval='month',
        amount_cents=1500,  # $15/mo PLACEHOLDER — EDIT BEFORE LAUNCH
        currency='usd',
        sort_order=10,
        features={
            'creator_analytics': True,
            'daily_joke_preview': True,
            'mature_content_addon': False,
        },
        limits={
            'mystery_box_rolls_per_day': 20,
            'submissions_per_day': 50,
            'daily_jokes_per_day': 5,
            'daily_joke_history_days': 365,
        },
    ),
]


def seed_plans(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    for data in PLANS:
        Plan.objects.update_or_create(slug=data['slug'], defaults=data)


def reverse_seed(apps, schema_editor):
    # Safe no-op: don't delete plans on rollback — data may have Subscriptions.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_plans, reverse_code=reverse_seed),
    ]
