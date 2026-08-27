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
