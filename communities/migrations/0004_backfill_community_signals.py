from django.db import migrations

# Frozen copy of the communities.materialize signal vocabulary at the time of this
# migration. Pruning old repeated shares is an optimisation, not needed for
# correctness, so the backfill mirrors every positive row. Idempotent.
SOURCES = (
    ('jokes', 'JokeReaction', 'like', 'updated_at', "reaction IN ('lol', 'crying')"),
    ('jokes', 'Favorite', 'favorite', 'created_at', 'TRUE'),
    ('jokes', 'SavedJoke', 'save', 'created_at', 'TRUE'),
    ('jokes', 'ShareEvent', 'share', 'created_at', 'user_id IS NOT NULL'),
)


def backfill(apps, schema_editor):
    table = apps.get_model('communities', 'CommunitySignal')._meta.db_table
    select = ' UNION ALL '.join(
        f"SELECT user_id, joke_id, '{kind}', id, {stamp} FROM {apps.get_model(app, model)._meta.db_table} "
        f'WHERE {where}'
        for app, model, kind, stamp, where in SOURCES
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO {table} (user_id, joke_id, kind, source_id, occurred_at) {select} '
            'ON CONFLICT (kind, source_id) DO NOTHING'
        )


class Migration(migrations.Migration):
    dependencies = [('communities', '0003_community_signal')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
