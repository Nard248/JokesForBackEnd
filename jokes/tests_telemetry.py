"""
Tests for the audience-telemetry ingest endpoint and the new impression/reach
fields it feeds into creator_insights.

Covers:
  - impression bulk insert + per-(user, joke, day) dedup
  - reveal sets revealed_punchline (existing view + create-when-missing)
  - reveal makes payoff_rate > 0 in insights afterwards
  - unknown joke / malformed event is skipped, never fatal
  - 401 for unauthenticated
  - batch cap at 50
  - insights overview gains impressions / unique_reach / open_rate (correct values)
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from jokes.models import (
    Format, AgeRating, Language, Joke, JokeSubmission,
    JokeView, JokeImpression, JokeDwell,
)
from creator_insights.services import build_creator_insights

User = get_user_model()

INGEST_URL = '/api/v1/telemetry/events'


def _make_joke(fmt, age, lang, text='Telemetry joke'):
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(text=text, format=fmt, age_rating=age, language=lang)


def _make_published_submission(user, fmt, age, lang, text='Telemetry joke'):
    joke = _make_joke(fmt, age, lang, text=text)
    JokeSubmission.objects.create(
        user=user, format=fmt, age_rating=age, language=lang,
        status='published', text=joke.text, published_joke=joke,
    )
    return joke


class TelemetryIngestTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')
        cls.user = User.objects.create_user(
            username='tele@test.com', email='tele@test.com', password='x'
        )
        cls.joke = _make_joke(cls.fmt, cls.age, cls.lang, text='J1')
        cls.joke2 = _make_joke(cls.fmt, cls.age, cls.lang, text='J2')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_unauthenticated_401(self):
        resp = APIClient().post(
            INGEST_URL, {'events': [{'joke': self.joke.id, 'type': 'impression'}]},
            format='json',
        )
        self.assertEqual(resp.status_code, 401)

    def test_impression_bulk_insert(self):
        resp = self.client.post(
            INGEST_URL,
            {'events': [
                {'joke': self.joke.id, 'type': 'impression', 'source': 'feed'},
                {'joke': self.joke2.id, 'type': 'impression', 'source': 'explore'},
            ]},
            format='json',
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()['accepted'], 2)
        self.assertEqual(JokeImpression.objects.count(), 2)

    def test_impression_dedup_same_day(self):
        events = [{'joke': self.joke.id, 'type': 'impression', 'source': 'feed'}] * 3
        resp = self.client.post(INGEST_URL, {'events': events}, format='json')
        self.assertEqual(resp.status_code, 202)
        # All 3 accepted (counted) but only one row persists for the day.
        self.assertEqual(
            JokeImpression.objects.filter(user=self.user, joke=self.joke).count(), 1
        )

    def test_reveal_sets_existing_view(self):
        view = JokeView.objects.create(
            user=self.user, joke=self.joke, source='explore',
            viewed_date=timezone.now().date(), revealed_punchline=False,
        )
        resp = self.client.post(
            INGEST_URL, {'events': [{'joke': self.joke.id, 'type': 'reveal'}]},
            format='json',
        )
        self.assertEqual(resp.status_code, 202)
        view.refresh_from_db()
        self.assertTrue(view.revealed_punchline)
        # No duplicate view created.
        self.assertEqual(JokeView.objects.filter(user=self.user, joke=self.joke).count(), 1)

    def test_reveal_creates_view_when_none(self):
        resp = self.client.post(
            INGEST_URL,
            {'events': [{'joke': self.joke.id, 'type': 'reveal', 'source': 'daily'}]},
            format='json',
        )
        self.assertEqual(resp.status_code, 202)
        view = JokeView.objects.get(user=self.user, joke=self.joke)
        self.assertTrue(view.revealed_punchline)
        self.assertEqual(view.source, 'daily')

    def test_malformed_and_unknown_skipped_not_fatal(self):
        resp = self.client.post(
            INGEST_URL,
            {'events': [
                {'joke': 999999, 'type': 'impression'},        # unknown joke
                {'joke': self.joke.id, 'type': 'bogus'},        # bad type
                'not-a-dict',                                   # malformed
                {'type': 'impression'},                         # missing joke
                {'joke': self.joke.id, 'type': 'impression'},  # valid
            ]},
            format='json',
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()['accepted'], 1)
        self.assertEqual(JokeImpression.objects.count(), 1)

    def test_empty_and_missing_events_ok(self):
        self.assertEqual(self.client.post(INGEST_URL, {}, format='json').status_code, 202)
        self.assertEqual(
            self.client.post(INGEST_URL, {'events': []}, format='json').json()['accepted'], 0
        )

    def test_batch_cap_at_50(self):
        # 60 impressions for 60 distinct jokes — only first 50 processed.
        jokes = [_make_joke(self.fmt, self.age, self.lang, text=f'cap{i}') for i in range(60)]
        events = [{'joke': j.id, 'type': 'impression'} for j in jokes]
        resp = self.client.post(INGEST_URL, {'events': events}, format='json')
        self.assertEqual(resp.json()['accepted'], 50)
        self.assertEqual(JokeImpression.objects.count(), 50)

    # --- Phase 2: dwell ---

    def test_dwell_creates_row(self):
        resp = self.client.post(
            INGEST_URL,
            {'events': [
                {'joke': self.joke.id, 'type': 'dwell', 'value': 5000,
                 'scroll_pct': 75, 'source': 'feed'},
            ]},
            format='json',
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()['accepted'], 1)
        d = JokeDwell.objects.get(user=self.user, joke=self.joke)
        self.assertEqual(d.dwell_ms, 5000)
        self.assertEqual(d.scroll_pct, 75)
        self.assertEqual(d.source, 'feed')

    def test_dwell_value_clamped_to_max(self):
        resp = self.client.post(
            INGEST_URL,
            {'events': [{'joke': self.joke.id, 'type': 'dwell', 'value': 999999999}]},
            format='json',
        )
        self.assertEqual(resp.json()['accepted'], 1)
        self.assertEqual(JokeDwell.objects.get().dwell_ms, 600000)

    def test_dwell_below_min_skipped(self):
        resp = self.client.post(
            INGEST_URL,
            {'events': [{'joke': self.joke.id, 'type': 'dwell', 'value': 300}]},
            format='json',
        )
        self.assertEqual(resp.json()['accepted'], 0)
        self.assertEqual(JokeDwell.objects.count(), 0)

    def test_dwell_scroll_pct_clamped(self):
        resp = self.client.post(
            INGEST_URL,
            {'events': [
                {'joke': self.joke.id, 'type': 'dwell', 'value': 5000, 'scroll_pct': 250},
                {'joke': self.joke2.id, 'type': 'dwell', 'value': 5000, 'scroll_pct': -10},
            ]},
            format='json',
        )
        self.assertEqual(resp.json()['accepted'], 2)
        self.assertEqual(JokeDwell.objects.get(joke=self.joke).scroll_pct, 100)
        self.assertEqual(JokeDwell.objects.get(joke=self.joke2).scroll_pct, 0)

    def test_dwell_scroll_pct_optional(self):
        resp = self.client.post(
            INGEST_URL,
            {'events': [{'joke': self.joke.id, 'type': 'dwell', 'value': 5000}]},
            format='json',
        )
        self.assertEqual(resp.json()['accepted'], 1)
        self.assertIsNone(JokeDwell.objects.get().scroll_pct)

    def test_dwell_bad_value_skipped(self):
        resp = self.client.post(
            INGEST_URL,
            {'events': [
                {'joke': self.joke.id, 'type': 'dwell'},                    # missing value
                {'joke': self.joke.id, 'type': 'dwell', 'value': 'abc'},    # non-int
                {'joke': self.joke.id, 'type': 'dwell', 'value': True},     # bool, not int
            ]},
            format='json',
        )
        self.assertEqual(resp.json()['accepted'], 0)
        self.assertEqual(JokeDwell.objects.count(), 0)

    def test_dwell_appends_multiple_rows(self):
        # Unlike impressions, dwell is NOT deduped — every sample is a row.
        events = [{'joke': self.joke.id, 'type': 'dwell', 'value': 5000}] * 3
        resp = self.client.post(INGEST_URL, {'events': events}, format='json')
        self.assertEqual(resp.json()['accepted'], 3)
        self.assertEqual(
            JokeDwell.objects.filter(user=self.user, joke=self.joke).count(), 3
        )

    def test_mixed_batch_all_handled(self):
        view = JokeView.objects.create(
            user=self.user, joke=self.joke, source='explore',
            viewed_date=timezone.now().date(), revealed_punchline=False,
        )
        resp = self.client.post(
            INGEST_URL,
            {'events': [
                {'joke': self.joke.id, 'type': 'impression', 'source': 'feed'},
                {'joke': self.joke.id, 'type': 'reveal'},
                {'joke': self.joke.id, 'type': 'dwell', 'value': 5000, 'scroll_pct': 95},
            ]},
            format='json',
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()['accepted'], 3)
        self.assertEqual(JokeImpression.objects.count(), 1)
        view.refresh_from_db()
        self.assertTrue(view.revealed_punchline)
        self.assertEqual(JokeDwell.objects.count(), 1)


class TelemetryInsightsIntegrationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')
        cls.creator = User.objects.create_user(
            username='tcreator@test.com', email='tcreator@test.com', password='x'
        )
        cls.viewer1 = User.objects.create_user(
            username='v1@test.com', email='v1@test.com', password='x'
        )
        cls.viewer2 = User.objects.create_user(
            username='v2@test.com', email='v2@test.com', password='x'
        )
        cls.joke = _make_published_submission(cls.creator, cls.fmt, cls.age, cls.lang)

        today = timezone.now().date()
        # 2 distinct users impressed the joke (unique_reach=2, impressions=2).
        JokeImpression.objects.create(user=cls.viewer1, joke=cls.joke, source='feed', created_date=today)
        JokeImpression.objects.create(user=cls.viewer2, joke=cls.joke, source='feed', created_date=today)
        # 1 detail-open view (views=1) -> open_rate = 1/2 = 0.5.
        JokeView.objects.create(user=cls.viewer1, joke=cls.joke, source='explore', viewed_date=today)

    def test_overview_has_impression_fields(self):
        data = build_creator_insights(self.creator, 'month')
        ov = data['overview']
        self.assertEqual(ov['impressions'], 2)
        self.assertEqual(ov['unique_reach'], 2)
        self.assertEqual(ov['open_rate'], 0.5)
        # top_jokes row carries impressions too.
        self.assertEqual(data['top_jokes'][0]['impressions'], 2)

    def test_open_rate_null_without_impressions(self):
        # A creator with views but no impressions -> open_rate None.
        creator2 = User.objects.create_user(
            username='c2@test.com', email='c2@test.com', password='x'
        )
        joke2 = _make_published_submission(creator2, self.fmt, self.age, self.lang, text='No imp')
        JokeView.objects.create(
            user=self.viewer1, joke=joke2, source='explore',
            viewed_date=timezone.now().date(),
        )
        ov = build_creator_insights(creator2, 'month')['overview']
        self.assertEqual(ov['impressions'], 0)
        self.assertIsNone(ov['open_rate'])

    def test_reveal_via_ingest_makes_payoff_positive(self):
        client = APIClient()
        client.force_authenticate(self.viewer1)
        # Before: viewer1's view is not revealed -> payoff 0.
        ov_before = build_creator_insights(self.creator, 'month')['overview']
        self.assertEqual(ov_before['payoff_rate'], 0)

        resp = client.post(
            INGEST_URL, {'events': [{'joke': self.joke.id, 'type': 'reveal'}]},
            format='json',
        )
        self.assertEqual(resp.status_code, 202)

        ov_after = build_creator_insights(self.creator, 'month')['overview']
        self.assertGreater(ov_after['payoff_rate'], 0)

    # --- Phase 2: dwell-driven read metrics ---

    def test_read_metrics_null_without_dwell(self):
        ov = build_creator_insights(self.creator, 'month')['overview']
        self.assertIsNone(ov['avg_read_seconds'])
        self.assertIsNone(ov['read_rate'])
        self.assertIsNone(ov['completion_rate'])

    def test_read_metrics_computed(self):
        today = timezone.now().date()
        # 4 dwell samples: 2000, 6000, 8000, 10000 ms -> avg 6.5s.
        # READ_THRESHOLD_MS=4000 -> 3 of 4 are reads -> read_rate 0.75.
        # scroll_pct on 3 rows: 50, 95, 100 -> 2 of 3 >= 90 -> completion 0.6667.
        for ms, sp in [(2000, 50), (6000, 95), (8000, 100), (10000, None)]:
            JokeDwell.objects.create(
                user=self.viewer1, joke=self.joke, dwell_ms=ms,
                scroll_pct=sp, source='feed', created_date=today,
            )
        ov = build_creator_insights(self.creator, 'month')['overview']
        self.assertEqual(ov['avg_read_seconds'], 6.5)
        self.assertEqual(ov['read_rate'], 0.75)
        self.assertEqual(ov['completion_rate'], round(2 / 3, 4))

        # Per top_jokes row carries avg_read_seconds + read_rate too.
        row = build_creator_insights(self.creator, 'month')['top_jokes'][0]
        self.assertEqual(row['avg_read_seconds'], 6.5)
        self.assertEqual(row['read_rate'], 0.75)

    def test_completion_rate_null_when_no_scroll(self):
        today = timezone.now().date()
        JokeDwell.objects.create(
            user=self.viewer1, joke=self.joke, dwell_ms=5000,
            scroll_pct=None, source='feed', created_date=today,
        )
        ov = build_creator_insights(self.creator, 'month')['overview']
        self.assertEqual(ov['avg_read_seconds'], 5.0)
        self.assertEqual(ov['read_rate'], 1.0)
        self.assertIsNone(ov['completion_rate'])
