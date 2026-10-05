"""Taxonomy lookups must return the WHOLE catalogue.

These are small, bounded reference tables that every client reads once to
populate pickers (the creator editor's tag picker, Explore's filter axes).
They inherited the feed's PAGE_SIZE=10 with no page_size_query_param, so any
catalogue over ten rows was silently truncated and the remainder became
unreachable in the UI -- the client fetches page 1 only.
"""
from rest_framework.test import APITestCase

from jokes.models import AgeRating, ContextTag, CultureTag, Format, Language, Tone

_CATALOGUES = [
    ('context-tags', ContextTag),
    ('tones', Tone),
    ('formats', Format),
    ('culture-tags', CultureTag),
    ('languages', Language),
    ('age-ratings', AgeRating),
    ('vibes', None),  # Vibe already opted out of pagination; keep it that way.
]


class LookupCatalogueCompletenessTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        # Push a catalogue well past the feed page size.
        for i in range(15):
            ContextTag.objects.get_or_create(
                slug=f'probe-theme-{i}', defaults={'name': f'Probe Theme {i}'},
            )

    def test_every_lookup_returns_all_rows_not_just_the_first_page(self):
        for path, model in _CATALOGUES:
            with self.subTest(catalogue=path):
                resp = self.client.get(f'/api/v1/{path}/')
                self.assertEqual(resp.status_code, 200, resp.content)
                body = resp.json()
                rows = body['results'] if isinstance(body, dict) else body
                if model is not None:
                    self.assertEqual(
                        len(rows), model.objects.count(),
                        f'{path} is truncated: the client sees {len(rows)} of '
                        f'{model.objects.count()} rows',
                    )

    def test_context_tags_include_rows_beyond_the_first_ten(self):
        resp = self.client.get('/api/v1/context-tags/')
        body = resp.json()
        rows = body['results'] if isinstance(body, dict) else body
        slugs = {r['slug'] for r in rows}
        self.assertGreater(ContextTag.objects.count(), 10)
        self.assertEqual(len(slugs), ContextTag.objects.count())


class FreshDatabaseCataloguesTests(APITestCase):
    """The E2E contract spec asserts every catalogue is non-empty on a database
    that has only been migrated (plus ``seed_e2e``, which adds no taxonomy).

    Each catalogue is reference data seeded by a migration -- culture tags by
    0040 (with the cultural collections of 0042 PROTECT-referencing them) -- so
    the test database, built by running those same migrations, must show it.
    """

    def test_every_catalogue_is_populated_by_migrations_alone(self):
        for path, _model in _CATALOGUES:
            with self.subTest(catalogue=path):
                body = self.client.get(f'/api/v1/{path}/').json()
                rows = body['results'] if isinstance(body, dict) else body
                self.assertGreater(len(rows), 0, f'/{path}/ is empty on a freshly migrated database')

    def test_culture_tags_are_the_migration_seeded_collections(self):
        slugs = {row['slug'] for row in self.client.get('/api/v1/culture-tags/').json()}
        self.assertLessEqual(
            {'spain-everyday', 'france-everyday', 'germany-everyday', 'armenia-everyday', 'italy-everyday'},
            slugs,
        )
