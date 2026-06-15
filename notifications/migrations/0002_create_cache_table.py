from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    # createcachetable is idempotent and respects the target connection, so it
    # works for prod migrate and for the test DB. Uses the LOCATION from CACHES.
    call_command('createcachetable', database=schema_editor.connection.alias)


def drop_cache_table(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        cur.execute('DROP TABLE IF EXISTS jokesfor_cache')


class Migration(migrations.Migration):
    dependencies = [
        ('notifications', '0001_initial'),
    ]
    operations = [
        migrations.RunPython(create_cache_table, drop_cache_table),
    ]
