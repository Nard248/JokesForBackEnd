from django.db import migrations


def enable(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    for plan in Plan.objects.using(schema_editor.connection.alias).filter(slug='creator_pro'):
        features = dict(plan.features or {})
        features['creator_community_insights'] = True
        plan.features = features
        plan.save(update_fields=['features'])


def disable(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    for plan in Plan.objects.using(schema_editor.connection.alias).filter(slug='creator_pro'):
        features = dict(plan.features or {})
        features.pop('creator_community_insights', None)
        plan.features = features
        plan.save(update_fields=['features'])


class Migration(migrations.Migration):
    dependencies = [('billing', '0009_creator_catalog_labels')]
    operations = [migrations.RunPython(enable, disable)]
