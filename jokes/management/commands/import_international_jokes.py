"""Import an original international corpus without duplicate or destructive writes.

Publication is gated, fail-closed:

* Every imported record is created HELD (``editorial_status='generated'``):
  stored, reviewable in the admin, never served to readers.
* Only a launch set (``--launch-set``) publishes, by promoting listed keys from
  ``generated`` to ``ai_screened``. It never downgrades legacy, native-reviewed
  or already-screened jokes and never touches removed ones.
* Launch-set ``blocked`` keys become ``tier_3`` (never served) and stay held.
* Records in a mature category (dark/edgy) are never ``tier_1``: they import as
  ``tier_2`` whatever their age rating, and a launch set cannot publish them.

Every run is idempotent: unchanged data performs no row writes.
"""

import json
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from jokes.international_corpus import MATURE_CATEGORIES, fingerprint, load_corpus, load_launch_set
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
from jokes.publication import blank_share_cards, visibility_changed
from jokes.serving import TIER_1, TIER_2, content_tier_for_age_rating

TIER_3 = 'tier_3'
HELD = Joke.EDITORIAL_GENERATED
SCREENED = Joke.EDITORIAL_AI_SCREENED


def import_tier(record, age_rating, blocked):
    """Content tier for a newly imported record.

    The age rating is derived by the single shared rule
    (``content_tier_for_age_rating``); two importer rules may only raise it:
    a launch-set block makes the record tier_3, and a mature category (dark,
    edgy) is never tier_1.
    """
    if record['id'] in blocked:
        return TIER_3
    tier = content_tier_for_age_rating(age_rating)
    if record['category'] in MATURE_CATEGORIES and tier == TIER_1:
        return TIER_2
    return tier


class Command(BaseCommand):
    help = (
        'Validate, report coverage, and idempotently import an authored international corpus. '
        'Imported jokes are held (never served) until a launch set publishes them.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--manifest', type=Path,
            default=Path(__file__).resolve().parents[2] / 'fixtures/international/manifest.json',
        )
        parser.add_argument(
            '--launch-set', type=Path,
            help=('Launch-set JSON: publishes its "publish" keys as ai_screened and blocks its '
                  '"blocked" keys (tier_3, held). Without it, an import only holds records.'),
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
            launch_set = (load_launch_set(options['launch_set'], corpus)
                          if options['launch_set'] else None)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        report = {
            'records': len(corpus.records), 'authored_complete': corpus.complete,
            'native_reviewed': False, 'authored_coverage': corpus.coverage,
        }
        if launch_set is not None:
            report['launch_set'] = {
                'method': launch_set['method'], 'screened_at': launch_set['screened_at'],
                'publish': len(launch_set['publish']), 'blocked': len(launch_set['blocked']),
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
            report['database'] = self._import(
                corpus, launch_set, require_complete=options['require_complete'],
            )
            stats = report['database']
            if not stats['context_complete']:
                self.stdout.write(self.style.WARNING(
                    f"Warning: {len(stats['context_mismatches'])} country context mismatch(es); "
                    'existing editorial country links were preserved. '
                    'Use --report for record details and resolve the differences explicitly.'
                ))
            self.stdout.write(self.style.SUCCESS(
                f"Imported: created={stats['created']} unchanged={stats['unchanged']} "
                f"removed={stats['removed']} published={stats['published']} "
                f"blocked={stats['blocked']} mature_floor={stats['mature_floor']} "
                f"origin_backfilled={stats['origin_backfilled']}. "
                f"Live: {stats['live']}; held: {stats['held']}. Native review is not claimed."
            ))
        if options['report']:
            options['report'].write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
            )

    @transaction.atomic
    def _import(self, corpus, launch_set, *, require_complete=False):
        # Serialize this importer's writes. Stable-key uniqueness remains the DB backstop.
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [729413809])

        publish = set(launch_set['publish']) if launch_set else set()
        blocked = launch_set['blocked'] if launch_set else {}

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
        # Languages, countries, cultures and collections (e.g. Norwegian Bokmål /
        # Norway) come from the manifest, so a new collection needs no migration.
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
        known_texts = set()
        if len(existing) < len(keys):
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
                age_rating=age_rating, language=language, origin_country=country, source=source,
                content_tier=import_tier(record, age_rating, blocked),
                cultural_note=record['cultural_note'], editorial_status=HELD,
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
        stats.update(self._apply_editorial_state(corpus, contexts, publish, blocked, launch_set))
        stats['context_complete'] = not stats['context_mismatches']
        stats.update(self._coverage(corpus, contexts, maps['category']))
        if require_complete and not stats['context_complete']:
            raise CommandError(
                'Installed country context is incomplete: '
                f"{len(stats['context_mismatches'])} existing record(s) lack authored country associations. "
                'Import rolled back; existing editorial country links preserved.'
            )
        if require_complete and not stats['installed_complete']:
            raise CommandError(
                'Installed coverage is incomplete after accounting for moderation, prohibited '
                'tiers, and editorial classification. Import rolled back; existing edits preserved.'
            )
        return stats

    def _apply_editorial_state(self, corpus, contexts, publish, blocked, launch_set):
        """Set-based safety and launch-set updates; each matches zero rows on a re-run.

        Removed jokes are never touched, and editor decisions are only ever made
        stricter by this command (a higher tier, a block), never relaxed.
        """
        live_rows = Joke.all_objects.filter(is_removed=False)
        keys_by_collection = defaultdict(list)
        for record in corpus.records:
            keys_by_collection[record['collection']].append(record['id'])
        mature_keys = [r['id'] for r in corpus.records if r['category'] in MATURE_CATEGORIES]
        blocked_keys = list(blocked)
        now = timezone.now()
        stats = {
            # Safety floor, also for rows imported before the rule existed.
            'mature_floor': live_rows.filter(seed_key__in=mature_keys, content_tier=TIER_1)
            .update(content_tier=TIER_2, updated_at=now),
            'blocked': live_rows.filter(seed_key__in=blocked_keys).exclude(content_tier=TIER_3)
            .update(content_tier=TIER_3, updated_at=now),
            # A block also withdraws an earlier AI-screen publication.
            'blocked_unpublished': live_rows.filter(
                seed_key__in=blocked_keys, editorial_status=SCREENED,
            ).update(editorial_status=HELD, updated_at=now),
            'origin_backfilled': 0,
        }
        for collection_id, collection_keys in keys_by_collection.items():
            stats['origin_backfilled'] += live_rows.filter(
                seed_key__in=collection_keys, origin_country__isnull=True,
            ).update(origin_country=contexts[collection_id][1])
        # Only held rows are promoted: never legacy/native_reviewed/ai_screened,
        # never removed, never prohibited (tier_3).
        stats['published'] = live_rows.filter(
            seed_key__in=list(publish), editorial_status=HELD,
        ).exclude(content_tier=TIER_3).update(editorial_status=SCREENED, updated_at=now)
        if stats['blocked'] or stats['blocked_unpublished']:
            # Blocked rows are no longer public: no share card may keep serving them.
            blank_share_cards(Joke.all_objects.filter(seed_key__in=blocked_keys).exclude(share_image=''))
        if any(stats[key] for key in ('mature_floor', 'blocked', 'blocked_unpublished', 'published')):
            visibility_changed()
        if launch_set is not None and (
            stats['published'] or stats['blocked'] or stats['blocked_unpublished']
        ):
            from audit.services import record_audit
            record_audit(
                None, 'editorial_launch_set_applied', target_type='launch_set',
                target_id=launch_set['screened_at'],
                metadata={
                    'method': launch_set['method'], 'published': stats['published'],
                    'blocked': stats['blocked'], 'unpublished_by_block': stats['blocked_unpublished'],
                },
            )
        return stats

    def _coverage(self, corpus, contexts, tones):
        """Installed coverage per collection/category in a handful of set queries.

        A record counts only while it is not removed, not tier_3, and its
        current language, primary country, culture and primary category still
        match its authored target. ``installed_count`` includes held records;
        ``public_count``/``mature_count`` are the published (servable) subset
        by tier and ``held_count`` the unpublished rest.
        """
        rows = {
            row['seed_key']: row for row in Joke.all_objects.filter(
                seed_key__in=[r['id'] for r in corpus.records], is_removed=False,
            ).exclude(content_tier=TIER_3).values('pk', 'seed_key', 'language_id', 'content_tier')
        }
        joke_ids = [row['pk'] for row in rows.values()]
        links = {}
        for field_name in ('countries', 'culture_tags', 'tones'):
            field = Joke._meta.get_field(field_name)
            links[field_name] = set(
                field.remote_field.through.objects.filter(**{f'{field.m2m_field_name()}_id__in': joke_ids})
                .values_list(f'{field.m2m_field_name()}_id', f'{field.m2m_reverse_field_name()}_id')
            )
        published = set(Joke.objects.filter(pk__in=joke_ids).values_list('pk', flat=True))
        counts = defaultdict(lambda: {'installed': 0, 'public': 0, 'mature': 0, 'held': 0})
        for record in corpus.records:
            row = rows.get(record['id'])
            if row is None:
                continue
            language, country, culture = contexts[record['collection']]
            pk = row['pk']
            if (row['language_id'] != language.pk or (pk, country.pk) not in links['countries']
                    or (pk, culture.pk) not in links['culture_tags']
                    or (pk, tones[record['category']].pk) not in links['tones']):
                continue
            bucket = counts[(record['collection'], record['category'])]
            bucket['installed'] += 1
            if pk not in published:
                bucket['held'] += 1
            elif row['content_tier'] == TIER_1:
                bucket['public'] += 1
            else:
                bucket['mature'] += 1
        coverage = []
        for target in corpus.coverage:
            bucket = counts[(target['collection'], target['category'])]
            coverage.append({
                'collection': target['collection'], 'category': target['category'],
                'target': target['target'], 'installed_count': bucket['installed'],
                'public_count': bucket['public'], 'mature_count': bucket['mature'],
                'held_count': bucket['held'],
                'missing': max(0, target['target'] - bucket['installed']),
            })
        return {
            'coverage': coverage,
            'installed_complete': all(row['missing'] == 0 for row in coverage),
            'live': len(published),
            'held': len(joke_ids) - len(published),
        }
