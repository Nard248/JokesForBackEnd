"""Corpus validation must establish real coverage before any database writes."""

import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase


def corpus_fixture(root, *, count=1, target=200):
    collection = {
        'id': 'es-es-everyday', 'language': 'es', 'language_name': 'Spanish',
        'language_native_name': 'Español', 'country': 'ES', 'country_name': 'Spain',
        'country_native_name': 'España', 'culture': 'spain-everyday',
        'culture_name': 'Everyday Spain', 'culture_native_name': 'Vida cotidiana en España',
        'description': 'Original everyday observations set in Spain.',
        'locale': 'es-ES', 'categories': ['wholesome'], 'target_per_category': target,
    }
    records = [{
        'id': f'intl-test-es-{i}', 'collection': collection['id'],
        'category': 'wholesome', 'format': 'oneliner',
        'text': f'Mi calendario tiene {i + 2} lunes: lo diseñó mi despertador.',
        'age_rating': 'family-friendly', 'themes': ['work'],
        'cultural_note': 'An original everyday observation; no national trait is implied.',
    } for i in range(count)]
    manifest = {
        'version': 1,
        'provenance': {
            'kind': 'ai_original', 'native_reviewed': False,
            'description': 'Original AI-authored material; no native-speaker review claimed.',
        },
        'collections': [collection], 'files': ['es.json'],
    }
    (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (root / 'es.json').write_text(json.dumps(records), encoding='utf-8')
    return manifest, records


class InternationalCorpusValidationTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest, self.records = corpus_fixture(self.root)

    def load(self, **kwargs):
        from jokes.international_corpus import load_corpus
        return load_corpus(self.root / 'manifest.json', **kwargs)

    def write_records(self):
        (self.root / 'es.json').write_text(json.dumps(self.records), encoding='utf-8')

    def test_reports_distinct_primary_category_count_and_remaining_target(self):
        corpus = self.load()
        self.assertEqual(corpus.coverage[0]['count'], 1)
        self.assertEqual(corpus.coverage[0]['missing'], 199)
        self.assertFalse(corpus.complete)
        self.assertEqual(corpus.records[0]['text'], self.records[0]['text'])

    def test_require_complete_fails_with_explicit_collection_and_category(self):
        with self.assertRaisesRegex(ValueError, 'es-es-everyday/wholesome.*199'):
            self.load(require_complete=True)

    def test_duplicate_keys_rejected(self):
        self.records.append(dict(self.records[0], text='Otro texto distinto.'))
        self.write_records()
        with self.assertRaisesRegex(ValueError, 'Duplicate.*id'):
            self.load()

    def test_case_spacing_punctuation_and_unicode_variants_are_not_new_jokes(self):
        self.records[0]['text'] = 'Mi café pide vacaciones.'
        self.records.append(dict(self.records[0], id='other-id', text='  MI CAFE\u0301   PIDE VACACIONES!'))
        self.write_records()
        with self.assertRaisesRegex(ValueError, 'Duplicate.*text'):
            self.load()

    def test_unknown_category_does_not_count_as_supported(self):
        self.records[0]['category'] = 'imaginary'
        self.write_records()
        with self.assertRaisesRegex(ValueError, 'category'):
            self.load()

    def test_native_review_cannot_be_asserted_by_generated_manifest(self):
        self.manifest['provenance']['native_reviewed'] = True
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'review'):
            self.load()

    def test_no_file_traversal(self):
        self.manifest['files'] = ['../outside.json']
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'inside'):
            self.load()

    def test_setup_joke_requires_both_parts(self):
        self.records[0].update(format='setup', setup='¿Por qué?', punchline='')
        self.write_records()
        with self.assertRaisesRegex(ValueError, 'punchline'):
            self.load()

    def test_country_and_locale_must_agree(self):
        self.manifest['collections'][0]['locale'] = 'es-MX'
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'locale'):
            self.load()

    def test_unexpected_record_fields_fail_instead_of_losing_metadata(self):
        self.records[0]['native_reviewed'] = True
        self.write_records()
        with self.assertRaisesRegex(ValueError, 'Unknown record'):
            self.load()

    def test_complete_reports_all_declared_targets_even_empty_ones(self):
        self.manifest['collections'][0]['categories'].append('puns')
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        rows = {row['category']: row for row in self.load().coverage}
        self.assertEqual(rows['puns']['count'], 0)
        self.assertEqual(rows['puns']['missing'], 200)

    def test_noncanonical_identifiers_cannot_create_unreachable_content(self):
        self.manifest['collections'][0]['language'] = 'es '
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'canonical'):
            self.load()

    def test_noncanonical_record_id_is_rejected(self):
        self.records[0]['id'] = ' intl-test-es-0 '
        self.write_records()
        with self.assertRaisesRegex(ValueError, 'canonical'):
            self.load()

    def test_malformed_format_produces_validation_error(self):
        self.records[0]['format'] = []
        self.write_records()
        with self.assertRaisesRegex(ValueError, 'format'):
            self.load()

    def test_related_country_is_context_without_extra_quota_credit(self):
        self.manifest['context_countries'] = [
            {'code': 'FR', 'name': 'France', 'native_name': 'France'},
        ]
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        self.records[0]['related_countries'] = ['FR']
        self.write_records()
        corpus = self.load()
        self.assertEqual(corpus.records[0]['related_countries'], ['FR'])
        self.assertEqual(len(corpus.coverage), 1)
        self.assertEqual(corpus.coverage[0]['count'], 1)

    def test_related_countries_require_distinct_known_secondary_codes(self):
        for invalid in (['ZZ'], ['ES'], ['es'], 'ES', ['FR', 'FR'], [None]):
            with self.subTest(invalid=invalid):
                self.records[0]['related_countries'] = invalid
                self.write_records()
                with self.assertRaisesRegex(ValueError, 'related_countries'):
                    self.load()

    def test_context_country_definitions_are_canonical_and_unambiguous(self):
        for invalid in (
            [{'code': 'fr', 'name': 'France', 'native_name': 'France'}],
            [{'code': 'ES', 'name': 'Different country', 'native_name': 'Different'}],
            [{'code': 'FR', 'name': '', 'native_name': 'France'}],
        ):
            with self.subTest(invalid=invalid):
                self.manifest['context_countries'] = invalid
                (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.load()


class InternationalCorpusImportTests(TestCase):
    def setUp(self):
        from jokes.models import AgeRating, ContextTag, Format, Tone
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest, self.records = corpus_fixture(self.root)
        Format.objects.get_or_create(slug='oneliner', defaults={'name': 'One-liner'})
        AgeRating.objects.get_or_create(
            slug='family-friendly', defaults={'name': 'Family-friendly', 'min_age': 0},
        )
        Tone.objects.get_or_create(slug='wholesome', defaults={'name': 'Wholesome'})
        ContextTag.objects.get_or_create(slug='work', defaults={'name': 'Work'})

    def run_import(self, **kwargs):
        output = StringIO()
        call_command('import_international_jokes', manifest=str(self.root / 'manifest.json'),
                     stdout=output, **kwargs)
        return output.getvalue()

    def write_bundle(self):
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        (self.root / 'es.json').write_text(json.dumps(self.records), encoding='utf-8')

    def configure_country_context(self):
        self.manifest['context_countries'] = [
            {'code': 'NO', 'name': 'Norway', 'native_name': 'Norge'},
        ]
        self.manifest['collections'][0]['target_per_category'] = 1
        self.write_bundle()

    def test_import_is_idempotent_and_sets_context_and_truthful_provenance(self):
        from jokes.models import Joke
        before = Joke.all_objects.count()
        self.run_import()
        self.run_import()
        self.assertEqual(Joke.all_objects.count(), before + 1)
        joke = Joke.objects.get(seed_key='intl-test-es-0')
        self.assertEqual(joke.language.code, 'es')
        self.assertEqual(list(joke.countries.values_list('code', flat=True)), ['ES'])
        self.assertEqual(list(joke.culture_tags.values_list('slug', flat=True)), ['spain-everyday'])
        self.assertEqual(list(joke.tones.values_list('slug', flat=True)), ['wholesome'])
        self.assertEqual(joke.editorial_status, 'generated')
        self.assertEqual(joke.content_tier, 'tier_1')
        self.assertFalse(joke.share_image)
        self.assertIn('native', joke.source.description)

    def test_adult_age_rating_imports_as_mature_tier(self):
        """Same derivation as admin bulk-publish: min_age >= 18 never ships as tier_1."""
        from jokes.models import AgeRating, Joke
        AgeRating.objects.update_or_create(
            slug='adult', defaults={'name': 'Adult', 'min_age': 18},
        )
        self.records[0]['age_rating'] = 'adult'
        self.write_bundle()
        self.run_import()
        self.assertEqual(Joke.all_objects.get(seed_key='intl-test-es-0').content_tier, 'tier_2')

    def test_dry_run_performs_no_writes(self):
        from jokes.models import Joke, Source
        before = (Joke.all_objects.count(), Source.objects.count())
        self.assertIn('199', self.run_import(dry_run=True))
        self.assertEqual((Joke.all_objects.count(), Source.objects.count()), before)

    def test_related_country_browses_same_joke_without_inventing_collection(self):
        from rest_framework.test import APIRequestFactory

        from jokes.discovery import filter_discovery, locale_catalog
        from jokes.models import CulturalCollection, Joke

        self.manifest['context_countries'] = [
            {'code': 'NO', 'name': 'Norway', 'native_name': 'Norge'},
        ]
        self.manifest['collections'][0]['target_per_category'] = 1
        self.records[0]['related_countries'] = ['NO']
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        (self.root / 'es.json').write_text(json.dumps(self.records), encoding='utf-8')
        self.run_import(require_complete=True)
        self.run_import(require_complete=True)
        joke = Joke.objects.get(seed_key=self.records[0]['id'])
        self.assertSetEqual(set(joke.countries.values_list('code', flat=True)), {'ES', 'NO'})
        self.assertTrue(filter_discovery(Joke.objects.all(), {'country': 'NO'}).filter(pk=joke.pk).exists())
        self.assertFalse(CulturalCollection.objects.filter(language__code='es', country__code='NO').exists())
        request = APIRequestFactory().get('/')
        catalog = locale_catalog(request)
        norway = next(c for c in catalog['countries'] if c['code'] == 'NO')
        self.assertIn('es', norway['language_codes'])
        culture = next(c for c in catalog['cultures'] if c['slug'] == 'spain-everyday')
        self.assertIn('NO', culture['country_codes'])

    def test_unknown_database_taxonomy_rolls_back_metadata_too(self):
        from jokes.models import Country, Joke, Tone
        Tone.objects.filter(slug='wholesome').delete()
        before = (Country.objects.count(), Joke.all_objects.count())
        with self.assertRaisesRegex(CommandError, 'wholesome'):
            self.run_import()
        self.assertEqual((Country.objects.count(), Joke.all_objects.count()), before)

    def test_authored_country_drift_reports_mismatch_without_overwriting_editorial_links(self):
        from jokes.models import CultureTag, Joke

        self.configure_country_context()
        self.run_import(require_complete=True)
        self.records[0]['related_countries'] = ['NO']
        self.write_bundle()
        report = self.root / 'report.json'
        output = self.run_import(report=report)
        body = json.loads(report.read_text())
        self.assertTrue(body['authored_complete'])
        self.assertTrue(body['database']['public_complete'])
        self.assertFalse(body['database']['context_complete'])
        self.assertEqual(body['database']['context_mismatches'], [{
            'id': self.records[0]['id'], 'collection': 'es-es-everyday',
            'expected_countries': ['ES', 'NO'], 'actual_countries': ['ES'],
            'missing_countries': ['NO'],
        }])
        self.assertIn('country context mismatch', output)
        joke = Joke.objects.get(seed_key=self.records[0]['id'])
        self.assertSetEqual(set(joke.countries.values_list('code', flat=True)), {'ES'})
        culture = CultureTag.objects.get(slug='spain-everyday')
        self.assertFalse(culture.countries.filter(code='NO').exists())
        with self.assertRaisesRegex(CommandError, 'country context'):
            self.run_import(require_complete=True)

    def test_strict_country_context_failure_rolls_back_new_records(self):
        from jokes.models import CultureTag, Joke

        self.configure_country_context()
        self.run_import(require_complete=True)
        self.records[0]['related_countries'] = ['NO']
        self.records.append({
            **self.records[0], 'id': 'intl-test-es-new',
            'text': 'Mi ascensor celebra cada planta como un ascenso profesional.',
        })
        self.write_bundle()
        before = Joke.all_objects.count()
        with self.assertRaisesRegex(CommandError, 'country context'):
            self.run_import(require_complete=True)
        self.assertEqual(Joke.all_objects.count(), before)
        self.assertFalse(Joke.all_objects.filter(seed_key='intl-test-es-new').exists())
        self.assertFalse(CultureTag.objects.get(slug='spain-everyday').countries.filter(code='NO').exists())

    def test_editorially_removed_secondary_country_is_reported_and_preserved(self):
        from jokes.models import Country, CultureTag, Joke

        self.configure_country_context()
        self.records[0]['related_countries'] = ['NO']
        self.write_bundle()
        self.run_import(require_complete=True)
        joke = Joke.objects.get(seed_key=self.records[0]['id'])
        norway = Country.objects.get(code='NO')
        joke.countries.remove(norway)
        culture = CultureTag.objects.get(slug='spain-everyday')
        culture.countries.remove(norway)
        report = self.root / 'report.json'
        self.run_import(report=report)
        stats = json.loads(report.read_text())['database']
        self.assertTrue(stats['public_complete'])
        self.assertFalse(stats['context_complete'])
        self.assertEqual(stats['context_mismatches'][0]['missing_countries'], ['NO'])
        self.assertFalse(joke.countries.filter(code='NO').exists())
        self.assertFalse(culture.countries.filter(code='NO').exists())

    def test_extra_editorial_countries_are_accepted_and_preserved(self):
        from jokes.models import Country, Joke

        self.configure_country_context()
        self.run_import(require_complete=True)
        joke = Joke.objects.get(seed_key=self.records[0]['id'])
        joke.countries.add(Country.objects.get(code='NO'))
        report = self.root / 'report.json'
        self.run_import(require_complete=True, report=report)
        stats = json.loads(report.read_text())['database']
        self.assertTrue(stats['context_complete'])
        self.assertEqual(stats['context_mismatches'], [])
        self.assertSetEqual(set(joke.countries.values_list('code', flat=True)), {'ES', 'NO'})

    def test_missing_primary_country_is_also_a_context_mismatch(self):
        from jokes.models import Joke

        self.run_import()
        joke = Joke.objects.get(seed_key=self.records[0]['id'])
        joke.countries.clear()
        report = self.root / 'report.json'
        self.run_import(report=report)
        stats = json.loads(report.read_text())['database']
        self.assertFalse(stats['context_complete'])
        self.assertEqual(stats['context_mismatches'][0]['missing_countries'], ['ES'])
        self.assertFalse(joke.countries.exists())

    def test_removed_records_do_not_propagate_authored_context_drift(self):
        from jokes.models import CultureTag, Joke

        self.configure_country_context()
        self.run_import()
        Joke.all_objects.filter(seed_key=self.records[0]['id']).update(is_removed=True)
        self.records[0]['related_countries'] = ['NO']
        self.write_bundle()
        report = self.root / 'report.json'
        self.run_import(report=report)
        stats = json.loads(report.read_text())['database']
        self.assertTrue(stats['context_complete'])
        self.assertEqual(stats['context_mismatches'], [])
        self.assertEqual(stats['removed'], 1)
        self.assertFalse(CultureTag.objects.get(slug='spain-everyday').countries.filter(code='NO').exists())

    def test_new_record_can_support_country_metadata_despite_another_records_drift(self):
        from jokes.models import CultureTag, Joke

        self.configure_country_context()
        self.run_import(require_complete=True)
        self.records[0]['related_countries'] = ['NO']
        self.records.append({
            **self.records[0], 'id': 'intl-test-es-new',
            'text': 'Mi ascensor celebra cada planta como un ascenso profesional.',
        })
        self.write_bundle()
        report = self.root / 'report.json'
        self.run_import(report=report)
        stats = json.loads(report.read_text())['database']
        self.assertFalse(stats['context_complete'])
        self.assertEqual(stats['created'], 1)
        self.assertTrue(Joke.objects.get(seed_key='intl-test-es-new').countries.filter(code='NO').exists())
        self.assertTrue(CultureTag.objects.get(slug='spain-everyday').countries.filter(code='NO').exists())

    def test_changed_seed_key_fails_without_overwriting_the_existing_joke(self):
        from jokes.models import Joke
        self.run_import()
        self.records[0]['text'] = 'Mi ascensor celebra cada planta como un ascenso profesional.'
        (self.root / 'es.json').write_text(json.dumps(self.records), encoding='utf-8')
        with self.assertRaisesRegex(CommandError, 'changed'):
            self.run_import()
        self.assertNotEqual(Joke.objects.get(seed_key='intl-test-es-0').text, self.records[0]['text'])

    def test_moderated_seed_is_not_restored(self):
        from jokes.models import Joke
        self.run_import()
        Joke.all_objects.filter(seed_key='intl-test-es-0').update(is_removed=True)
        output = self.run_import()
        self.assertTrue(Joke.all_objects.get(seed_key='intl-test-es-0').is_removed)
        self.assertIn('removed=1', output)

    def test_identical_text_with_another_seed_key_is_rejected(self):
        from jokes.models import Joke
        self.run_import()
        self.records[0]['id'] = 'different-seed-key'
        (self.root / 'es.json').write_text(json.dumps(self.records), encoding='utf-8')
        before = Joke.all_objects.count()
        with self.assertRaisesRegex(CommandError, 'already exists'):
            self.run_import()
        self.assertEqual(Joke.all_objects.count(), before)

    def test_require_complete_rejects_before_importing(self):
        from jokes.models import Joke
        before = Joke.all_objects.count()
        with self.assertRaisesRegex(CommandError, 'incomplete'):
            self.run_import(require_complete=True)
        self.assertEqual(Joke.all_objects.count(), before)

    def test_live_coverage_does_not_claim_removed_or_prohibited_jokes(self):
        from jokes.models import Joke
        self.manifest['collections'][0]['target_per_category'] = 1
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        self.run_import(require_complete=True)
        Joke.all_objects.filter(seed_key='intl-test-es-0').update(content_tier='tier_3')
        with self.assertRaisesRegex(CommandError, 'public coverage'):
            self.run_import(require_complete=True)

    def test_live_coverage_detects_editorial_recategorization_without_reverting_it(self):
        from jokes.models import Joke
        self.manifest['collections'][0]['target_per_category'] = 1
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        self.run_import(require_complete=True)
        joke = Joke.objects.get(seed_key='intl-test-es-0')
        joke.tones.clear()
        report = self.root / 'report.json'
        self.run_import(report=report)
        body = json.loads(report.read_text())
        self.assertTrue(body['authored_complete'])
        self.assertFalse(body['database']['public_complete'])
        self.assertEqual(body['database']['coverage'][0]['public_count'], 0)
        self.assertFalse(joke.tones.exists())


class BundledInternationalCorpusTests(SimpleTestCase):
    def test_shipped_bundle_meets_all_six_country_category_targets(self):
        """Guard the promised content volume, including files omitted by accident."""
        from jokes.international_corpus import CATEGORIES, load_corpus

        corpus = load_corpus(
            Path(__file__).parent / 'fixtures/international/manifest.json', require_complete=True,
        )
        self.assertEqual(
            {(c['language'], c['country']) for c in corpus.manifest['collections']},
            {('es', 'ES'), ('fr', 'FR'), ('de', 'DE'), ('hy', 'AM'), ('it', 'IT'), ('nb', 'NO')},
        )
        self.assertEqual(len(corpus.coverage), 6 * len(CATEGORIES))
        for target in corpus.coverage:
            with self.subTest(collection=target['collection'], category=target['category']):
                self.assertGreaterEqual(target['target'], 200)
                self.assertGreaterEqual(target['count'], 200)
        self.assertGreaterEqual(len(corpus.records), 10800)
