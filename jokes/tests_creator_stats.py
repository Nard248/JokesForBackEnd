"""Creator analytics: GET /users/me/creator-stats/.

The interesting risk here is arithmetic, not permissions. Five metrics read
from five tables, and the obvious implementation — five `Count`s annotated onto
one queryset — multiplies them against each other through the joins. These
tests pin the numbers with deliberately different counts per metric, so any
fan-out shows up as a wrong total rather than a passing coincidence.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from jokes.models import (
    AgeRating, Format, Joke, JokeRating, JokeSubmission, JokeView,
    Language, SavedJoke, ShareEvent,
)

User = get_user_model()


def _make_joke(fmt, age, lang, text='Test', creator=None):
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text=text, format=fmt, age_rating=age, language=lang,
            content_tier='tier_1', creator=creator,
        )


class CreatorStatsTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')
        cls.creator = User.objects.create_user(
            username='creator@test.com', email='creator@test.com', password='x',
        )
        cls.other = User.objects.create_user(
            username='other@test.com', email='other@test.com', password='x',
        )
        cls.url = reverse('creator-stats')

    def setUp(self):
        self.client.force_authenticate(self.creator)

    def _readers(self, count):
        return [
            User.objects.create_user(
                username=f'r{i}@t.com', email=f'r{i}@t.com', password='x',
            )
            for i in range(count)
        ]

    def test_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_no_jokes_reports_zeroes_rather_than_an_empty_body(self):
        body = self.client.get(self.url).json()
        self.assertEqual(body['jokes'], [])
        self.assertEqual(body['totals']['views'], 0)
        self.assertEqual(body['totals']['published'], 0)

    def test_metrics_do_not_inflate_each_other(self):
        """Deliberately unequal counts: 4 views, 3 likes, 1 dislike, 2 saves.

        Under a naive multi-`Count` annotation every one of these reports 24.
        """
        joke = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        readers = self._readers(4)
        for reader in readers:
            JokeView.objects.create(user=reader, joke=joke)
        for reader in readers[:3]:
            JokeRating.objects.create(user=reader, joke=joke, rating=JokeRating.LIKE)
        JokeRating.objects.create(
            user=readers[3], joke=joke, rating=JokeRating.DISLIKE,
        )
        for reader in readers[:2]:
            SavedJoke.objects.create(user=reader, joke=joke)
        ShareEvent.objects.create(joke=joke)

        body = self.client.get(self.url).json()
        row = body['jokes'][0]
        self.assertEqual(
            (row['views'], row['likes'], row['dislikes'], row['saves'], row['shares']),
            (4, 3, 1, 2, 1),
        )
        self.assertEqual(body['totals']['views'], 4)
        self.assertEqual(body['totals']['likes'], 3)

    def test_only_the_callers_own_jokes_are_counted(self):
        mine = _make_joke(self.fmt, self.age, self.lang, text='Mine', creator=self.creator)
        theirs = _make_joke(self.fmt, self.age, self.lang, text='Theirs', creator=self.other)
        reader = self._readers(1)[0]
        JokeView.objects.create(user=reader, joke=mine)
        JokeView.objects.create(user=reader, joke=theirs)

        body = self.client.get(self.url).json()
        self.assertEqual([row['id'] for row in body['jokes']], [mine.id])
        self.assertEqual(body['totals']['views'], 1)

    def test_a_removed_joke_stops_reporting(self):
        """A taken-down joke has no audience, so it must not report one."""
        joke = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        JokeView.objects.create(user=self._readers(1)[0], joke=joke)
        Joke.all_objects.filter(pk=joke.pk).update(is_removed=True)

        body = self.client.get(self.url).json()
        self.assertEqual(body['jokes'], [])
        self.assertEqual(body['totals']['views'], 0)

    def test_the_review_pipeline_is_reported_by_status(self):
        for state in ('draft', 'draft', 'pending', 'rejected'):
            JokeSubmission.objects.create(
                user=self.creator, text='x', format=self.fmt,
                age_rating=self.age, language=self.lang, status=state,
            )
        totals = self.client.get(self.url).json()['totals']
        self.assertEqual((totals['draft'], totals['pending'], totals['rejected']), (2, 1, 1))

    def test_the_breakdown_is_capped_but_the_totals_are_not(self):
        reader = self._readers(1)[0]
        for index in range(3):
            joke = _make_joke(
                self.fmt, self.age, self.lang, text=f'J{index}', creator=self.creator,
            )
            JokeView.objects.create(user=reader, joke=joke)

        body = self.client.get(self.url, {'limit': 1}).json()
        self.assertEqual(len(body['jokes']), 1)
        self.assertEqual(body['totals']['views'], 3, 'totals must cover every joke')
        self.assertEqual(body['totals']['published'], 3)
