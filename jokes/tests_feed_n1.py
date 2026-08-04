"""Regression test for the JokeViewSet.list() N+1 query bug.

list() (jokes/views.py) builds its queryset via Joke.objects.search()
(JokeManager.search, jokes/managers.py), which starts from the MANAGER's
plain get_queryset() -- NOT JokeViewSet.get_queryset(), which is where the
select_related/prefetch_related eager loading lives. So the feed's queryset
never gets that eager loading, and serializing a page of jokes with
JokeSerializer (which nests format/age_rating/language/source/tones/
context_tags/culture_tags/media__asset) re-hits the DB once per joke, per
relation -- classic N+1.

These tests seed fully-nested jokes (every relation populated, media on
half of them) and assert the feed request issues a small, FIXED number of
queries that does not grow with how many joke rows land on the page.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from rest_framework.test import APIClient

from jokes.models import (
    AgeRating,
    ContextTag,
    CultureTag,
    Format,
    Joke,
    JokeMedia,
    Language,
    MediaAsset,
    Source,
    Tone,
)

User = get_user_model()

JOKE_COUNT = 20
PAGE_SIZE = 10  # REST_FRAMEWORK['PAGE_SIZE'] in settings.py


def _taxonomy():
    fmt, _ = Format.objects.get_or_create(
        slug='oneliner', defaults={'name': 'One-Liner'},
    )
    age, _ = AgeRating.objects.get_or_create(
        slug='all-ages', defaults={'name': 'All Ages'},
    )
    lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
    source, _ = Source.objects.get_or_create(name='Feed N1 Test Source')
    tones = []
    for slug in ('clean', 'dad-joke'):
        tone, _ = Tone.objects.get_or_create(slug=slug, defaults={'name': slug.title()})
        tones.append(tone)
    context_tags = []
    for slug in ('work', 'family'):
        tag, _ = ContextTag.objects.get_or_create(slug=slug, defaults={'name': slug.title()})
        context_tags.append(tag)
    culture, _ = CultureTag.objects.get_or_create(
        slug='universal', defaults={'name': 'Universal'},
    )
    return fmt, age, lang, source, tones, context_tags, culture


def _make_asset(owner):
    asset = MediaAsset(owner=owner, kind='image', width=800, height=600)
    asset.file.save('image.webp', ContentFile(b'fake-webp-bytes'), save=False)
    asset.save()
    return asset


class JokeFeedN1RegressionTests(TestCase):
    """/api/v1/jokes/ (JokeViewSet.list) must eager-load its nested
    relations exactly like JokeViewSet.get_queryset() does for retrieve()."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username='feedowner', email='feedowner@example.com', password='x',
        )
        fmt, age, lang, source, tones, context_tags, culture = _taxonomy()
        cls.jokes = []
        with mock.patch('jokes.models.Joke._generate_share_image'):
            for i in range(JOKE_COUNT):
                joke = Joke.objects.create(
                    text=f'Why did the test suite cross the road? #{i}',
                    format=fmt, age_rating=age, language=lang, source=source,
                )
                joke.tones.set(tones)
                joke.context_tags.set(context_tags)
                joke.culture_tags.set([culture])
                cls.jokes.append(joke)
        # Media on every other joke so get_media()'s media__asset prefetch
        # (and the N+1 it guards against) is actually exercised.
        for i, joke in enumerate(cls.jokes):
            if i % 2 == 0:
                asset = _make_asset(cls.owner)
                JokeMedia.objects.create(joke=joke, asset=asset, position=0)

    def setUp(self):
        self.client = APIClient()

    def test_feed_list_query_count_is_constant(self):
        """20 fully-nested jokes, default page (10/page, anonymous request).

        Before the fix: per-row queries for format/age_rating/language/
        source (FK) + tones/context_tags/culture_tags (M2M) + media/asset
        blow this well past 100 queries for a 10-row page. After the fix:
        a small fixed number, independent of row count.
        """
        with self.assertNumQueries(19):
            response = self.client.get('/api/v1/jokes/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), PAGE_SIZE)

    def test_feed_list_query_count_does_not_grow_with_rows_on_page(self):
        """O(1) proof: page 1 and page 2 both carry a full page (10 rows,
        since JOKE_COUNT=20=2*PAGE_SIZE) but are DIFFERENT rows/relations.
        If eager loading is in place, both pages cost the identical, fixed
        query count -- the count must not scale with which/how many rows
        are being serialized.
        """
        with self.assertNumQueries(19):
            resp1 = self.client.get('/api/v1/jokes/', {'page': 1})
        with self.assertNumQueries(19):
            resp2 = self.client.get('/api/v1/jokes/', {'page': 2})
        self.assertEqual(len(resp1.data['results']), PAGE_SIZE)
        self.assertEqual(len(resp2.data['results']), PAGE_SIZE)

    def test_feed_list_preserves_nested_data(self):
        """Correctness: eager loading must not drop or alter data. Walk
        both pages (10 + 10 = all 20 seeded jokes) and check every joke's
        nested format/tones/context_tags/culture_tags/media came through
        intact."""
        all_rows = {}
        for page in (1, 2):
            response = self.client.get('/api/v1/jokes/', {'page': page})
            self.assertEqual(response.status_code, 200)
            for row in response.data['results']:
                all_rows[row['id']] = row
        self.assertEqual(len(all_rows), JOKE_COUNT)

        even_ids = {j.id for i, j in enumerate(self.jokes) if i % 2 == 0}
        for joke in self.jokes:
            row = all_rows[joke.id]
            self.assertEqual(row['format']['slug'], 'oneliner')
            self.assertEqual(row['age_rating']['slug'], 'all-ages')
            self.assertEqual(row['language']['code'], 'en')
            self.assertEqual(row['source']['name'], 'Feed N1 Test Source')
            self.assertEqual(
                sorted(t['slug'] for t in row['tones']), ['clean', 'dad-joke'],
            )
            self.assertEqual(
                sorted(t['slug'] for t in row['context_tags']),
                ['family', 'work'],
            )
            self.assertEqual(
                [t['slug'] for t in row['culture_tags']], ['universal'],
            )
            if joke.id in even_ids:
                self.assertEqual(len(row['media']), 1)
                self.assertIn('url', row['media'][0])
                self.assertTrue(row['media'][0]['url'])
            else:
                self.assertEqual(row['media'], [])
