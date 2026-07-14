"""Deterministic time-progression tests (freezegun) for day-boundary behavior.

These tests FREEZE the wall clock at a fixed UTC instant, assert behavior for
"day N", then ADVANCE the clock to "day N+1" (or across a wider gap) and assert
the rollover. The backend buckets every "today" off ``timezone.now().date()``
with TIME_ZONE='UTC', so freezegun patches all of it cleanly.

Covered here (streaks live in test_streak_time_progression.py):
  1. Daily joke   — per-date DailyJoke selection changes across the boundary.
  3. Mystery box  — daily-cap count resets lazily on the new rolled_date.
  4. Per-day dedup — JokeView 60s debounce + JokeImpression/JokeDwell day bucket.
  5. History window — get_recently_shown_joke_ids() "last N days" edge behavior
                       (+ a finding about DailyJokeViewSet.history being
                        row-count- rather than date-window-based).

Run:
  DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 \
    DB_HOST=localhost DB_PORT=5432 \
    .venv/bin/python manage.py test jokes.test_time_progression --keepdb
"""
import unittest
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from freezegun import freeze_time
from rest_framework.test import APITestCase

from jokes.models import (
    AgeRating, DailyJoke, Format, Joke, JokeDwell, JokeImpression, JokeView,
    Language, MysteryBoxRoll,
)
from jokes.recommendations import get_recently_shown_joke_ids

User = get_user_model()

DAY_N = '2026-07-14T12:00:00Z'
DAY_N1 = '2026-07-15T12:00:00Z'


def _make_joke(text):
    fmt = Format.objects.get(slug='oneliner')
    age = AgeRating.objects.first()
    lang = Language.objects.get(code='en')
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text=text, format=fmt, age_rating=age, language=lang,
        )


class DailyJokeRolloverTests(APITestCase):
    """Behavior 1: a NEW DailyJoke row (different joke) is generated on day N+1."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='daily@example.com', email='daily@example.com', password='pw',
        )
        # >=2 jokes so day N+1 (which excludes day-N's joke via the recently-shown
        # window) can deterministically pick a DIFFERENT joke.
        cls.jokes = [_make_joke(f'daily joke {i}') for i in range(3)]

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def test_new_row_and_different_joke_next_day(self):
        with freeze_time(DAY_N):
            r1 = self.client.get('/api/v1/daily-jokes/today/')
            self.assertEqual(r1.status_code, 200, r1.content)
            joke_n = r1.data['joke']['id']
            self.assertEqual(r1.data['date'], '2026-07-14')
            # delivered_at stamped on first access
            row_n = DailyJoke.objects.get(user=self.user, date=date(2026, 7, 14))
            self.assertIsNotNone(row_n.delivered_at)
            first_delivered = row_n.delivered_at

            # Same-day re-fetch is idempotent: same row, no new row, delivered_at unchanged.
            r1b = self.client.get('/api/v1/daily-jokes/today/')
            self.assertEqual(r1b.data['joke']['id'], joke_n)
            self.assertEqual(
                DailyJoke.objects.filter(user=self.user, date=date(2026, 7, 14)).count(), 1,
            )
            row_n.refresh_from_db()
            self.assertEqual(row_n.delivered_at, first_delivered)

        with freeze_time(DAY_N1):
            r2 = self.client.get('/api/v1/daily-jokes/today/')
            self.assertEqual(r2.status_code, 200, r2.content)
            joke_n1 = r2.data['joke']['id']
            self.assertEqual(r2.data['date'], '2026-07-15')

        # A fresh row exists for the new date, and the selection actually changed.
        self.assertTrue(DailyJoke.objects.filter(user=self.user, date=date(2026, 7, 15)).exists())
        self.assertEqual(DailyJoke.objects.filter(user=self.user).count(), 2)
        self.assertNotEqual(
            joke_n, joke_n1,
            'Day N+1 must generate a fresh joke, not re-serve the stale day-N pick',
        )


class MysteryBoxDailyResetTests(APITestCase):
    """Behavior 3: the daily-cap count resets lazily on the new rolled_date."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='mystery@example.com', email='mystery@example.com', password='pw',
        )
        cls.jokes = [_make_joke(f'mystery joke {i}') for i in range(6)]

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def test_cap_hits_on_day_n_then_resets_day_n1(self):
        with freeze_time(DAY_N):
            for i in range(MysteryBoxRoll.MAX_DAILY_ROLLS):
                r = self.client.post('/api/v1/mystery-box/roll/')
                self.assertEqual(r.status_code, 200, f'roll {i} -> {r.content}')
            # Over the cap on the same day.
            blocked = self.client.post('/api/v1/mystery-box/roll/')
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(
                MysteryBoxRoll.objects.filter(
                    user=self.user, rolled_date=date(2026, 7, 14)).count(),
                MysteryBoxRoll.MAX_DAILY_ROLLS,
            )

        with freeze_time(DAY_N1):
            # New day -> count query keys off the new rolled_date -> starts at 0.
            r = self.client.post('/api/v1/mystery-box/roll/')
            self.assertEqual(r.status_code, 200, r.content)

        self.assertEqual(
            MysteryBoxRoll.objects.filter(user=self.user, rolled_date=date(2026, 7, 14)).count(),
            3,
        )
        self.assertEqual(
            MysteryBoxRoll.objects.filter(user=self.user, rolled_date=date(2026, 7, 15)).count(),
            1,
        )


class JokeViewDebounceDayBucketTests(APITestCase):
    """Behavior 4: 60s-debounced JokeView + viewed_date buckets by day."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='view@example.com', email='view@example.com', password='pw',
        )
        cls.joke = _make_joke('view joke')

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def test_same_day_debounces_next_day_distinct(self):
        url = f'/api/v1/jokes/{self.joke.id}/'
        with freeze_time(DAY_N):
            self.client.get(url)
            self.client.get(url)  # within 60s (same frozen instant) -> debounced
            self.assertEqual(
                JokeView.objects.filter(user=self.user, joke=self.joke).count(), 1,
            )
            self.assertEqual(
                JokeView.objects.get(user=self.user, joke=self.joke).viewed_date,
                date(2026, 7, 14),
            )

        with freeze_time(DAY_N1):
            self.client.get(url)  # >60s later AND a new day -> new row

        views = JokeView.objects.filter(user=self.user, joke=self.joke)
        self.assertEqual(views.count(), 2)
        self.assertEqual(
            set(views.values_list('viewed_date', flat=True)),
            {date(2026, 7, 14), date(2026, 7, 15)},
        )


class ImpressionDwellDayBucketTests(APITestCase):
    """Behavior 4 (telemetry): JokeImpression per-day dedup + JokeDwell day bucket."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='imp@example.com', email='imp@example.com', password='pw',
        )
        cls.joke = _make_joke('impression joke')

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def _post(self, events):
        return self.client.post('/api/v1/telemetry/events', {'events': events}, format='json')

    def test_impression_dedups_same_day_new_row_next_day(self):
        ev = [{'joke': self.joke.id, 'type': 'impression', 'source': 'feed'}]
        with freeze_time(DAY_N):
            self._post(ev)
            self._post(ev)  # same (user, joke, day) -> get_or_create dedups
            self.assertEqual(
                JokeImpression.objects.filter(
                    user=self.user, joke=self.joke, created_date=date(2026, 7, 14)).count(),
                1,
            )
        with freeze_time(DAY_N1):
            self._post(ev)  # new created_date -> distinct row

        imps = JokeImpression.objects.filter(user=self.user, joke=self.joke)
        self.assertEqual(imps.count(), 2)
        self.assertEqual(
            set(imps.values_list('created_date', flat=True)),
            {date(2026, 7, 14), date(2026, 7, 15)},
        )

    def test_dwell_buckets_by_created_date(self):
        ev = [{'joke': self.joke.id, 'type': 'dwell', 'value': 3000, 'source': 'feed'}]
        with freeze_time(DAY_N):
            self._post(ev)
        with freeze_time(DAY_N1):
            self._post(ev)
        dwells = JokeDwell.objects.filter(user=self.user, joke=self.joke)
        self.assertEqual(dwells.count(), 2)  # append-only, one per day
        self.assertEqual(
            set(dwells.values_list('created_date', flat=True)),
            {date(2026, 7, 14), date(2026, 7, 15)},
        )


class RecentlyShownWindowTests(APITestCase):
    """Behavior 5: get_recently_shown_joke_ids() "last N days" rolling window."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='window@example.com', email='window@example.com', password='pw',
        )
        cls.joke = _make_joke('edge joke')
        # A DailyJoke delivered on 2026-06-15. With a 30-day window it is:
        #   - INSIDE the window when today <= 2026-07-15 (cutoff 06-15)
        #   - OUTSIDE the window once today >= 2026-07-16 (cutoff 06-16)
        DailyJoke.objects.create(user=cls.user, joke=cls.joke, date=date(2026, 6, 15))

    def test_entry_falls_out_of_window_as_clock_advances(self):
        with freeze_time('2026-07-15T00:00:00Z'):  # cutoff = 2026-06-15 (inclusive)
            ids = get_recently_shown_joke_ids(self.user, days=30)
            self.assertIn(self.joke.id, ids, 'On the edge day the entry is still inside the window')

        with freeze_time('2026-07-16T00:00:00Z'):  # cutoff = 2026-06-16 -> 06-15 excluded
            ids = get_recently_shown_joke_ids(self.user, days=30)
            self.assertNotIn(self.joke.id, ids, 'Past the edge the entry must fall out of the window')


class HistoryEndpointWindowTests(APITestCase):
    """Behavior 5 (finding): DailyJokeViewSet.history is row-count-based, NOT a
    rolling date window, despite the "last 30 days" docstring.

    This test PINS the actual behavior: an ancient DailyJoke row still shows up
    (because it is among the newest 30 rows), and advancing the clock does NOT
    evict it. Documented as a finding, not asserted as a bug.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='hist@example.com', email='hist@example.com', password='pw',
        )
        cls.old_joke = _make_joke('ancient joke')
        # A very old delivery (well outside any 30-day window).
        DailyJoke.objects.create(user=cls.user, joke=cls.old_joke, date=date(2024, 1, 1))

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def test_history_is_row_count_not_date_window(self):
        with freeze_time('2026-07-14T12:00:00Z'):
            r = self.client.get('/api/v1/daily-jokes/history/')
            self.assertEqual(r.status_code, 200, r.content)
            dates = [row['date'] for row in r.data]
        # The 2.5-year-old row is still returned: history is "last 30 ROWS",
        # not a rolling date window. Advancing the clock never evicts it.
        self.assertIn('2024-01-01', dates)

    @unittest.expectedFailure
    def test_history_SHOULD_roll_off_entries_older_than_window(self):
        """BUG (jokes/views.py:1149-1157): DailyJokeViewSet.history returns the
        newest 30 ROWS (`[:30]`) with NO date cutoff and never consults the
        `daily_joke_history_days` entitlement (30/90/365 across plans, defined in
        billing/entitlements.py:30 + seeded in billing/migrations/0002).

        Intended behavior: a rolling "last N days" window that EVICTS stale
        entries as the clock advances. This test asserts that intent and is
        marked expectedFailure to document the gap — a 2.5-year-old delivery
        must NOT appear once the clock is well past its 30-day window.
        """
        with freeze_time('2026-07-14T12:00:00Z'):
            r = self.client.get('/api/v1/daily-jokes/history/')
            dates = [row['date'] for row in r.data]
        self.assertNotIn('2024-01-01', dates)
