"""Deterministic time-progression tests (freezegun) for the streak engine.

The streak has two reconcile paths that both key off the WALL CLOCK:
  * write path — ``update_streak_on_view`` (post_save on JokeView); gap-walk uses
    the JokeView's ``viewed_date``, monthly-freeze refresh uses ``timezone.now()``.
  * read path  — ``_reconcile_streak`` on GET /users/me/streak/; PURELY wall-clock
    (``timezone.now()``), previously untested — the highest-value target here.

We drive these with freezegun (never by hand-writing StreakDay/Streak date
fields) so the real wall-clock code actually runs and rolls over.

Run:
  DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 \
    DB_HOST=localhost DB_PORT=5432 \
    .venv/bin/python manage.py test jokes.test_streak_time_progression --keepdb
"""
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from freezegun import freeze_time
from rest_framework.test import APITestCase

from jokes.models import (
    AgeRating,
    Format,
    Joke,
    JokeView,
    Language,
    Streak,
    StreakDay,
)

User = get_user_model()


def _make_joke(text):
    fmt = Format.objects.get(slug='oneliner')
    age = AgeRating.objects.first()
    lang = Language.objects.get(code='en')
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text=text, format=fmt, age_rating=age, language=lang,
        )


class _StreakBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username=cls.__name__.lower() + '@ex.com',
            email=cls.__name__.lower() + '@ex.com',
            password='pw',
        )
        # A handful of distinct jokes so each day's view is a new (user, joke) pair
        # (the signal only counts the first JokeView of a pair: `if not created`).
        cls.jokes = [_make_joke(f'{cls.__name__} joke {i}') for i in range(10)]

    def view_on(self, when, joke):
        """Create a real JokeView at a frozen instant -> fires the streak signal."""
        with freeze_time(when):
            JokeView.objects.create(user=self.user, joke=joke)

    def streak(self):
        return Streak.objects.get(user=self.user)


# =============================================================================
# WRITE PATH — update_streak_on_view (JokeView post_save signal)
# =============================================================================

class WritePathIncrementTests(_StreakBase):
    def test_consecutive_days_increment(self):
        self.view_on('2026-07-14T09:00:00Z', self.jokes[0])
        self.assertEqual(self.streak().current_count, 1)
        self.view_on('2026-07-15T09:00:00Z', self.jokes[1])
        self.assertEqual(self.streak().current_count, 2)
        self.view_on('2026-07-16T09:00:00Z', self.jokes[2])
        s = self.streak()
        self.assertEqual(s.current_count, 3)
        self.assertEqual(s.longest_count, 3)
        self.assertEqual(s.last_active_date, date(2026, 7, 16))

    def test_multiple_views_same_day_do_not_double_count(self):
        self.view_on('2026-07-14T09:00:00Z', self.jokes[0])
        self.view_on('2026-07-14T18:00:00Z', self.jokes[1])  # same day, new joke
        self.assertEqual(self.streak().current_count, 1)


class WritePathFreezeTests(_StreakBase):
    def test_missed_day_with_freeze_available_is_frozen_not_burned(self):
        self.view_on('2026-07-14T09:00:00Z', self.jokes[0])  # count 1, freezes 2
        # Skip 2026-07-15 entirely.
        self.view_on('2026-07-16T09:00:00Z', self.jokes[1])
        s = self.streak()
        # The gap day auto-burned ONE freeze and the streak survived (+1 for today).
        self.assertEqual(s.current_count, 2)
        self.assertEqual(s.freeze_days_available, 1)
        self.assertEqual(s.freezes_used_total, 1)
        self.assertEqual(
            StreakDay.objects.get(user=self.user, date=date(2026, 7, 15)).status,
            StreakDay.STATUS_FROZEN,
        )
        self.assertEqual(
            StreakDay.objects.get(user=self.user, date=date(2026, 7, 16)).status,
            StreakDay.STATUS_READ,
        )

    def test_missed_day_without_freeze_burns_streak(self):
        # Build a 3-day streak.
        self.view_on('2026-07-14T09:00:00Z', self.jokes[0])
        self.view_on('2026-07-15T09:00:00Z', self.jokes[1])
        self.view_on('2026-07-16T09:00:00Z', self.jokes[2])
        s = self.streak()
        self.assertEqual(s.current_count, 3)
        # Exhaust freezes so the next miss cannot be covered.
        s.freeze_days_available = 0
        s.save()
        # Miss 2026-07-17, return 2026-07-18.
        self.view_on('2026-07-18T09:00:00Z', self.jokes[3])
        s = self.streak()
        self.assertEqual(
            s.current_count, 1,
            'Uncovered missed day must BURN the streak to 0, then +1 for today',
        )
        self.assertEqual(s.longest_count, 3, 'longest is preserved across the burn')
        self.assertEqual(
            StreakDay.objects.get(user=self.user, date=date(2026, 7, 17)).status,
            StreakDay.STATUS_MISSED,
        )


class WritePathMonthlyRefreshTests(_StreakBase):
    def test_freeze_pool_refreshes_on_first_view_of_new_month(self):
        self.view_on('2026-06-30T09:00:00Z', self.jokes[0])
        s = self.streak()
        s.freeze_days_available = 0  # simulate June's pool spent
        s.save()
        # Next calendar day IS the next month -> refresh fires, no gap to walk.
        self.view_on('2026-07-01T09:00:00Z', self.jokes[1])
        s = self.streak()
        self.assertEqual(s.freeze_days_available, Streak.FREEZES_PER_MONTH)
        self.assertEqual(s.last_freeze_refresh_month, '2026-07')
        self.assertEqual(s.current_count, 2, 'consecutive day across month boundary keeps counting')


# =============================================================================
# READ PATH — _reconcile_streak on GET /users/me/streak/ (pure wall-clock)
# =============================================================================

class ReadPathReconcileTests(_StreakBase):
    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def get_streak(self):
        r = self.client.get('/api/v1/users/me/streak/')
        self.assertEqual(r.status_code, 200, r.content)
        return r.data

    def test_reconcile_freezes_gap_day_on_read(self):
        self.view_on('2026-07-14T09:00:00Z', self.jokes[0])  # count 1, freezes 2
        # No activity on 07-15. Open the streak page on 07-16 -> lazy reconcile.
        with freeze_time('2026-07-16T09:00:00Z'):
            data = self.get_streak()
        self.assertEqual(data['current_count'], 1, 'streak survives — gap day frozen')
        self.assertEqual(data['freeze_days_available'], 1)
        self.assertEqual(
            StreakDay.objects.get(user=self.user, date=date(2026, 7, 15)).status,
            StreakDay.STATUS_FROZEN,
        )

    def test_reconcile_burns_gap_day_on_read_when_no_freeze(self):
        self.view_on('2026-07-14T09:00:00Z', self.jokes[0])
        s = self.streak()
        s.freeze_days_available = 0
        s.save()
        # Miss 07-15, open the streak page on 07-16 -> reconcile must burn.
        with freeze_time('2026-07-16T09:00:00Z'):
            data = self.get_streak()
        self.assertEqual(
            data['current_count'], 0,
            'read-path reconcile must burn the streak on an uncovered missed day',
        )
        self.assertEqual(
            StreakDay.objects.get(user=self.user, date=date(2026, 7, 15)).status,
            StreakDay.STATUS_MISSED,
        )

    def test_reconcile_does_not_burn_today_before_day_ends(self):
        """One-day gap (active yesterday, nothing yet today) is NOT a break."""
        self.view_on('2026-07-14T09:00:00Z', self.jokes[0])
        with freeze_time('2026-07-15T09:00:00Z'):
            data = self.get_streak()
        self.assertEqual(data['current_count'], 1, 'today still in progress -> no burn yet')
        self.assertFalse(
            StreakDay.objects.filter(user=self.user, date=date(2026, 7, 15)).exists(),
            'today is not marked missed until the day is actually over',
        )

    def test_read_path_monthly_refresh_at_month_boundary(self):
        self.view_on('2026-07-31T09:00:00Z', self.jokes[0])
        s = self.streak()
        s.freeze_days_available = 0
        s.save()
        # Exactly the next calendar day (new month), so there is NO gap to walk —
        # isolates the monthly freeze-pool refresh on the read path.
        with freeze_time('2026-08-01T09:00:00Z'):
            data = self.get_streak()
        self.assertEqual(data['freeze_days_available'], Streak.FREEZES_PER_MONTH)
        self.assertEqual(data['current_count'], 1)
        self.assertEqual(self.streak().last_freeze_refresh_month, '2026-08')


# =============================================================================
# SERIALIZER wall-clock methods (StreakSerializer) — sliding grid + risk flag
# =============================================================================

class StreakSerializerClockTests(_StreakBase):
    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def get_streak(self):
        r = self.client.get('/api/v1/users/me/streak/')
        self.assertEqual(r.status_code, 200, r.content)
        return r.data

    def test_last_14_days_window_slides_across_boundary(self):
        self.view_on('2026-07-14T09:00:00Z', self.jokes[0])

        with freeze_time('2026-07-14T12:00:00Z'):
            grid = self.get_streak()['last_14_days']
        self.assertEqual(grid[-1]['date'], '2026-07-14')  # today is the last cell
        self.assertEqual(grid[-1]['status'], 'read')

        with freeze_time('2026-07-15T12:00:00Z'):
            grid = self.get_streak()['last_14_days']
        # Window slid one day: new "today" cell is pending, yesterday still read.
        self.assertEqual(grid[-1]['date'], '2026-07-15')
        self.assertEqual(grid[-1]['status'], 'pending')
        self.assertEqual(grid[-2]['date'], '2026-07-14')
        self.assertEqual(grid[-2]['status'], 'read')

    def test_streak_at_risk_flag_flips_with_clock(self):
        self.view_on('2026-07-14T09:00:00Z', self.jokes[0])

        # Next day, before 8 PM UTC and not yet read today -> not at risk.
        with freeze_time('2026-07-15T10:00:00Z'):
            self.assertFalse(self.get_streak()['streak_at_risk_today'])

        # Same next day, after 8 PM UTC and still not read -> at risk.
        with freeze_time('2026-07-15T21:00:00Z'):
            self.assertTrue(self.get_streak()['streak_at_risk_today'])

        # Read today -> never at risk, even late.
        self.view_on('2026-07-15T21:30:00Z', self.jokes[1])
        with freeze_time('2026-07-15T22:00:00Z'):
            self.assertFalse(self.get_streak()['streak_at_risk_today'])
