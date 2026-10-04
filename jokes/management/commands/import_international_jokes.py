"""Import an original international corpus without duplicate or destructive writes."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from jokes.international_corpus import fingerprint, load_corpus
from jokes.models import (
    AgeRating,
    ContextTag,
    Country,
    CulturalCollection,
    CultureTag,
    Format,
    Joke,
    Language,
    Source,
    Tone,
)
from jokes.serving import content_tier_for_age_rating


class Command(BaseCommand):
    help = 'Validate, report coverage, and idempotently import an authored international corpus'

    def add_arguments(self, parser):
        parser.add_argument(
            '--manifest', type=Path,
            default=Path(__file__).resolve().parents[2] / 'fixtures/international/manifest.json',
        )
        parser.add_argument('--dry-run', action='store_true', help='Validate files only; no database writes')
        parser.add_argument(
            '--require-complete', action='store_true',
            help='Reject unmet category targets or missing authored country associations',
        )
        parser.add_argument('--report', type=Path, help='Write a JSON coverage report to this local path')

    def handle(self, *args, **options):
        try:
            corpus = load_corpus(options['manifest'], require_complete=options['require_complete'])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        report = {
            'records': len(corpus.records), 'authored_complete': corpus.complete,
            'native_reviewed': False, 'authored_coverage': corpus.coverage,
        }
        for row in corpus.coverage:
            self.stdout.write(
                f"{row['collection']}/{row['category']}: "
                f"{row['count']}/{row['target']}; missing {row['missing']}"
            )
        if options['dry_run']:
            report['mode'] = 'validation_only'
            self.stdout.write(f"Validated {len(corpus.records)} records; dry run, no database writes.")
        else:
            report['database'] = self._import(corpus, require_complete=options['require_complete'])
            stats = report['database']
            if not stats['context_complete']:
                self.stdout.write(self.style.WARNING(
                    f"Warning: {len(stats['context_mismatches'])} country context mismatch(es); "
                    'existing editorial country links were preserved. '
                    'Use --report for record details and resolve the differences explicitly.'
                ))
            self.stdout.write(self.style.SUCCESS(
                f"Imported: created={stats['created']} unchanged={stats['unchanged']} "
                f"removed={stats['removed']}. Native review is not claimed."
            ))
        if options['report']:
            options['report'].write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
            )

    @transaction.atomic
    def _import(self, corpus, *, require_complete=False):
        # Serialize this importer's writes. Stable-key uniqueness remains the DB backstop.
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [729413809])

        maps = {}
        for field, model, values in (
            ('format', Format, {r['format'] for r in corpus.records}),
            ('age_rating', AgeRating, {r['age_rating'] for r in corpus.records}),
            ('category', Tone, {r['category'] for r in corpus.records}),
            ('themes', ContextTag, {v for r in corpus.records for v in r['themes']}),
        ):
            maps[field] = {obj.slug: obj for obj in model.objects.filter(slug__in=values)}
            if missing := values - maps[field].keys():
                raise CommandError(f'Unknown database {field}: {sorted(missing)}. Apply taxonomy migrations first.')

        contexts = {}
        country_by_code = {}
        for definition in corpus.manifest.get('context_countries', []):
            country_by_code[definition['code']], _ = Country.objects.get_or_create(
                code=definition['code'], defaults={
                    'name': definition['name'], 'native_name': definition['native_name'],
                },
            )
        for collection in corpus.manifest['collections']:
            language, _ = Language.objects.get_or_create(
                code=collection['language'], defaults={
                    'name': collection['language_name'],
                    'native_name': collection['language_native_name'],
                },
            )
            country, _ = Country.objects.get_or_create(
                code=collection['country'], defaults={
                    'name': collection['country_name'],
                    'native_name': collection['country_native_name'],
                },
            )
            country_by_code[country.code] = country
            culture, _ = CultureTag.objects.get_or_create(
                slug=collection['culture'], defaults={
                    'name': collection['culture_name'],
                    'native_name': collection['culture_native_name'],
                    'description': collection['description'],
                },
            )
            culture.languages.add(language)
            culture.countries.add(country)
            collection_row = CulturalCollection.objects.filter(slug=collection['id']).first()
            triple = (language.pk, country.pk, culture.pk)
            if collection_row is not None:
                if (collection_row.language_id, collection_row.country_id, collection_row.culture_id) != triple:
                    raise CommandError(f"Collection {collection['id']} changed its language/country/culture.")
            else:
                if CulturalCollection.objects.filter(language=language, country=country, culture=culture).exists():
                    raise CommandError(f"Collection context already exists with a different id: {collection['id']}")
                CulturalCollection.objects.create(
                    slug=collection['id'], language=language, country=country, culture=culture,
                )
            contexts[collection['id']] = (language, country, culture)

        source, _ = Source.objects.get_or_create(
            name='JokesFor international originals v1',
            defaults={'description': corpus.manifest['provenance']['description']},
        )
        keys = [record['id'] for record in corpus.records]
        existing = {
            obj.seed_key: obj
            for obj in Joke.all_objects.filter(seed_key__in=keys)
            .select_related('language', 'format').prefetch_related('countries')
        }
        language_ids = {language.pk for language, _, _ in contexts.values()}
        # Include removed jokes: a new ID must not republish a taken-down original.
        known_texts = {
            (language_id, fingerprint(text))
            for language_id, text in Joke.all_objects.filter(language_id__in=language_ids)
            .values_list('language_id', 'text').iterator(chunk_size=2000)
        }
        additions, records_to_add = [], []
        stats = {'created': 0, 'unchanged': 0, 'removed': 0, 'context_mismatches': []}
        supported_related_by_collection = {}
        for record in corpus.records:
            language, country, _ = contexts[record['collection']]
            if previous := existing.get(record['id']):
                if previous.is_removed:
                    stats['removed'] += 1
                    continue
                immutable = {
                    'text': record['text'], 'setup': record['setup'], 'punchline': record['punchline'],
                    'language_id': language.pk, 'format_id': maps['format'][record['format']].pk,
                }
                if any(getattr(previous, field) != value for field, value in immutable.items()):
                    raise CommandError(
                        f"Stable key {record['id']} changed. Existing content was preserved; "
                        'resolve the authored revision explicitly.'
                    )
                expected_countries = {country.code, *record['related_countries']}
                actual_countries = {country.code for country in previous.countries.all()}
                if missing_countries := expected_countries - actual_countries:
                    stats['context_mismatches'].append({
                        'id': record['id'], 'collection': record['collection'],
                        'expected_countries': sorted(expected_countries),
                        'actual_countries': sorted(actual_countries),
                        'missing_countries': sorted(missing_countries),
                    })
                # Country edits remain authoritative; authored drift must not invent
                # culture-country metadata for an association absent from the joke.
                supported_related_by_collection.setdefault(record['collection'], set()).update(
                    actual_countries.intersection(record['related_countries']),
                )
                stats['unchanged'] += 1
                continue
            text_key = (language.pk, fingerprint(record['text']))
            if text_key in known_texts:
                raise CommandError(f"Joke text already exists for {record['id']}; no duplicate was imported.")
            known_texts.add(text_key)
            age_rating = maps['age_rating'][record['age_rating']]
            additions.append(Joke(
                seed_key=record['id'], text=record['text'], setup=record['setup'],
                punchline=record['punchline'], format=maps['format'][record['format']],
                age_rating=age_rating, language=language, source=source,
                content_tier=content_tier_for_age_rating(age_rating),
                cultural_note=record['cultural_note'], editorial_status='generated',
            ))
            records_to_add.append(record)
            supported_related_by_collection.setdefault(record['collection'], set()).update(
                record['related_countries'],
            )
        # Deliberately avoid Joke.save(): rendering thousands of share cards is separate work.
        Joke.all_objects.bulk_create(additions, batch_size=500)
        relations = {'tones': [], 'context_tags': [], 'culture_tags': [], 'countries': []}
        for joke, record in zip(additions, records_to_add, strict=True):
            _, country, culture = contexts[record['collection']]
            targets = {
                'tones': [maps['category'][record['category']].pk],
                'context_tags': [maps['themes'][slug].pk for slug in record['themes']],
                'culture_tags': [culture.pk],
                'countries': [country.pk] + [country_by_code[code].pk for code in record['related_countries']],
            }
            for field_name, target_ids in targets.items():
                field = Joke._meta.get_field(field_name)
                for target_id in target_ids:
                    relations[field_name].append(field.remote_field.through(**{
                        f'{field.m2m_field_name()}_id': joke.pk,
                        f'{field.m2m_reverse_field_name()}_id': target_id,
                    }))
        for field_name, rows in relations.items():
            Joke._meta.get_field(field_name).remote_field.through.objects.bulk_create(rows, batch_size=1000)
        for collection_id, codes in supported_related_by_collection.items():
            if codes:
                contexts[collection_id][2].countries.add(*(country_by_code[code] for code in codes))
        stats['created'] = len(additions)
        stats['context_complete'] = not stats['context_mismatches']
        stats['public_bundle_records'] = Joke.objects.filter(
            seed_key__in=keys, content_tier='tier_1',
        ).count()
        stats['coverage'] = []
        for target in corpus.coverage:
            language, country, culture = contexts[target['collection']]
            target_keys = [r['id'] for r in corpus.records
                           if r['collection'] == target['collection']
                           and r['category'] == target['category']]
            installed = Joke.objects.filter(
                seed_key__in=target_keys, language=language, countries=country,
                culture_tags=culture, tones__slug=target['category'],
            )
            public_count = installed.filter(content_tier='tier_1').distinct().count()
            mature_count = installed.filter(content_tier='tier_2').distinct().count()
            stats['coverage'].append({
                'collection': target['collection'], 'category': target['category'],
                'target': target['target'], 'public_count': public_count,
                'mature_count': mature_count, 'missing': max(0, target['target'] - public_count),
            })
        stats['public_complete'] = all(row['missing'] == 0 for row in stats['coverage'])
        if require_complete and not stats['context_complete']:
            raise CommandError(
                'Installed country context is incomplete: '
                f"{len(stats['context_mismatches'])} existing record(s) lack authored country associations. "
                'Import rolled back; existing editorial country links preserved.'
            )
        if require_complete and not stats['public_complete']:
            raise CommandError(
                'Installed public coverage is incomplete after accounting for moderation, '
                'content tiers, and editorial classification. Import rolled back; existing edits preserved.'
            )
        return stats
