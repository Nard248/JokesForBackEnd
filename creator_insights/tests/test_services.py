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
    JokeView, JokeReaction, Favorite, SavedJoke, ShareEvent,
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
