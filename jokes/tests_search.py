"""PostgreSQL integration coverage for the public, unified joke search."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from io import StringIO
from queue import Queue
from time import monotonic, sleep
from unittest.mock import patch

from django.core.management import call_command
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from jokes.models import (
    AgeRating,
    ContextTag,
    Country,
    CultureTag,
    Format,
    Joke,
    Language,
    Source,
    Tone,
)


class UnifiedJokeSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.format = Format.objects.create(
            name='Quipformat', slug='quipformat', description='Framedescriptor',
        )
        cls.age = AgeRating.objects.create(
            name='Gentlerating', slug='gentlerating', description='Ratingdescriptor',
        )
        cls.language = Language.objects.get(code='en')
        cls.language.name = 'Testlanguage'
        cls.language.save(update_fields=['name'])
        cls.source = Source.objects.create(name='Attributionname', description='Sourcedescriptor')

    def make_joke(self, **values):
        joke = Joke(
            **{
                'text': 'Ordinary comedy', 'format': self.format,
                'age_rating': self.age, 'language': self.language, **values,
            },
        )
        Joke.all_objects.bulk_create([joke])
        return joke

    def search_ids(self, query, **kwargs):
        return list(Joke.objects.search(query, **kwargs).filter(format=self.format)
                    .values_list('pk', flat=True))

    def test_searches_each_content_field_and_dialogue_without_speaker_metadata(self):
        for field, value, term in [
            ('text', 'Textmatch', 'textmatch'),
            ('setup', 'Setupmatch', 'setupmatch'),
            ('punchline', 'Punchlinematch', 'punchlinematch'),
            ('lines', ['Knock knock', 'Dialogueanswer'], 'dialogueanswer'),
        ]:
            with self.subTest(field=field):
                joke = self.make_joke(**{field: value})
                self.assertEqual(self.search_ids(term), [joke.pk])

    def test_searches_all_public_classification_and_source_fields(self):
        joke = self.make_joke(source=self.source)
        joke.tones.add(Tone.objects.create(
            name='Categoryname', slug='categoryslug', description='Categorydescriptor',
        ))
        joke.context_tags.add(ContextTag.objects.create(
            name='Themename', slug='themeslug', description='Themedescriptor',
        ))
        joke.culture_tags.add(CultureTag.objects.create(
            name='Culturename', slug='cultureslug', description='Culturedescriptor',
        ))
        for term in [
            'categoryname', 'categoryslug', 'categorydescriptor',
            'themename', 'themeslug', 'themedescriptor',
            'culturename', 'cultureslug', 'culturedescriptor',
            'quipformat', 'framedescriptor', 'gentlerating', 'ratingdescriptor',
            'testlanguage', 'en', 'attributionname', 'sourcedescriptor',
        ]:
            with self.subTest(term=term):
                self.assertEqual(self.search_ids(term), [joke.pk])

    def test_cross_field_query_combines_content_and_category(self):
        joke = self.make_joke(punchline='Astronaut')
        joke.tones.add(Tone.objects.create(name='Whimsical', slug='whimsical'))
        self.assertEqual(self.search_ids('astronaut whimsical'), [joke.pk])

    def test_multiple_matching_classification_filters_return_one_joke(self):
        joke = self.make_joke(text='Filteredmatch')
        joke.tones.add(
            Tone.objects.create(name='Firstfilter', slug='firstfilter'),
            Tone.objects.create(name='Secondfilter', slug='secondfilter'),
        )
        joke.context_tags.add(
            ContextTag.objects.create(name='Firsttheme', slug='firsttheme'),
            ContextTag.objects.create(name='Secondtheme', slug='secondtheme'),
        )
        self.assertEqual(self.search_ids('filteredmatch', filters={
            'tones': ['firstfilter', 'secondfilter'],
            'context_tags': ['firsttheme', 'secondtheme'],
        }), [joke.pk])

    def test_content_matches_rank_above_category_then_description(self):
        content = self.make_joke(punchline='Telescopes')
        category = self.make_joke()
        descriptor = self.make_joke()
        category.tones.add(Tone.objects.create(name='Telescopes', slug='astral'))
        descriptor.context_tags.add(ContextTag.objects.create(
            name='Space', slug='space', description='Telescopes',
        ))
        self.assertEqual(self.search_ids('telescopes'), [content.pk, category.pk, descriptor.pk])

    def test_rank_ties_are_deterministic_by_date_and_id(self):
        older = self.make_joke(text='Constellation')
        newer = self.make_joke(text='Constellation')
        Joke.all_objects.filter(pk__in=[older.pk, newer.pk]).update(created_at=timezone.now())
        self.assertEqual(self.search_ids('constellation'), [newer.pk, older.pk])

    def test_bulk_content_and_dialogue_updates_replace_old_terms(self):
        joke = self.make_joke(text='Oldcontent', lines=['Olddialogue'])
        Joke.all_objects.filter(pk=joke.pk).update(text='Newcontent', lines=['Newdialogue'])
        self.assertEqual(self.search_ids('oldcontent OR olddialogue'), [])
        self.assertEqual(self.search_ids('newcontent newdialogue'), [joke.pk])

    def test_full_save_cannot_clear_database_generated_vectors(self):
        joke = self.make_joke(text='Persistentcontent')
        # INSERT triggers update the database, not this in-memory model.
        self.assertIsNone(joke.search_vector)
        with patch('jokes.models.Joke._generate_share_image'):
            joke.editorial_status = 'native_reviewed'
            joke.save()
        self.assertEqual(self.search_ids('persistentcontent'), [joke.pk])

    def test_stale_full_save_preserves_new_relation_terms_in_both_vectors(self):
        joke = self.make_joke(text='Stablecontent')
        joke.refresh_from_db()
        category = Tone.objects.create(name='Freshcategory', slug='freshcategory')
        joke.tones.add(category)
        with patch('jokes.models.Joke._generate_share_image'):
            joke.editorial_status = 'native_reviewed'
            joke.save()
        self.assertEqual(self.search_ids('freshcategory'), [joke.pk])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT search_vector_simple @@ plainto_tsquery('simple', 'freshcategory') "
                'FROM jokes_joke WHERE id = %s', [joke.pk],
            )
            self.assertTrue(cursor.fetchone()[0])

    def test_fk_reassignment_replaces_old_metadata(self):
        joke = self.make_joke(source=self.source)
        replacement = Source.objects.create(name='Replacementsource')
        Joke.all_objects.filter(pk=joke.pk).update(source=replacement)
        self.assertEqual(self.search_ids('attributionname'), [])
        self.assertEqual(self.search_ids('replacementsource'), [joke.pk])

    def test_category_add_remove_clear_and_set_stay_current(self):
        joke = self.make_joke()
        first = Tone.objects.create(name='Firstcategory', slug='firstcategory')
        second = Tone.objects.create(name='Secondcategory', slug='secondcategory')
        joke.tones.add(first)
        self.assertEqual(self.search_ids('firstcategory'), [joke.pk])
        joke.tones.set([second])
        self.assertEqual(self.search_ids('firstcategory'), [])
        self.assertEqual(self.search_ids('secondcategory'), [joke.pk])
        joke.tones.remove(second)
        self.assertEqual(self.search_ids('secondcategory'), [])
        joke.tones.add(first, second)
        joke.tones.clear()
        self.assertEqual(self.search_ids('firstcategory OR secondcategory'), [])

    def test_through_table_bulk_insert_update_and_delete_stay_current(self):
        joke = self.make_joke()
        other = self.make_joke()
        category = Tone.objects.create(name='Throughcategory', slug='throughcategory')
        through = Joke.tones.through
        through.objects.bulk_create([through(joke_id=joke.pk, tone_id=category.pk)])
        self.assertEqual(self.search_ids('throughcategory'), [joke.pk])
        through.objects.filter(joke_id=joke.pk).update(joke_id=other.pk)
        self.assertEqual(self.search_ids('throughcategory'), [other.pk])
        through.objects.filter(joke_id=other.pk).delete()
        self.assertEqual(self.search_ids('throughcategory'), [])

    def test_all_related_bulk_renames_refresh_existing_jokes(self):
        joke = self.make_joke(source=self.source)
        category = Tone.objects.create(name='Originalcategory', slug='categorykey')
        theme = ContextTag.objects.create(name='Originaltheme', slug='themekey')
        culture = CultureTag.objects.create(name='Originalculture', slug='culturekey')
        joke.tones.add(category)
        joke.context_tags.add(theme)
        joke.culture_tags.add(culture)
        for obj, original, replacement in [
            (self.format, 'quipformat', 'Updatedformat'),
            (self.age, 'gentlerating', 'Updatedrating'),
            (self.language, 'testlanguage', 'Updatedlanguage'),
            (self.source, 'attributionname', 'Updatedsource'),
            (category, 'originalcategory', 'Updatedcategory'),
            (theme, 'originaltheme', 'Updatedtheme'),
            (culture, 'originalculture', 'Updatedculture'),
        ]:
            with self.subTest(model=type(obj).__name__):
                type(obj).objects.filter(pk=obj.pk).update(name=replacement)
                self.assertEqual(self.search_ids(replacement), [joke.pk])
                # Format/rating keep their original slug, so those old terms remain valid.
                if obj not in (self.format, self.age):
                    self.assertEqual(self.search_ids(original), [])

    def test_deleting_category_and_nullable_source_removes_indexed_terms(self):
        joke = self.make_joke(source=self.source)
        category = Tone.objects.create(name='Deletedcategory', slug='deletedcategory')
        joke.tones.add(category)
        category.delete()
        self.source.delete()
        self.assertEqual(self.search_ids('deletedcategory OR attributionname'), [])
        self.assertEqual(self.search_ids('ordinary'), [joke.pk])

    def test_stemming_phrase_or_and_exclusion_semantics_are_preserved(self):
        exact = self.make_joke(text='Running lunar rabbits')
        split = self.make_joke(text='A rabbit takes a lunar holiday')
        comet = self.make_joke(text='Comet')
        self.assertEqual(self.search_ids('run'), [exact.pk])
        self.assertEqual(self.search_ids('"lunar rabbits"'), [exact.pk])
        self.assertEqual(set(self.search_ids('rabbit OR comet')), {exact.pk, split.pk, comet.pk})
        self.assertEqual(self.search_ids('rabbit -holiday'), [exact.pk])

    def test_empty_query_browses_and_punctuation_does_not_match_everything(self):
        joke = self.make_joke()
        self.assertEqual(self.search_ids(' \t\n '), [joke.pk])
        self.assertEqual(self.search_ids('!!! ???'), [])
        self.assertEqual(self.search_ids('the and or'), [])

    def test_query_limits_and_control_characters_raise_validation_errors(self):
        for query in ['x' * 201, ' '.join(['x'] * 33), 'bad\x00query', 'bad\x1bquery']:
            with self.subTest(query=repr(query)):
                with self.assertRaises(ValidationError) as raised:
                    Joke.objects.search(query)
                self.assertIn('q', raised.exception.detail)

    def test_query_normalization_keeps_websearch_operators(self):
        joke = self.make_joke(text='Lunar rabbits')
        self.assertEqual(self.search_ids('  "lunar rabbits"  OR\tcomet\n-holiday  '), [joke.pk])

    def test_exclusion_only_queries_do_not_scan_and_return_the_catalog(self):
        self.make_joke(text='Ordinary comedy')
        for query in ['-astronaut', '-astronaut OR -comet', 'the -astronaut']:
            with self.subTest(query=query):
                self.assertEqual(self.search_ids(query), [])

    def test_country_and_native_labels_stay_current_after_rename_and_removal(self):
        joke = self.make_joke(cultural_note='Contextdescriptor')
        country = Country.objects.create(code='ZZ', name='Countrylabel', native_name='Երկիր')
        culture = CultureTag.objects.create(name='Culturelabel', slug='culturekey', native_name='Մշակույթ')
        joke.countries.add(country)
        joke.culture_tags.add(culture)
        for term in ['countrylabel', 'zz', 'Երկիր', 'Մշակույթ', 'contextdescriptor']:
            with self.subTest(term=term):
                self.assertEqual(self.search_ids(term), [joke.pk])
        Country.objects.filter(pk=country.pk).update(native_name='Հայրենիք')
        self.assertEqual(self.search_ids('Երկիր'), [])
        self.assertEqual(self.search_ids('Հայրենիք'), [joke.pk])
        joke.countries.clear()
        self.assertEqual(self.search_ids('countrylabel OR Հայրենիք'), [])

    def test_non_english_content_uses_simple_query_and_preserves_exclusions(self):
        language = Language.objects.create(code='zz', name='Otherlanguage', native_name='Լեզու')
        joke = self.make_joke(text='հայերեն կատակ running', language=language)
        self.assertEqual(self.search_ids('հայերեն'), [joke.pk])
        self.assertEqual(self.search_ids('Լեզու'), [joke.pk])
        self.assertEqual(self.search_ids('running'), [joke.pk])
        self.assertEqual(self.search_ids('run'), [])
        self.assertEqual(self.search_ids('հայերեն -running'), [])
        self.assertEqual(self.search_ids('-missing'), [])

    def test_removal_and_tier_constraints_are_preserved(self):
        allowed = self.make_joke(text='Boundaryword')
        self.make_joke(text='Boundaryword', is_removed=True)
        self.make_joke(text='Boundaryword', content_tier='tier_2')
        self.make_joke(text='Boundaryword', content_tier='tier_3')
        self.assertEqual(self.search_ids('boundaryword', allowed_tiers=['tier_1']), [allowed.pk])

    def test_rebuild_recovers_missing_documents_including_removed_jokes(self):
        joke = self.make_joke(lines=['Rebuilddialogue'], is_removed=True)
        joke.tones.add(Tone.objects.create(name='Rebuildcategory', slug='rebuildcategory'))
        Joke.all_objects.filter(pk=joke.pk).update(search_vector=None)
        call_command('rebuild_search_index', stdout=StringIO())
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT search_vector @@ websearch_to_tsquery(%s, %s) FROM jokes_joke WHERE id = %s',
                ['english', 'rebuilddialogue rebuildcategory', joke.pk],
            )
            self.assertTrue(cursor.fetchone()[0])

    def test_unrelated_updates_do_not_rebuild_the_vector(self):
        joke = self.make_joke()
        Joke.all_objects.filter(pk=joke.pk).update(search_vector=None)
        Joke.all_objects.filter(pk=joke.pk).update(is_removed=True)
        joke.refresh_from_db()
        self.assertIsNone(joke.search_vector)

    def test_migration_install_is_replayable_after_interrupted_backfill(self):
        migration = import_module('jokes.migrations.0041_unified_joke_search')
        with connection.cursor() as cursor:
            cursor.execute(migration.Migration.operations[3].sql)
            cursor.execute(migration.Migration.operations[3].sql)
        joke = self.make_joke(lines=['Replaydialogue'])
        joke.tones.add(Tone.objects.create(name='Replaycategory', slug='replaycategory'))
        self.assertEqual(self.search_ids('replaydialogue replaycategory'), [joke.pk])


class ConcurrentSearchIndexTests(TransactionTestCase):
    """Real concurrent connections exercise row locks and fresh SQL snapshots."""

    # Match ConcurrentTelemetryTests: suppress post_migrate during flush so
    # its serialized taxonomy/content-type snapshot can be restored safely.
    serialized_rollback = True

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        # The final flush would otherwise leave migration-seeded lookups empty
        # for later classes and the next --keepdb run (billing convention).
        connection.creation.deserialize_db_from_string(connection._test_serialized_contents)

    def setUp(self):
        fmt, _ = Format.objects.get_or_create(slug='concurrent', defaults={'name': 'Concurrent'})
        age, _ = AgeRating.objects.get_or_create(slug='concurrent', defaults={'name': 'Concurrent'})
        language, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
        self.joke = Joke(text='Concurrency', format=fmt, age_rating=age, language=language)
        Joke.all_objects.bulk_create([self.joke])
        self.first = Tone.objects.create(name='Firstconcurrent', slug='firstconcurrent')
        self.second = Tone.objects.create(name='Secondconcurrent', slug='secondconcurrent')

    def add_in_thread(self, category_id, pid_queue):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute('SELECT pg_backend_pid()')
                pid_queue.put(cursor.fetchone()[0])
            Joke.tones.through.objects.create(joke_id=self.joke.pk, tone_id=category_id)
        finally:
            connection.close()

    def wait_for_lock(self, pid):
        deadline = monotonic() + 3
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT cardinality(pg_blocking_pids(%s)) > 0', [pid])
                if cursor.fetchone()[0]:
                    return
            sleep(0.01)
        self.fail('Concurrent writer did not reach the expected database lock.')

    def test_concurrent_category_additions_preserve_both_terms(self):
        pid_queue = Queue()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                Joke.all_objects.select_for_update(no_key=True).get(pk=self.joke.pk)
                self.joke.tones.add(self.first)
                future = executor.submit(self.add_in_thread, self.second.pk, pid_queue)
                self.wait_for_lock(pid_queue.get(timeout=3))
            future.result(timeout=6)
        self.assertEqual(
            list(Joke.objects.search('firstconcurrent secondconcurrent').values_list('pk', flat=True)),
            [self.joke.pk],
        )

    def test_category_added_during_a_rename_indexes_the_committed_name(self):
        pid_queue = Queue()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                Tone.objects.filter(pk=self.first.pk).update(name='Renamedconcurrent')
                future = executor.submit(self.add_in_thread, self.first.pk, pid_queue)
                self.wait_for_lock(pid_queue.get(timeout=3))
            future.result(timeout=6)
        self.assertEqual(
            list(Joke.objects.search('renamedconcurrent').values_list('pk', flat=True)),
            [self.joke.pk],
        )
