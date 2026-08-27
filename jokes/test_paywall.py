"""Tests for the freemium daily-read punchline paywall.

Free tier = 10 DISTINCT joke reveals/day; past the cap the PUNCHLINE is withheld
SERVER-SIDE (setup teaser stays). Paid tiers are unlimited. The daily editorial
joke (/daily-jokes/today/) is exempt. Reset boundary = midnight UTC.

Run:
  DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 \
    DB_HOST=localhost DB_PORT=5432 \
    .venv/bin/python manage.py test jokes.test_paywall --keepdb
"""
import json
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from freezegun import freeze_time
from rest_framework.test import APITestCase

from billing.models import Plan, Subscription
from jokes.models import (
    AgeRating,
    DailyJoke,
    Format,
    Joke,
    JokeView,
    Language,
)

User = get_user_model()

DAY_N = '2026-07-14T12:00:00Z'
DAY_N1 = '2026-07-15T12:00:00Z'
FREE_CAP = 10


def _make_joke(format_slug='setup', *, text='', setup='', punchline='', lines=None):
    fmt = Format.objects.get(slug=format_slug)
    age = AgeRating.objects.first()
    lang = Language.objects.get(code='en')
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text=text, setup=setup, punchline=punchline, lines=lines,
            format=fmt, age_rating=age, language=lang,
        )


def _setup_joke(n=0):
    return _make_joke('setup', setup=f'Why did the chicken {n}?', punchline=f'To get to {n}.')


class _Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='free@example.com', email='free@example.com', password='pw',
        )

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def _consume(self, count, user=None):
        """Seed `count` DISTINCT consumed reads (JokeView rows) for today."""
        user = user or self.user
        for i in range(count):
            JokeView.objects.create(user=user, joke=_setup_joke(1000 + i))

    def _retrieve(self, joke):
        return self.client.get(f'/api/v1/jokes/{joke.id}/')

    def _status(self):
        return self.client.get('/api/v1/jokes/daily-reads/')


class FreeUnderLimitTests(_Base):
    def test_under_limit_unlocked_and_used_counts_distinct(self):
        joke_a = _setup_joke(1)
        joke_b = _setup_joke(2)

        # Start: nothing consumed.
        self.assertEqual(self._status().data['used'], 0)

        r = self._retrieve(joke_a)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['is_locked'])
        self.assertEqual(r.data['punchline'], joke_a.punchline)  # payoff present
        self.assertEqual(self._status().data['used'], 1)

        # Re-open SAME joke -> distinct used does not move.
        self._retrieve(joke_a)
        self.assertEqual(self._status().data['used'], 1)

        # A different joke increments.
        self._retrieve(joke_b)
        s = self._status().data
        self.assertEqual(s['used'], 2)
        self.assertEqual(s['limit'], FREE_CAP)
        self.assertEqual(s['remaining'], FREE_CAP - 2)
        self.assertFalse(s['over'])


class FreeOverLimitTests(_Base):
    def test_new_joke_locked_stripped_setup_kept(self):
        self._consume(FREE_CAP)
        locked = _setup_joke(99)

        r = self._retrieve(locked)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['is_locked'])
        self.assertIsNone(r.data['punchline'])         # payoff withheld
        self.assertIsNone(r.data['lines'])
        self.assertEqual(r.data['setup'], locked.setup)  # teaser kept

    def test_locked_retrieve_creates_no_jokeview(self):
        self._consume(FREE_CAP)
        locked = _setup_joke(98)
        before = JokeView.objects.filter(user=self.user).count()

        r = self._retrieve(locked)
        self.assertTrue(r.data['is_locked'])
        after = JokeView.objects.filter(user=self.user).count()
        self.assertEqual(after, before, 'A locked delivery must NOT log consumption')
        self.assertFalse(
            JokeView.objects.filter(user=self.user, joke=locked).exists()
        )

    def test_already_consumed_joke_stays_unlocked(self):
        self._consume(FREE_CAP - 1)
        already = _setup_joke(50)
        JokeView.objects.create(user=self.user, joke=already)  # consumed today
        # Now at the cap (10 distinct), but `already` is in consumed_ids.

        self.assertTrue(self._status().data['over'])
        r = self._retrieve(already)
        self.assertFalse(r.data['is_locked'])
        self.assertEqual(r.data['punchline'], already.punchline)

    def test_locked_joke_never_leaks_punchline_via_backfilled_text(self):
        """A published two-part joke stores a denormalized ``text`` of
        "<setup> <punchline>" (the submission pipeline backfills it). Locking
        must withhold the payoff from EVERY field it appears in, not just
        ``punchline`` -- otherwise the paywall is bypassed by reading ``text``.

        The other tests in this class build jokes with ``text=''``, so they
        cannot see this: production rows are not shaped like the fixtures.
        """
        self._consume(FREE_CAP)
        locked = _make_joke(
            'setup',
            setup='Why did the coffee file a police report?',
            punchline='It got mugged.',
            text='Why did the coffee file a police report? It got mugged.',
        )

        r = self._retrieve(locked)

        self.assertTrue(r.data['is_locked'])
        self.assertNotIn(
            'It got mugged',
            json.dumps(r.data, default=str),
            'The punchline must not appear ANYWHERE in a locked payload',
        )

    def test_text_only_format_blurs_whole_card(self):
        self._consume(FREE_CAP)
        one = _make_joke('oneliner', text='I only tell dad jokes now.')

        r = self._retrieve(one)
        self.assertTrue(r.data['is_locked'])
        self.assertIsNone(r.data['text'])  # no teaser for text-only -> null text


class PaidUnlimitedTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='paid@example.com', email='paid@example.com', password='pw',
        )
        Subscription.objects.create(
            user=cls.user,
            plan=Plan.objects.get(slug='supporter'),
            status='active',
        )

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def test_never_locked_even_far_over_free_cap(self):
        for i in range(FREE_CAP + 5):
            JokeView.objects.create(user=self.user, joke=_setup_joke(200 + i))
        joke = _setup_joke(300)

        r = self.client.get(f'/api/v1/jokes/{joke.id}/')
        self.assertFalse(r.data['is_locked'])
        self.assertEqual(r.data['punchline'], joke.punchline)

    def test_status_reports_unlimited(self):
        s = self.client.get('/api/v1/jokes/daily-reads/').data
        self.assertIsNone(s['limit'])
        self.assertIsNone(s['remaining'])
        self.assertFalse(s['over'])


class DailyEditorialExemptTests(_Base):
    def test_today_joke_never_locked_over_limit(self):
        self._consume(FREE_CAP)
        editorial = _setup_joke(77)
        today = date(2026, 7, 14)
        with freeze_time(DAY_N):
            DailyJoke.objects.create(user=self.user, joke=editorial, date=today)
            r = self.client.get('/api/v1/daily-jokes/today/')
            self.assertEqual(r.status_code, 200, r.content)
            self.assertFalse(r.data['joke']['is_locked'])
            self.assertEqual(r.data['joke']['punchline'], editorial.punchline)


class ResetAtMidnightTests(_Base):
    def test_over_limit_day_n_resets_day_n1(self):
        locked = _setup_joke(88)
        with freeze_time(DAY_N):
            self._consume(FREE_CAP)  # 10 distinct reads on 2026-07-14
            self.assertTrue(self._status().data['over'])
            r = self._retrieve(locked)
            self.assertTrue(r.data['is_locked'])

        with freeze_time(DAY_N1):
            s = self._status().data
            self.assertEqual(s['used'], 0, 'used resets at midnight UTC')
            self.assertFalse(s['over'])
            r = self._retrieve(locked)
            self.assertFalse(r.data['is_locked'])
            self.assertEqual(r.data['punchline'], locked.punchline)


class StatusEndpointTests(_Base):
    def test_shape_and_values(self):
        self._consume(3)
        s = self._status().data
        self.assertEqual(
            set(s.keys()), {'limit', 'used', 'remaining', 'over', 'reset_at'},
        )
        self.assertEqual(s['limit'], FREE_CAP)
        self.assertEqual(s['used'], 3)
        self.assertEqual(s['remaining'], FREE_CAP - 3)
        self.assertFalse(s['over'])
        self.assertTrue(s['reset_at'].startswith('2026-'))


class HistoryEntitlementTests(APITestCase):
    """History window honors the daily_joke_history_days entitlement: a 60-day-old
    entry is out-of-window for free (30d) but in-window for supporter (90d)."""

    @classmethod
    def setUpTestData(cls):
        cls.joke = _make_joke('setup', setup='s', punchline='p')

    def _history_dates(self, user):
        self.client.force_authenticate(user=user)
        with freeze_time(DAY_N):  # today = 2026-07-14
            r = self.client.get('/api/v1/daily-jokes/history/')
        self.assertEqual(r.status_code, 200, r.content)
        return [row['date'] for row in r.data]

    def test_free_excludes_but_supporter_includes_60_day_old(self):
        old = date(2026, 5, 15)  # 60 days before 2026-07-14

        free_user = User.objects.create_user(
            username='h-free@example.com', email='h-free@example.com', password='pw',
        )
        DailyJoke.objects.create(user=free_user, joke=self.joke, date=old)
        self.assertNotIn('2026-05-15', self._history_dates(free_user))

        sup_user = User.objects.create_user(
            username='h-sup@example.com', email='h-sup@example.com', password='pw',
        )
        Subscription.objects.create(
            user=sup_user, plan=Plan.objects.get(slug='supporter'), status='active',
        )
        DailyJoke.objects.create(user=sup_user, joke=self.joke, date=old)
        self.assertIn('2026-05-15', self._history_dates(sup_user))
