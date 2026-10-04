from django.db import migrations


def enable_pro_workbench(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    for plan in Plan.objects.using(schema_editor.connection.alias).filter(slug='creator_pro'):
        features = dict(plan.features or {})
        features.update(creator_content_explorer=True, creator_exports=True)
        plan.features = features
        plan.save(update_fields=['features'])


def remove_workbench_features(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    for plan in Plan.objects.using(schema_editor.connection.alias).filter(slug='creator_pro'):
        features = dict(plan.features or {})
        features.pop('creator_content_explorer', None)
        features.pop('creator_exports', None)
        plan.features = features
        plan.save(update_fields=['features'])


class Migration(migrations.Migration):
    dependencies = [('billing', '0006_planprice')]
    operations = [migrations.RunPython(enable_pro_workbench, remove_workbench_features)]
