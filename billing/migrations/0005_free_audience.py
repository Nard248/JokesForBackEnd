"""Retire reader purchase limits and Supporter sales without changing contracts.

Existing subscriptions, prices and Stripe identifiers remain intact. A rollback
does not silently reintroduce paywalls or reopen sales of a retired plan.
"""
from django.db import migrations


def free_audience(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    plans = Plan.objects.using(schema_editor.connection.alias)
    for plan in plans.all().iterator():
        limits = dict(plan.limits or {})
        limits.update({
            'free_joke_reads_per_day': None,
            'mystery_box_rolls_per_day': None,
            'daily_joke_history_days': None,
            'daily_jokes_per_day': None,
        })
        plan.limits = limits
        plan.save(using=schema_editor.connection.alias, update_fields=['limits'])
    plans.filter(slug='supporter').update(is_active=False, is_public=False)


class Migration(migrations.Migration):
    dependencies = [('billing', '0004_tip')]
    operations = [migrations.RunPython(free_audience, reverse_code=migrations.RunPython.noop)]
