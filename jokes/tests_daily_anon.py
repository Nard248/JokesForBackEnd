"""The anonymous "joke of the day" must actually be a joke of the DAY.

`order_by('?')` re-rolled on every request, so a logged-out visitor saw a
different joke on each refresh and a shared "today's joke" link showed
something different to every recipient -- which is not what a daily ritual
product means by daily. Authenticated users already get a stable per-day pick
via the DailyJoke table.
"""
from unittest.mock import patch

from freezegun import freeze_time
from rest_framework.test import APITestCase

from jokes.models import AgeRating, Format, Joke, Language


class AnonymousDailyJokeStabilityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        fmt = Format.objects.get(slug='oneliner')
        age = AgeRating.objects.first()
        lang = Language.objects.get(code='en')
        with patch('jokes.models.Joke._generate_share_image'):
            for i in range(25):
                Joke.objects.create(
                    text=f'Anonymous daily candidate {i}.',
                    format=fmt, age_rating=age, language=lang,
                    content_tier='tier_1',
                )

    def _today_id(self):
        resp = self.client.get('/api/v1/daily-jokes/today/')
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()['joke']['id']

    @freeze_time('2026-07-14 12:00:00')
    def test_same_joke_on_every_request_within_a_day(self):
        ids = {self._today_id() for _ in range(6)}
        self.assertEqual(
            len(ids), 1,
            f'anonymous daily joke changed between requests: {ids}',
        )

    def test_the_pick_changes_from_one_day_to_the_next(self):
        with freeze_time('2026-07-14 12:00:00'):
            day_one = self._today_id()
        with freeze_time('2026-07-15 12:00:00'):
            day_two = self._today_id()
        self.assertNotEqual(day_one, day_two)
