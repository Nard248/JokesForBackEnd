"""Replace only the original seed copy; preserve customized merchant catalog data."""
from django.db import migrations


def update_seed_copy(apps, schema_editor):
    plans = apps.get_model('billing', 'Plan').objects.using(schema_editor.connection.alias)
    plans.filter(slug='creator_pro', name='Creator Pro (PLACEHOLDER)').update(name='Creator Pro')
    plans.filter(
        slug='creator_pro',
        description='Power-user tier — PLACEHOLDER price, edit before launch.',
    ).update(description='Explore your content performance and export creator insights. Reading stays free.')
    plans.filter(slug='supporter', name='Supporter (PLACEHOLDER)').update(name='Supporter')
    plans.filter(
        slug='supporter',
        description='Support the platform — PLACEHOLDER price, edit before launch.',
    ).update(description='Legacy subscription. Existing subscribers can manage billing in the customer portal.')
    plans.filter(slug='free', description='Get started with JokesFor at no cost.').update(
        description='Read and discover jokes for free, publish your own, and see basic creator insights.',
    )


class Migration(migrations.Migration):
    dependencies = [('billing', '0008_subscriptioncheckout')]
    operations = [migrations.RunPython(update_seed_copy, migrations.RunPython.noop)]
