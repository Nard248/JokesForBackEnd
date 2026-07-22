"""
Tests for creator_insights.services.

Covers:
  - resolve_creator_jokes: attribution join, creator-scoped
  - build_creator_insights: overview metrics, breakdowns, top_jokes, audience, suggestions
"""
import json
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from jokes.models import (
    Format, AgeRating, Language, Tone, ContextTag, Joke, JokeSubmission,
    JokeView, JokeReaction, Favorite, SavedJoke, ShareEvent, JokeImpression,
)

User = get_user_model()

TODAY = timezone.now().date()


def _make_joke(fmt, age, lang, text='Test joke', content_tier='tier_1'):
    with patch('jokes.models.Joke._generate_share_image'):
        j = Joke.objects.create(
            text=text, format=fmt, age_rating=age, language=lang,
            content_tier=content_tier,
        )
    return j


def _make_published_submission(user, fmt, age, lang, joke=None, text='Test joke',
                                content_tier='tier_1'):
    if joke is None:
        joke = _make_joke(fmt, age, lang, text=text, content_tier=content_tier)
    sub = JokeSubmission.objects.create(
        user=user,
        format=fmt,
        age_rating=age,
        language=lang,
        status='published',
        text=joke.text,
        published_joke=joke,
    )
    return sub, joke


def _view(user, joke, revealed=False, source='explore', days_ago=0):
    vdate = TODAY - timedelta(days=days_ago)
    return JokeView.objects.create(
        user=user, joke=joke, revealed_punchline=revealed,
        source=source, viewed_date=vdate,
    )


class ResolveCreatorJokesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='creator@svc.com', email='creator@svc.com', password='x'
        )
        cls.other_creator = User.objects.create_user(
            username='other@svc.com', email='other@svc.com', password='x'
        )

        # Creator has 2 published jokes
        cls.sub1, cls.joke1 = _make_published_submission(cls.creator, cls.fmt, cls.age, cls.lang, text='Joke 1')
        cls.sub2, cls.joke2 = _make_published_submission(cls.creator, cls.fmt, cls.age, cls.lang, text='Joke 2')

        # Other creator's joke should NOT appear
        cls.sub_other, cls.joke_other = _make_published_submission(
            cls.other_creator, cls.fmt, cls.age, cls.lang, text='Other joke'
        )

        # Draft submission for creator: joke should NOT appear
        cls.joke_draft = _make_joke(cls.fmt, cls.age, cls.lang, text='Draft joke')
        JokeSubmission.objects.create(
            user=cls.creator, format=cls.fmt, age_rating=cls.age, language=cls.lang,
            status='draft', text='Draft joke', published_joke=cls.joke_draft,
        )

    def test_returns_exactly_creator_published_jokes(self):
        from creator_insights.services import resolve_creator_jokes
        qs = resolve_creator_jokes(self.creator)
        ids = set(qs.values_list('id', flat=True))
        self.assertEqual(ids, {self.joke1.id, self.joke2.id})

    def test_excludes_other_creators_jokes(self):
        from creator_insights.services import resolve_creator_jokes
        qs = resolve_creator_jokes(self.creator)
        self.assertNotIn(self.joke_other.id, qs.values_list('id', flat=True))

    def test_excludes_draft_jokes(self):
        from creator_insights.services import resolve_creator_jokes
        qs = resolve_creator_jokes(self.creator)
        self.assertNotIn(self.joke_draft.id, qs.values_list('id', flat=True))

    def test_zero_jokes_for_user_with_no_published_submissions(self):
        from creator_insights.services import resolve_creator_jokes
        bare_user = User.objects.create_user(
            username='bare@svc.com', email='bare@svc.com', password='x'
        )
        qs = resolve_creator_jokes(bare_user)
        self.assertEqual(qs.count(), 0)

    def test_tier2_joke_is_included(self):
        """Owner scope bypasses tier gate — tier_2 joke must appear in resolve."""
        from creator_insights.services import resolve_creator_jokes
        tier2_user = User.objects.create_user(
            username='tier2creator@svc.com', email='tier2creator@svc.com', password='x'
        )
        _, tier2_joke = _make_published_submission(
            tier2_user, self.fmt, self.age, self.lang, text='Mature joke', content_tier='tier_2'
        )
        qs = resolve_creator_jokes(tier2_user)
        self.assertIn(tier2_joke.id, qs.values_list('id', flat=True))


class OverviewMetricsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='ov_creator@svc.com', email='ov_creator@svc.com', password='x'
        )
        cls.reader1 = User.objects.create_user(
            username='reader1@svc.com', email='reader1@svc.com', password='x'
        )
        cls.reader2 = User.objects.create_user(
            username='reader2@svc.com', email='reader2@svc.com', password='x'
        )

        cls._, cls.joke1 = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang, text='OV Joke 1'
        )
        cls._, cls.joke2 = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang, text='OV Joke 2'
        )

        # Views: 3 total (2 readers on j1, 1 on j2)
        # reader1 views joke1 once revealed, once not
        _view(cls.reader1, cls.joke1, revealed=True, days_ago=5)
        _view(cls.reader1, cls.joke1, revealed=False, days_ago=4)
        # reader2 views joke1 once revealed
        _view(cls.reader2, cls.joke1, revealed=True, days_ago=3)
        # reader1 views joke2 once not revealed
        _view(cls.reader1, cls.joke2, revealed=False, days_ago=2)

        # Reactions on joke1
        JokeReaction.objects.create(user=cls.reader1, joke=cls.joke1, reaction='lol')
        JokeReaction.objects.create(user=cls.reader2, joke=cls.joke1, reaction='crying')

        # Favorites on joke2
        Favorite.objects.create(user=cls.reader1, joke=cls.joke2)

        # SavedJoke on joke1
        SavedJoke.objects.create(user=cls.reader1, joke=cls.joke1)

        # ShareEvent on joke1
        ShareEvent.objects.create(joke=cls.joke1, user=cls.reader1, platform='whatsapp')

    def test_overview_published_count(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        self.assertEqual(data['overview']['published_jokes'], 2)

    def test_overview_total_views(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        self.assertEqual(data['overview']['views'], 4)

    def test_overview_reach(self):
        """Reach = distinct viewers across all creator's jokes."""
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        # reader1 and reader2 both viewed creator's jokes
        self.assertEqual(data['overview']['reach'], 2)

    def test_overview_payoff_rate(self):
        """2 revealed out of 4 views = 0.5."""
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        self.assertAlmostEqual(data['overview']['payoff_rate'], 0.5)

    def test_overview_reactions(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        self.assertEqual(data['overview']['reactions'], 2)

    def test_overview_favorites(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        self.assertEqual(data['overview']['favorites'], 1)

    def test_overview_saves(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        self.assertEqual(data['overview']['saves'], 1)

    def test_overview_shares(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        self.assertEqual(data['overview']['shares'], 1)

    def test_overview_zero_jokes_empty(self):
        """Creator with no published jokes returns zeros everywhere."""
        from creator_insights.services import build_creator_insights
        bare = User.objects.create_user(
            username='bare_ov@svc.com', email='bare_ov@svc.com', password='x'
        )
        data = build_creator_insights(bare, 'all')
        ov = data['overview']
        self.assertEqual(ov['published_jokes'], 0)
        self.assertEqual(ov['views'], 0)
        self.assertEqual(ov['reach'], 0)
        self.assertIsNone(ov['payoff_rate'])


class BreakdownsAndTopJokesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='top_creator@svc.com', email='top_creator@svc.com', password='x'
        )
        cls.reader = User.objects.create_user(
            username='top_reader@svc.com', email='top_reader@svc.com', password='x'
        )

        cls._, cls.joke_a = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang, text='Top Joke A'
        )
        cls._, cls.joke_b = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang, text='Top Joke B'
        )

        # joke_a gets more views -> should be ranked first
        _view(cls.reader, cls.joke_a, revealed=True, source='daily', days_ago=1)
        _view(cls.reader, cls.joke_a, revealed=True, source='explore', days_ago=2)
        _view(cls.reader, cls.joke_b, revealed=False, source='whatsapp', days_ago=1)

        # Reactions grouped
        JokeReaction.objects.create(user=cls.reader, joke=cls.joke_a, reaction='lol')
        # Shares grouped
        ShareEvent.objects.create(joke=cls.joke_a, user=cls.reader, platform='whatsapp')
        ShareEvent.objects.create(joke=cls.joke_b, user=cls.reader, platform='twitter')

    def test_reactions_breakdown_groups_by_reaction(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        breakdown = data['reactions_breakdown']
        self.assertIsInstance(breakdown, list)
        total = sum(r['count'] for r in breakdown)
        self.assertEqual(total, 1)
        reactions = {r['reaction'] for r in breakdown}
        self.assertIn('lol', reactions)

    def test_shares_breakdown_groups_by_platform(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        breakdown = data['shares_breakdown']
        platforms = {r['platform'] for r in breakdown}
        self.assertIn('whatsapp', platforms)
        self.assertIn('twitter', platforms)

    def test_source_mix_groups_by_source(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        mix = data['source_mix']
        sources = {r['source'] for r in mix}
        self.assertIn('daily', sources)
        self.assertIn('explore', sources)

    def test_top_jokes_ordered_by_views_desc(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        top = data['top_jokes']
        self.assertGreaterEqual(len(top), 2)
        # joke_a has 2 views, joke_b has 1 -> joke_a is first
        self.assertEqual(top[0]['id'], self.joke_a.id)
        self.assertEqual(top[0]['views'], 2)

    def test_top_jokes_has_required_fields(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        top = data['top_jokes']
        required = {'id', 'text', 'views', 'reactions', 'saves', 'shares', 'payoff_rate'}
        for joke_row in top:
            self.assertTrue(required.issubset(joke_row.keys()),
                            f"Missing keys: {required - joke_row.keys()}")


class AudienceAndSuggestionsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')
        cls.tone = Tone.objects.first()
        cls.theme = ContextTag.objects.first()

        cls.creator = User.objects.create_user(
            username='aud_creator@svc.com', email='aud_creator@svc.com', password='x'
        )
        cls.reader = User.objects.create_user(
            username='aud_reader@svc.com', email='aud_reader@svc.com', password='x'
        )

        _, cls.joke = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang, text='Audience joke'
        )
        if cls.tone:
            cls.joke.tones.add(cls.tone)
        if cls.theme:
            cls.joke.context_tags.add(cls.theme)

        _view(cls.reader, cls.joke, days_ago=3)

    def test_audience_top_themes_present(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        self.assertIn('audience', data)
        aud = data['audience']
        self.assertIn('top_themes', aud)
        self.assertIn('top_categories', aud)
        self.assertIn('top_formats', aud)

    def test_suggestions_has_three_cards(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        suggestions = data['suggestions']
        kinds = {s['kind'] for s in suggestions}
        # All three cards must be present (even if data is sparse)
        self.assertIn('peak_hour', kinds)
        self.assertIn('what_resonates', kinds)
        self.assertIn('consistency', kinds)

    def test_suggestions_have_required_fields(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        for s in data['suggestions']:
            self.assertIn('kind', s)
            self.assertIn('title', s)
            self.assertIn('detail', s)
            self.assertIn('data', s)

    def test_consistency_card_includes_days_since(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        consistency = next(s for s in data['suggestions'] if s['kind'] == 'consistency')
        self.assertIn('days_since', consistency['data'])
        self.assertIsInstance(consistency['data']['days_since'], int)

    def test_top_level_keys_present(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        required_keys = {
            'period', 'is_creator', 'overview', 'reactions_breakdown',
            'shares_breakdown', 'source_mix', 'top_jokes', 'audience', 'suggestions',
        }
        self.assertTrue(required_keys.issubset(data.keys()))

    def test_sparkline_has_28_entries(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        self.assertEqual(len(data['overview']['daily_reach_28d']), 28)


class PeriodBoundaryTests(TestCase):
    """Views outside the period window must be excluded; 'all' includes everything."""

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='pb_creator@svc.com', email='pb_creator@svc.com', password='x'
        )
        cls.reader = User.objects.create_user(
            username='pb_reader@svc.com', email='pb_reader@svc.com', password='x'
        )

        _, cls.joke = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang, text='Boundary joke'
        )

        # View today — always within any window
        cls.view_today = _view(cls.reader, cls.joke, days_ago=0)

        # View 10 days ago — outside the 'week' (6-day) window but inside 'all'
        cls.view_old = _view(cls.reader, cls.joke, days_ago=10)
        # Force viewed_date to 10 days ago explicitly (in case auto_now_add
        # overrides the date).  JokeView.viewed_date is set explicitly in _view().

    def test_week_period_excludes_old_view(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, period='week')
        # Only the today-view should be counted (days_ago=0 is within 6 days)
        self.assertEqual(data['overview']['views'], 1)

    def test_all_period_includes_both_views(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, period='all')
        # Both views (today + 10 days ago) must appear
        self.assertEqual(data['overview']['views'], 2)


class WindowSinceTests(TestCase):

    def test_period_week(self):
        from creator_insights.services import window_since
        since = window_since('week')
        expected = timezone.now().date() - timedelta(days=6)
        self.assertEqual(since, expected)

    def test_period_month(self):
        from creator_insights.services import window_since
        since = window_since('month')
        expected = timezone.now().date() - timedelta(days=29)
        self.assertEqual(since, expected)

    def test_period_all_returns_none(self):
        from creator_insights.services import window_since
        self.assertIsNone(window_since('all'))

    def test_unknown_period_defaults_to_month(self):
        from creator_insights.services import window_since
        since = window_since('bogus')
        expected = timezone.now().date() - timedelta(days=29)
        self.assertEqual(since, expected)


class TopJokesViewCountFanoutTests(TestCase):
    """BUG 1 — view_count/payoff_count lack distinct=True, causing fan-out
    when reaction/save/share LEFT JOINs multiply JokeView rows.

    Setup: 1 joke, 3 views (2 revealed), 2 reactions, 1 share.
    Without distinct=True the join produces 3*2*1=6 view rows (or some multiple),
    so view_count > 3 and payoff_rate is wrong.
    After the fix: view_count == 3, payoff_rate == 2/3.
    """

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='fanout_creator@svc.com', email='fanout_creator@svc.com', password='x'
        )
        cls.reader1 = User.objects.create_user(
            username='fanout_r1@svc.com', email='fanout_r1@svc.com', password='x'
        )
        cls.reader2 = User.objects.create_user(
            username='fanout_r2@svc.com', email='fanout_r2@svc.com', password='x'
        )

        _, cls.joke = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang, text='Fanout joke'
        )

        # 3 views: 2 revealed, 1 not
        _view(cls.reader1, cls.joke, revealed=True, days_ago=1)
        _view(cls.reader2, cls.joke, revealed=True, days_ago=2)
        _view(cls.reader1, cls.joke, revealed=False, days_ago=3)

        # 2 reactions — these LEFT JOINs would fan out view rows without distinct
        JokeReaction.objects.create(user=cls.reader1, joke=cls.joke, reaction='lol')
        JokeReaction.objects.create(user=cls.reader2, joke=cls.joke, reaction='crying')

        # 1 share — another join multiplier
        ShareEvent.objects.create(joke=cls.joke, user=cls.reader1, platform='whatsapp')

    def test_top_jokes_view_count_not_fanned_out(self):
        """view_count must equal 3 (distinct JokeView PKs), not a multiple."""
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        top = data['top_jokes']
        self.assertEqual(len(top), 1)
        row = top[0]
        self.assertEqual(
            row['views'], 3,
            f"Expected view_count=3 but got {row['views']} — likely fan-out bug (BUG 1)",
        )

    def test_top_jokes_payoff_rate_not_fanned_out(self):
        """payoff_rate must be 2/3 (2 revealed out of 3 distinct views)."""
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        top = data['top_jokes']
        row = top[0]
        self.assertIsNotNone(row['payoff_rate'])
        self.assertAlmostEqual(
            row['payoff_rate'], round(2 / 3, 4), places=4,
            msg=f"Expected payoff_rate≈{round(2/3,4)} but got {row['payoff_rate']} — likely fan-out bug (BUG 1)",
        )


class TopJokesPeriodConsistencyTests(TestCase):
    """BUG 4 — reaction/save/share counts in _top_jokes are all-time while
    view_count is period-filtered.  After the fix, all four metrics use only
    in-period rows.

    Setup: 1 joke.
      - 2 views inside the 'week' window
      - 1 reaction OUTSIDE the window (old)
      - 1 reaction INSIDE the window
    Before fix: reactions == 2 (all-time) even though period='week'.
    After fix:  reactions == 1 (only in-period reaction).
    """

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='period_c_creator@svc.com', email='period_c_creator@svc.com', password='x'
        )
        cls.reader = User.objects.create_user(
            username='period_c_reader@svc.com', email='period_c_reader@svc.com', password='x'
        )

        _, cls.joke = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang, text='Period consistency joke'
        )

        # Views in period (week = last 6 days)
        _view(cls.reader, cls.joke, days_ago=1)
        _view(cls.reader, cls.joke, days_ago=2)

        cls.reader2 = User.objects.create_user(
            username='period_c_reader2@svc.com', email='period_c_reader2@svc.com', password='x'
        )

        # Reaction OUTSIDE week window (40 days ago — all-time but not in-period)
        old_reaction = JokeReaction.objects.create(
            user=cls.reader, joke=cls.joke, reaction='lol'
        )
        JokeReaction.objects.filter(pk=old_reaction.pk).update(
            created_at=timezone.now() - timedelta(days=40)
        )

        # Reaction INSIDE week window (today) — different user so unique_together passes
        JokeReaction.objects.create(user=cls.reader2, joke=cls.joke, reaction='crying')

        # Save OUTSIDE week window
        old_save = SavedJoke.objects.create(user=cls.reader, joke=cls.joke)
        SavedJoke.objects.filter(pk=old_save.pk).update(
            created_at=timezone.now() - timedelta(days=40)
        )

        # Share OUTSIDE week window
        old_share = ShareEvent.objects.create(joke=cls.joke, user=cls.reader, platform='twitter')
        ShareEvent.objects.filter(pk=old_share.pk).update(
            created_at=timezone.now() - timedelta(days=40)
        )

    def test_top_jokes_reactions_period_filtered(self):
        """For period='week', only in-period reactions should be counted."""
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'week')
        top = data['top_jokes']
        self.assertEqual(len(top), 1)
        row = top[0]
        self.assertEqual(
            row['reactions'], 1,
            f"Expected 1 in-period reaction but got {row['reactions']} — BUG 4 (all-time reactions in _top_jokes)",
        )

    def test_top_jokes_saves_period_filtered(self):
        """For period='week', only in-period saves should be counted."""
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'week')
        top = data['top_jokes']
        row = top[0]
        self.assertEqual(
            row['saves'], 0,
            f"Expected 0 in-period saves but got {row['saves']} — BUG 4 (all-time saves in _top_jokes)",
        )

    def test_top_jokes_shares_period_filtered(self):
        """For period='week', only in-period shares should be counted."""
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'week')
        top = data['top_jokes']
        row = top[0]
        self.assertEqual(
            row['shares'], 0,
            f"Expected 0 in-period shares but got {row['shares']} — BUG 4 (all-time shares in _top_jokes)",
        )


class WhatResonatesFanoutTests(TestCase):
    """BUG 2 & BUG 3 — tone_stats in _suggestions/_what_resonates.

    BUG 2: views=Count('id') (JokeView.id) is fanned out by the reactions JOIN
    because distinct=True is missing → reactions_per_view is inflated/wrong.

    BUG 3: reactions Count has no date filter → for period='week' the numerator
    is all-time while the denominator is in-period → reactions_per_view is wrong.

    Setup:
      Tone A: 2 in-period views, 4 all-time reactions (2 in-period + 2 old).
      Tone B: 1 in-period view, 1 in-period reaction.

    Without bug fix for BUG 3 (period='week'):
      Tone A reactions_per_view = 4/2 = 2.0  (WRONG — uses all-time reactions)
      Tone B reactions_per_view = 1/1 = 1.0
      → what_resonates picks Tone A (wrong winner!)

    After fix:
      Tone A reactions_per_view = 2/2 = 1.0  (only in-period reactions)
      Tone B reactions_per_view = 1/1 = 1.0
      → Tie or correct ranking (Tone B wins or ties — the key assertion is that
         Tone A's rate is 1.0, not 2.0, proving in-period filtering works).

    Without BUG 2 fix (with reactions LEFT JOIN), view count for Tone A would be
    fanned out: 2 views × 4 reactions = 8 rows → views=8, reactions_per_view=0.5 (wrong).
    """

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='resonates_creator@svc.com', email='resonates_creator@svc.com', password='x'
        )
        cls.reader = User.objects.create_user(
            username='resonates_reader@svc.com', email='resonates_reader@svc.com', password='x'
        )

        # Get two tones
        tones = list(Tone.objects.all()[:2])
        if len(tones) < 2:
            raise cls.skipTest("Need at least 2 Tone objects in fixture")
        cls.tone_a = tones[0]
        cls.tone_b = tones[1]

        # Joke tagged with Tone A
        _, cls.joke_a = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang, text='Resonates Joke A'
        )
        cls.joke_a.tones.add(cls.tone_a)

        # Joke tagged with Tone B
        _, cls.joke_b = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang, text='Resonates Joke B'
        )
        cls.joke_b.tones.add(cls.tone_b)

        # 2 in-period views on Joke A (within 'week' = last 6 days)
        _view(cls.reader, cls.joke_a, days_ago=1)
        _view(cls.reader, cls.joke_a, days_ago=2)

        cls.reader2 = User.objects.create_user(
            username='resonates_r2@svc.com', email='resonates_r2@svc.com', password='x'
        )
        cls.reader3 = User.objects.create_user(
            username='resonates_r3@svc.com', email='resonates_r3@svc.com', password='x'
        )
        cls.reader4 = User.objects.create_user(
            username='resonates_r4@svc.com', email='resonates_r4@svc.com', password='x'
        )

        # 2 in-period reactions on Joke A (distinct users)
        r_a1 = JokeReaction.objects.create(user=cls.reader, joke=cls.joke_a, reaction='lol')
        r_a2 = JokeReaction.objects.create(user=cls.reader2, joke=cls.joke_a, reaction='crying')

        # 2 OLD reactions on Joke A — distinct users, set old timestamps
        r_a3 = JokeReaction.objects.create(user=cls.reader3, joke=cls.joke_a, reaction='hmm')
        r_a4 = JokeReaction.objects.create(user=cls.reader4, joke=cls.joke_a, reaction='eyeroll')
        JokeReaction.objects.filter(pk__in=[r_a3.pk, r_a4.pk]).update(
            created_at=timezone.now() - timedelta(days=40)
        )

        # 1 in-period view on Joke B
        _view(cls.reader, cls.joke_b, days_ago=1)

        # 1 in-period reaction on Joke B (reader3 didn't react to B yet)
        JokeReaction.objects.create(user=cls.reader3, joke=cls.joke_b, reaction='lol')

    def _get_tone_data(self, data, tone_name):
        """Extract reactions_per_view for a specific tone from what_resonates suggestion."""
        # We need to inspect tone_stats directly; the suggestion only exposes best_tone.
        # Instead, call _suggestions indirectly and introspect the resonates_data.
        what_resonates = next(
            s for s in data['suggestions'] if s['kind'] == 'what_resonates'
        )
        return what_resonates['data']

    def test_what_resonates_views_not_fanned_out_by_reactions(self):
        """BUG 2: Tone A should have 2 views (distinct JokeView PKs), not a fanned-out multiple.

        We use 'all' period so we're only testing the distinct=True fix (BUG 2),
        not the date filter (BUG 3). With 4 reactions and 2 views on Tone A:
          Without distinct: views fanned out → rate != 4/2 = 2.0
          After fix: reactions_per_view = 4/2 = 2.0 for Tone A (best tone wins)

        The definitive check: call _top_jokes directly via build_creator_insights
        and also verify through the suggestions data. We check via _top_jokes that
        view_count is 3 (done in TopJokesViewCountFanoutTests). Here we verify the
        what_resonates rate is 2.0 (Tone A: 4 reactions / 2 distinct views).
        """
        from creator_insights.services import _suggestions, resolve_creator_jokes, window_since
        jokes = resolve_creator_jokes(self.creator)
        since = window_since('all')  # None
        suggestions = _suggestions(self.creator, jokes, since)
        what_resonates = next(s for s in suggestions if s['kind'] == 'what_resonates')
        rate = what_resonates['data']['reactions_per_view']
        self.assertIsNotNone(rate)
        # After distinct fix: best rate = 4 reactions / 2 views = 2.0 for Tone A
        # Without distinct: views fanned out (2 views × 4 reactions = 8 rows) → rate = 4/8 = 0.5
        # or some other wrong value. The key is rate == 2.0 after fix.
        self.assertAlmostEqual(
            rate, 2.0, places=3,
            msg=f"Expected reactions_per_view=2.0 (4 reactions / 2 distinct views) but got {rate} — likely BUG 2 fan-out",
        )

    def test_what_resonates_reactions_are_period_filtered(self):
        """BUG 3: For period='week', only in-period reactions should count.

        Tone A: 2 in-period views, 2 in-period reactions, 2 old reactions.
        Without BUG 3 fix: rate for Tone A = 4/2 = 2.0 (uses all-time reactions).
        After BUG 3 fix: rate for Tone A = 2/2 = 1.0.
        Tone B: 1/1 = 1.0 regardless.
        The best rate should be 1.0, not 2.0.
        """
        from creator_insights.services import _suggestions, resolve_creator_jokes, window_since
        jokes = resolve_creator_jokes(self.creator)
        since = window_since('week')
        suggestions = _suggestions(self.creator, jokes, since)
        what_resonates = next(s for s in suggestions if s['kind'] == 'what_resonates')
        rate = what_resonates['data']['reactions_per_view']
        self.assertIsNotNone(rate)
        # Without fix: 4 all-time reactions / 2 in-period views = 2.0
        # After fix: 2 in-period reactions / 2 in-period views = 1.0
        self.assertAlmostEqual(
            rate, 1.0, places=3,
            msg=f"Expected reactions_per_view=1.0 (in-period only) but got {rate} — likely BUG 3 (all-time reactions)",
        )


class TopJokesMultiRelationFanoutTests(TestCase):
    """PERF #14 — _top_jokes must NOT LEFT-JOIN views × reactions × saves ×
    shares × impressions in one query (the cartesian product that hangs Neon).

    Setup (one joke with rows on ALL five relations simultaneously — the exact
    shape that fans out): 3 views (2 revealed), 2 reactions, 2 saves, 2 shares,
    3 impressions.  A naive multi-JOIN annotate materialises
    3×2×2×2×3 = 72 intermediate rows per joke; the counts must instead be
    exactly the real per-relation totals.
    """

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='mrfanout_creator@svc.com', email='mrfanout_creator@svc.com', password='x'
        )
        cls.r1 = User.objects.create_user(username='mrf_r1@svc.com', email='mrf_r1@svc.com', password='x')
        cls.r2 = User.objects.create_user(username='mrf_r2@svc.com', email='mrf_r2@svc.com', password='x')
        cls.r3 = User.objects.create_user(username='mrf_r3@svc.com', email='mrf_r3@svc.com', password='x')

        _, cls.joke = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang, text='Multi-relation fan-out joke'
        )

        # 3 views (2 revealed) -> views=3, payoff_rate=2/3
        _view(cls.r1, cls.joke, revealed=True, days_ago=1)
        _view(cls.r2, cls.joke, revealed=True, days_ago=2)
        _view(cls.r3, cls.joke, revealed=False, days_ago=3)

        # 2 reactions (distinct users — unique_together user+joke)
        JokeReaction.objects.create(user=cls.r1, joke=cls.joke, reaction='lol')
        JokeReaction.objects.create(user=cls.r2, joke=cls.joke, reaction='crying')

        # 2 saves (distinct users — unique_together user+joke+collection)
        SavedJoke.objects.create(user=cls.r1, joke=cls.joke)
        SavedJoke.objects.create(user=cls.r2, joke=cls.joke)

        # 2 shares (no unique constraint)
        ShareEvent.objects.create(joke=cls.joke, user=cls.r1, platform='whatsapp')
        ShareEvent.objects.create(joke=cls.joke, user=cls.r2, platform='twitter')

        # 3 impressions (no unique constraint)
        JokeImpression.objects.create(user=cls.r1, joke=cls.joke, source='feed')
        JokeImpression.objects.create(user=cls.r2, joke=cls.joke, source='explore')
        JokeImpression.objects.create(user=cls.r3, joke=cls.joke, source='feed')

    def test_counts_are_correct_not_fanned_out(self):
        """Every per-joke count equals the real relation total, not a join product."""
        from creator_insights.services import build_creator_insights
        row = build_creator_insights(self.creator, 'all')['top_jokes'][0]
        self.assertEqual(row['views'], 3)
        self.assertEqual(row['reactions'], 2)
        self.assertEqual(row['saves'], 2)
        self.assertEqual(row['shares'], 2)
        self.assertEqual(row['impressions'], 3)
        self.assertAlmostEqual(row['payoff_rate'], round(2 / 3, 4), places=4)

    def test_top_jokes_query_has_no_multi_relation_join(self):
        """The annotated top-jokes query must compute each metric as its own
        correlated subquery — zero LEFT OUTER JOINs to the five relation tables
        (that JOIN set is exactly the cartesian-product fan-out)."""
        from creator_insights.services import _annotated_top_jokes_qs, resolve_creator_jokes, window_since
        qs = _annotated_top_jokes_qs(resolve_creator_jokes(self.creator), window_since('all'))[:10]
        sql = str(qs.query)
        for model in (JokeView, JokeReaction, SavedJoke, ShareEvent, JokeImpression):
            table = model._meta.db_table
            self.assertNotIn(
                f'LEFT OUTER JOIN "{table}"', sql,
                msg=f'{table} is LEFT-JOINed into the top-jokes query — multi-relation fan-out is back',
            )
            # still referenced (inside its own scalar subquery)
            self.assertIn(f'"{table}"', sql)

    def test_top_jokes_query_count_bounded(self):
        """_top_jokes issues a bounded, constant number of queries (annotate +
        dwell aggregation + watch media-kind lookup + watch aggregation)
        regardless of relation-row volume — no N+1."""
        from creator_insights.services import _top_jokes, resolve_creator_jokes, window_since
        jokes = resolve_creator_jokes(self.creator)
        since = window_since('all')
        with self.assertNumQueries(4):
            _top_jokes(jokes, since)


# =============================================================================
# Task 5: Watch telemetry — per-joke avg_watch_seconds / watch_completion_rate
# in top_jokes. Only meaningful for jokes whose media includes a video/audio
# asset; text/image jokes carry the keys as None (never accrue JokeWatch rows,
# so this is provably a no-op for them). Mirrors the dwell-based
# avg_read_seconds / completion_rate computation style.
# =============================================================================

import shutil
import tempfile

from django.test import override_settings

from jokes.models import JokeMedia, JokeWatch
from jokes.tests_media import make_asset

_WATCH_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_WATCH_MEDIA_ROOT)
class WatchMetricsTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_WATCH_MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.fmt_text = Format.objects.get(slug='oneliner')
        cls.fmt_video = Format.objects.get(slug='video')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='watch_creator@svc.com', email='watch_creator@svc.com', password='x'
        )
        cls.reader = User.objects.create_user(
            username='watch_reader@svc.com', email='watch_reader@svc.com', password='x'
        )

        cls._, cls.text_joke = _make_published_submission(
            cls.creator, cls.fmt_text, cls.age, cls.lang, text='Text joke'
        )
        cls._, cls.video_joke = _make_published_submission(
            cls.creator, cls.fmt_video, cls.age, cls.lang, text='Video joke'
        )
        asset = make_asset(cls.creator, kind='video', duration_ms=8000)
        JokeMedia.objects.create(joke=cls.video_joke, asset=asset, position=0)

        # A view each so both jokes surface deterministically in top_jokes.
        _view(cls.reader, cls.text_joke, revealed=True, source='explore')
        _view(cls.reader, cls.video_joke, revealed=True, source='explore')

    def _row(self, data, joke_id):
        return next(r for r in data['top_jokes'] if r['id'] == joke_id)

    def test_keys_present_and_null_for_text_joke(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        row = self._row(data, self.text_joke.id)
        self.assertIn('avg_watch_seconds', row)
        self.assertIn('watch_completion_rate', row)
        self.assertIsNone(row['avg_watch_seconds'])
        self.assertIsNone(row['watch_completion_rate'])
        # Untouched existing stat, proving the addition is neutral for text jokes.
        self.assertEqual(row['payoff_rate'], 1.0)

    def test_keys_null_for_video_joke_without_watch_samples(self):
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        row = self._row(data, self.video_joke.id)
        self.assertIsNone(row['avg_watch_seconds'])
        self.assertIsNone(row['watch_completion_rate'])

    def test_avg_watch_seconds_and_completion_rate_computed(self):
        from creator_insights.services import build_creator_insights
        # 4 watch samples: 2000, 6000, 8000, 10000 ms -> avg 6.5s.
        # watch_pct on 3 of 4 rows: 50, 95, 100 -> 2 of 3 >= 90 -> completion 0.6667.
        for ms, pct in [(2000, 50), (6000, 95), (8000, 100), (10000, None)]:
            JokeWatch.objects.create(
                user=self.reader, joke=self.video_joke, watch_ms=ms, watch_pct=pct,
                source='feed',
            )
        data = build_creator_insights(self.creator, 'all')
        row = self._row(data, self.video_joke.id)
        self.assertEqual(row['avg_watch_seconds'], 6.5)
        self.assertEqual(row['watch_completion_rate'], round(2 / 3, 4))

        # Text joke stays null — no cross-joke leakage from the video joke's
        # watch rows — and its other stats are unaffected.
        text_row = self._row(data, self.text_joke.id)
        self.assertIsNone(text_row['avg_watch_seconds'])
        self.assertIsNone(text_row['watch_completion_rate'])
        self.assertEqual(text_row['payoff_rate'], 1.0)

    def test_watch_completion_rate_null_without_pct_samples(self):
        from creator_insights.services import build_creator_insights
        JokeWatch.objects.create(
            user=self.reader, joke=self.video_joke, watch_ms=5000, watch_pct=None,
            source='feed',
        )
        data = build_creator_insights(self.creator, 'all')
        row = self._row(data, self.video_joke.id)
        self.assertEqual(row['avg_watch_seconds'], 5.0)
        self.assertIsNone(row['watch_completion_rate'])
