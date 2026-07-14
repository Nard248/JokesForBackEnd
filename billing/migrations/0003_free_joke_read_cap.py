"""Seed the freemium punchline paywall's daily read cap onto each plan.

Free tier = 10 distinct joke reveals/day (punchline withheld server-side past
the cap). Paid tiers (supporter, creator_pro) = None (unlimited).

Merges into each plan's existing ``limits`` JSON without disturbing the other
keys. Reverse removes only the key this migration added.
"""
from django.db import migrations

READ_CAPS = {
    'free': 10,
    'supporter': None,      # None => unlimited (billing.entitlements.get_limit)
    'creator_pro': None,
}

KEY = 'free_joke_reads_per_day'


def set_read_caps(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    for slug, value in READ_CAPS.items():
        try:
            plan = Plan.objects.get(slug=slug)
        except Plan.DoesNotExist:
            continue
        limits = dict(plan.limits or {})
        limits[KEY] = value
        plan.limits = limits
        plan.save(update_fields=['limits'])


def unset_read_caps(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    for slug in READ_CAPS:
        try:
            plan = Plan.objects.get(slug=slug)
        except Plan.DoesNotExist:
            continue
        limits = dict(plan.limits or {})
        limits.pop(KEY, None)
        plan.limits = limits
        plan.save(update_fields=['limits'])


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0002_seed_plans'),
    ]

    operations = [
        migrations.RunPython(set_read_caps, reverse_code=unset_read_caps),
    ]
