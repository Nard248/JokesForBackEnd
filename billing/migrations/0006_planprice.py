import django.db.models.deletion
from django.db import migrations, models


def seed_price_history(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    PlanPrice = apps.get_model('billing', 'PlanPrice')
    Subscription = apps.get_model('billing', 'Subscription')
    for plan in Plan.objects.using(schema_editor.connection.alias).exclude(stripe_price_id=''):
        mapping, _ = PlanPrice.objects.using(schema_editor.connection.alias).get_or_create(
            stripe_price_id=plan.stripe_price_id, defaults={'plan_id': plan.pk},
        )
        if mapping.plan_id != plan.pk:
            raise ValueError('Conflicting catalog Stripe price mappings require reconciliation.')
    # A subscriber may still renew on a price the catalog replaced before this
    # migration existed. Preserve that known mapping too.
    for subscription in Subscription.objects.using(schema_editor.connection.alias).filter(
        plan__is_default=False,
        status__in=['active', 'trialing', 'past_due', 'unpaid', 'paused', 'incomplete'],
    ).exclude(stripe_price_id=''):
        mapping, _ = PlanPrice.objects.using(schema_editor.connection.alias).get_or_create(
            stripe_price_id=subscription.stripe_price_id,
            defaults={'plan_id': subscription.plan_id},
        )
        if mapping.plan_id != subscription.plan_id:
            raise ValueError('Conflicting historical Stripe price mappings require reconciliation.')


class Migration(migrations.Migration):
    dependencies = [('billing', '0005_free_audience')]

    operations = [
        migrations.CreateModel(
            name='PlanPrice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stripe_price_id', models.CharField(max_length=80, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stripe_prices', to='billing.plan')),
            ],
        ),
        migrations.RunPython(seed_price_history, migrations.RunPython.noop),
    ]
