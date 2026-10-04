"""Keep indexed search documents transactionally in sync with their source rows.

The functions are deliberately frozen here: future changes require a migration,
not an import of mutable application code. Backfill commits bounded batches.
"""

import pgtrigger.migrations
from django.db import migrations, transaction


FUNCTIONS_SQL = r"""
CREATE OR REPLACE FUNCTION jokes_refresh_search_document(target_id bigint)
RETURNS void LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    joke_row jokes_joke%ROWTYPE;
    content_text text;
    label_text text;
    description_text text;
BEGIN
    -- Serialize competing content/relation edits *before* reading their values.
    -- Separate statements in this VOLATILE function take fresh READ COMMITTED
    -- snapshots after a lock wait, so the last writer indexes committed data.
    -- NO KEY UPDATE also permits concurrent through-table FK KEY SHARE locks;
    -- FOR UPDATE would create avoidable lock-upgrade deadlocks on relation adds.
    SELECT * INTO joke_row FROM jokes_joke WHERE id = target_id FOR NO KEY UPDATE;
    IF NOT FOUND THEN RETURN; END IF;

    -- A concurrent taxonomy rename must not miss an as-yet-uncommitted new
    -- relation. SHARE locks conflict with name/description updates (unlike FK
    -- KEY SHARE locks). The renamer either sees the committed relation or this
    -- refresher waits and reads the renamed value in the following statement.
    PERFORM 1 FROM jokes_format WHERE id = joke_row.format_id FOR SHARE;
    PERFORM 1 FROM jokes_agerating WHERE id = joke_row.age_rating_id FOR SHARE;
    PERFORM 1 FROM jokes_language WHERE id = joke_row.language_id FOR SHARE;
    PERFORM 1 FROM jokes_source WHERE id = joke_row.source_id FOR SHARE;
    PERFORM 1 FROM jokes_tone t JOIN jokes_joke_tones r ON r.tone_id = t.id
        WHERE r.joke_id = target_id ORDER BY t.id FOR SHARE OF t;
    PERFORM 1 FROM jokes_contexttag t JOIN jokes_joke_context_tags r ON r.contexttag_id = t.id
        WHERE r.joke_id = target_id ORDER BY t.id FOR SHARE OF t;
    PERFORM 1 FROM jokes_culturetag t JOIN jokes_joke_culture_tags r ON r.culturetag_id = t.id
        WHERE r.joke_id = target_id ORDER BY t.id FOR SHARE OF t;
    PERFORM 1 FROM jokes_country t JOIN jokes_joke_countries r ON r.country_id = t.id
        WHERE r.joke_id = target_id ORDER BY t.id FOR SHARE OF t;

    content_text := concat_ws(' ', joke_row.text, joke_row.setup, joke_row.punchline,
        (SELECT string_agg(item #>> '{}', ' ' ORDER BY position)
         FROM jsonb_array_elements(
             CASE WHEN jsonb_typeof(joke_row.lines) = 'array'
                  THEN joke_row.lines ELSE '[]'::jsonb END
         ) WITH ORDINALITY AS dialogue(item, position)
         WHERE jsonb_typeof(item) = 'string'));

    SELECT string_agg(labels, ' ' ORDER BY axis, id),
           concat_ws(' ', joke_row.cultural_note, string_agg(description, ' ' ORDER BY axis, id))
    INTO label_text, description_text
    FROM (
        SELECT 1 AS axis, id, concat_ws(' ', name, slug) AS labels, description
            FROM jokes_format WHERE id = joke_row.format_id
        UNION ALL
        SELECT 2, id, concat_ws(' ', name, slug), description
            FROM jokes_agerating WHERE id = joke_row.age_rating_id
        UNION ALL
        SELECT 3, id, concat_ws(' ', name, native_name, code), ''
            FROM jokes_language WHERE id = joke_row.language_id
        UNION ALL
        SELECT 4, id, name, description FROM jokes_source WHERE id = joke_row.source_id
        UNION ALL
        SELECT 5, t.id, concat_ws(' ', t.name, t.slug), t.description
            FROM jokes_tone t JOIN jokes_joke_tones r ON r.tone_id = t.id
            WHERE r.joke_id = target_id
        UNION ALL
        SELECT 6, t.id, concat_ws(' ', t.name, t.slug), t.description
            FROM jokes_contexttag t JOIN jokes_joke_context_tags r ON r.contexttag_id = t.id
            WHERE r.joke_id = target_id
        UNION ALL
        SELECT 7, t.id, concat_ws(' ', t.name, t.native_name, t.slug), t.description
            FROM jokes_culturetag t JOIN jokes_joke_culture_tags r ON r.culturetag_id = t.id
            WHERE r.joke_id = target_id
        UNION ALL
        SELECT 8, t.id, concat_ws(' ', t.name, t.native_name, t.code), ''
            FROM jokes_country t JOIN jokes_joke_countries r ON r.country_id = t.id
            WHERE r.joke_id = target_id
    ) metadata;

    UPDATE jokes_joke SET
        search_vector =
            setweight(to_tsvector('pg_catalog.english', coalesce(content_text, '')), 'A') ||
            setweight(to_tsvector('pg_catalog.english', coalesce(label_text, '')), 'B') ||
            setweight(to_tsvector('pg_catalog.english', coalesce(description_text, '')), 'C'),
        search_vector_simple =
            setweight(to_tsvector('pg_catalog.simple', coalesce(content_text, '')), 'A') ||
            setweight(to_tsvector('pg_catalog.simple', coalesce(label_text, '')), 'B') ||
            setweight(to_tsvector('pg_catalog.simple', coalesce(description_text, '')), 'C')
    WHERE id = target_id;
END;
$$;

CREATE OR REPLACE FUNCTION jokes_search_content_changed()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM jokes_refresh_search_document(NEW.id);
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION jokes_search_preserve_vectors()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Django full saves include derived fields from the in-memory instance.
    -- They may be NULL after INSERT or stale after a related-row edit. Keep
    -- the current database document; the AFTER trigger rebuilds it when a
    -- source value changed. Vector-only refresh/repair writes bypass this.
    NEW.search_vector := OLD.search_vector;
    NEW.search_vector_simple := OLD.search_vector_simple;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION jokes_search_relation_changed()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target_id bigint;
    target_ids bigint[] := '{}';
BEGIN
    IF TG_OP <> 'INSERT' THEN target_ids := array_append(target_ids, OLD.joke_id); END IF;
    IF TG_OP <> 'DELETE' THEN target_ids := array_append(target_ids, NEW.joke_id); END IF;
    FOR target_id IN SELECT DISTINCT id FROM unnest(target_ids) AS targets(id) ORDER BY id
    LOOP
        PERFORM jokes_refresh_search_document(target_id);
    END LOOP;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION jokes_search_taxonomy_changed()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target_id bigint;
BEGIN
    -- TG_ARGV is fixed by migration DDL, never supplied by a request.
    FOR target_id IN EXECUTE TG_ARGV[0] USING NEW.id LOOP
        PERFORM jokes_refresh_search_document(target_id);
    END LOOP;
    RETURN NULL;
END;
$$;
"""

CONTENT_COLUMNS = (
    'text', 'setup', 'punchline', 'lines', 'format_id', 'age_rating_id',
    'language_id', 'source_id', 'cultural_note',
)
RELATIONS = (
    ('tones', 'tone_id'), ('context_tags', 'contexttag_id'),
    ('culture_tags', 'culturetag_id'), ('countries', 'country_id'),
)
TAXONOMIES = (
    ('format', ('name', 'slug', 'description'), 'SELECT id FROM jokes_joke WHERE format_id = $1 ORDER BY id'),
    ('agerating', ('name', 'slug', 'description'), 'SELECT id FROM jokes_joke WHERE age_rating_id = $1 ORDER BY id'),
    ('language', ('name', 'native_name', 'code'), 'SELECT id FROM jokes_joke WHERE language_id = $1 ORDER BY id'),
    ('source', ('name', 'description'), 'SELECT id FROM jokes_joke WHERE source_id = $1 ORDER BY id'),
    ('tone', ('name', 'slug', 'description'), 'SELECT joke_id FROM jokes_joke_tones WHERE tone_id = $1 ORDER BY joke_id'),
    ('contexttag', ('name', 'slug', 'description'), 'SELECT joke_id FROM jokes_joke_context_tags WHERE contexttag_id = $1 ORDER BY joke_id'),
    ('culturetag', ('name', 'native_name', 'slug', 'description'), 'SELECT joke_id FROM jokes_joke_culture_tags WHERE culturetag_id = $1 ORDER BY joke_id'),
    ('country', ('name', 'native_name', 'code'), 'SELECT joke_id FROM jokes_joke_countries WHERE country_id = $1 ORDER BY joke_id'),
)


def changed(columns):
    old = ', '.join(f'OLD.{column}' for column in columns)
    new = ', '.join(f'NEW.{column}' for column in columns)
    return f'ROW({old}) IS DISTINCT FROM ROW({new})'


TRIGGERS_SQL = f"""
CREATE TRIGGER jokes_search_insert AFTER INSERT ON jokes_joke
    FOR EACH ROW EXECUTE FUNCTION jokes_search_content_changed();
CREATE TRIGGER jokes_search_preserve BEFORE UPDATE OF {', '.join(CONTENT_COLUMNS)} ON jokes_joke
    FOR EACH ROW EXECUTE FUNCTION jokes_search_preserve_vectors();
CREATE TRIGGER jokes_search_update AFTER UPDATE OF {', '.join(CONTENT_COLUMNS)} ON jokes_joke
    FOR EACH ROW WHEN ({changed(CONTENT_COLUMNS)})
    EXECUTE FUNCTION jokes_search_content_changed();
"""
DROP_SQL = """
DROP TRIGGER IF EXISTS jokes_search_insert ON jokes_joke;
DROP TRIGGER IF EXISTS jokes_search_preserve ON jokes_joke;
DROP TRIGGER IF EXISTS jokes_search_update ON jokes_joke;
"""
for relation, related_id in RELATIONS:
    TRIGGERS_SQL += f"""
    CREATE TRIGGER jokes_search_relation_write AFTER INSERT OR DELETE ON jokes_joke_{relation}
        FOR EACH ROW EXECUTE FUNCTION jokes_search_relation_changed();
    CREATE TRIGGER jokes_search_relation_update AFTER UPDATE OF joke_id, {related_id}
        ON jokes_joke_{relation} FOR EACH ROW
        WHEN ({changed(('joke_id', related_id))})
        EXECUTE FUNCTION jokes_search_relation_changed();
    """
    DROP_SQL += f"""
    DROP TRIGGER IF EXISTS jokes_search_relation_write ON jokes_joke_{relation};
    DROP TRIGGER IF EXISTS jokes_search_relation_update ON jokes_joke_{relation};
    """
for taxonomy, columns, query in TAXONOMIES:
    TRIGGERS_SQL += f"""
    CREATE TRIGGER jokes_search_taxonomy_update AFTER UPDATE OF {', '.join(columns)}
        ON jokes_{taxonomy} FOR EACH ROW WHEN ({changed(columns)})
        EXECUTE FUNCTION jokes_search_taxonomy_changed('{query}');
    """
    DROP_SQL += f'DROP TRIGGER IF EXISTS jokes_search_taxonomy_update ON jokes_{taxonomy};\n'
DROP_SQL += """
DROP FUNCTION IF EXISTS jokes_search_taxonomy_changed();
DROP FUNCTION IF EXISTS jokes_search_relation_changed();
DROP FUNCTION IF EXISTS jokes_search_content_changed();
DROP FUNCTION IF EXISTS jokes_search_preserve_vectors();
DROP FUNCTION IF EXISTS jokes_refresh_search_document(bigint);
"""


def backfill(apps, schema_editor):
    joke = apps.get_model('jokes', 'Joke')
    alias = schema_editor.connection.alias
    last_id = 0
    while ids := list(joke._base_manager.using(alias).filter(pk__gt=last_id)
                     .order_by('pk').values_list('pk', flat=True)[:500]):
        with transaction.atomic(using=alias), schema_editor.connection.cursor() as cursor:
            cursor.execute(
                'SELECT jokes_refresh_search_document(id) FROM unnest(%s::bigint[]) AS targets(id)',
                [ids],
            )
        last_id = ids[-1]


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('jokes', '0040_seed_discovery_locales')]
    operations = [
        # Runs last on rollback, once the original pgtrigger functions return.
        migrations.RunSQL(migrations.RunSQL.noop, 'UPDATE jokes_joke SET text = text'),
        pgtrigger.migrations.RemoveTrigger(model_name='joke', name='joke_search_vector_update'),
        pgtrigger.migrations.RemoveTrigger(model_name='joke', name='joke_simple_search_update'),
        # Replay-safe if a later backfill batch fails in this non-atomic migration.
        migrations.RunSQL(DROP_SQL + FUNCTIONS_SQL + TRIGGERS_SQL, DROP_SQL),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
