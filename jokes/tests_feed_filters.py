"""Feed/search filter semantics for the Explore surface.

Explore lets a reader stack several formats ("One-liner" AND "Setup →
Punchline"), which the client sends as a comma-separated `joke_format`. The
tone/theme/culture axes have always accepted that shape; format did not, so
selecting more than one silently produced an empty feed.
"""
from unittest.mock import patch

from rest_framework.test import APITestCase

from jokes.models import AgeRating, Format, Joke, Language


def _make(format_slug, **kw):
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            format=Format.objects.get(slug=format_slug),
            age_rating=AgeRating.objects.first(),
            language=Language.objects.get(code='en'),
            **kw,
        )


class FormatFilterTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.one = _make('oneliner', text='A single line lands alone.')
        cls.setup = _make(
            'setup', setup='Why did the filter fail?', punchline='It only took one.',
        )

    def _ids(self, qs):
        resp = self.client.get(f'/api/v1/jokes/?{qs}')
        self.assertEqual(resp.status_code, 200, resp.content)
        return {j['id'] for j in resp.json()['results']}

    def test_single_format_filter_matches(self):
        self.assertIn(self.one.id, self._ids('joke_format=oneliner'))
        self.assertNotIn(self.setup.id, self._ids('joke_format=oneliner'))

    def test_comma_separated_formats_return_the_union(self):
        """Stacking formats must widen the feed, not empty it."""
        ids = self._ids('joke_format=oneliner,setup')
        self.assertIn(self.one.id, ids)
        self.assertIn(self.setup.id, ids)

    def test_unknown_format_slug_matches_nothing(self):
        self.assertEqual(self._ids('joke_format=not-a-format'), set())
