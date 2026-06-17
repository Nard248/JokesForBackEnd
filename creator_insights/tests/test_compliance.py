"""
Compliance tests for creator_insights:

1. Owner-scoped tier bypass: creator sees their own tier_2 joke counted in insights.
2. No cross-user PII leak: no other user's email/username appears in the response.
3. Strict creator scope: jokes from another creator never appear in this creator's top_jokes.
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from jokes.models import (
    Format, AgeRating, Language, Joke, JokeSubmission, JokeView,
    JokeReaction, SavedJoke,
)

User = get_user_model()

INSIGHTS_URL = '/api/v1/creators/me/insights/'


def _make_joke(fmt, age, lang, text='Compliance test', content_tier='tier_1'):
    with patch('jokes.models.Joke._generate_share_image'):
        j = Joke.objects.create(
            text=text, format=fmt, age_rating=age, language=lang,
            content_tier=content_tier,
        )
    return j


def _make_published_submission(user, fmt, age, lang, text='Compliance test',
                                content_tier='tier_1'):
    joke = _make_joke(fmt, age, lang, text=text, content_tier=content_tier)
    JokeSubmission.objects.create(
        user=user,
        format=fmt,
        age_rating=age,
        language=lang,
        status='published',
        text=joke.text,
        published_joke=joke,
    )
    return joke


class OwnerTierBypassTests(TestCase):
    """Creator must see their own tier_2 joke counted in their insights."""

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='tier2_comp@test.com',
            email='tier2_comp@test.com',
            password='x',
        )
        cls.reader = User.objects.create_user(
            username='tier2_reader@test.com',
            email='tier2_reader@test.com',
            password='x',
        )

        # Creator has a tier_2 joke
        cls.tier2_joke = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang,
            text='Mature tier_2 joke', content_tier='tier_2',
        )
        # Add a view on the tier_2 joke
        JokeView.objects.create(
            user=cls.reader, joke=cls.tier2_joke, revealed_punchline=True,
            viewed_date=cls.tier2_joke.created_at.date(),
        )

    def test_creator_sees_own_tier2_joke_in_published_count(self):
        """Owner bypass: the tier_2 joke must count in published_jokes."""
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        self.assertGreaterEqual(data['overview']['published_jokes'], 1)

    def test_creator_sees_own_tier2_joke_views_counted(self):
        """Views on the tier_2 joke must be counted in total views."""
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        self.assertGreaterEqual(data['overview']['views'], 1)

    def test_creator_sees_own_tier2_in_top_jokes(self):
        """The tier_2 joke must appear in top_jokes (not hidden)."""
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        joke_ids = {j['id'] for j in data['top_jokes']}
        self.assertIn(self.tier2_joke.id, joke_ids)

    def test_via_endpoint(self):
        """Endpoint: tier_2 joke shows up in creator's insights response."""
        client = APIClient()
        client.force_authenticate(self.creator)
        response = client.get(INSIGHTS_URL + '?period=all')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(data['overview']['published_jokes'], 1)


class NoPIILeakTests(TestCase):
    """No engaging user's email or username should appear in the insights response."""

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='pii_creator@test.com',
            email='pii_creator@test.com',
            password='x',
        )
        # This user's email must NOT leak into the response
        cls.audience_user = User.objects.create_user(
            username='secret_audience@private.com',
            email='secret_audience@private.com',
            password='x',
        )

        cls.joke = _make_published_submission(
            cls.creator, cls.fmt, cls.age, cls.lang, text='PII test joke'
        )
        JokeView.objects.create(
            user=cls.audience_user, joke=cls.joke, revealed_punchline=False,
            viewed_date=cls.joke.created_at.date(),
        )
        JokeReaction.objects.create(
            user=cls.audience_user, joke=cls.joke, reaction='lol'
        )

    def test_audience_email_not_in_response(self):
        """The audience user's email must not appear anywhere in the JSON response."""
        client = APIClient()
        client.force_authenticate(self.creator)
        response = client.get(INSIGHTS_URL + '?period=all')
        response_text = response.content.decode('utf-8')
        self.assertNotIn('secret_audience@private.com', response_text,
                         'Audience user email leaked into creator insights response')

    def test_audience_username_not_in_response(self):
        """The audience user's username must not appear in the JSON response."""
        client = APIClient()
        client.force_authenticate(self.creator)
        response = client.get(INSIGHTS_URL + '?period=all')
        response_text = response.content.decode('utf-8')
        self.assertNotIn('secret_audience', response_text,
                         'Audience username leaked into creator insights response')

    def test_response_has_no_user_id_fields_in_audience(self):
        """Audience composition returns only aggregate label/count — no user IDs."""
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator, 'all')
        aud = data['audience']
        for key in ('top_themes', 'top_categories', 'top_formats'):
            for item in aud[key]:
                self.assertNotIn('user', item)
                self.assertNotIn('user_id', item)
                self.assertNotIn('email', item)
                self.assertIn('label', item)
                self.assertIn('count', item)


class CreatorScopeIsolationTests(TestCase):
    """Jokes from another creator must never appear in this creator's insights."""

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator_a = User.objects.create_user(
            username='scope_a@test.com', email='scope_a@test.com', password='x'
        )
        cls.creator_b = User.objects.create_user(
            username='scope_b@test.com', email='scope_b@test.com', password='x'
        )
        cls.reader = User.objects.create_user(
            username='scope_reader@test.com', email='scope_reader@test.com', password='x'
        )

        cls.joke_a = _make_published_submission(
            cls.creator_a, cls.fmt, cls.age, cls.lang, text='Creator A joke'
        )
        cls.joke_b = _make_published_submission(
            cls.creator_b, cls.fmt, cls.age, cls.lang, text='Creator B joke'
        )

        # Both jokes have views
        JokeView.objects.create(
            user=cls.reader, joke=cls.joke_a, viewed_date=cls.joke_a.created_at.date()
        )
        JokeView.objects.create(
            user=cls.reader, joke=cls.joke_b, viewed_date=cls.joke_b.created_at.date()
        )

    def test_creator_a_top_jokes_excludes_creator_b_jokes(self):
        """Creator A's insights must not include Creator B's joke."""
        from creator_insights.services import build_creator_insights
        data = build_creator_insights(self.creator_a, 'all')
        joke_ids = {j['id'] for j in data['top_jokes']}
        self.assertNotIn(self.joke_b.id, joke_ids,
                         'Creator B\'s joke appeared in Creator A\'s top_jokes')

    def test_creator_a_views_count_excludes_creator_b_views(self):
        """Creator A's view count should only count views on their own jokes."""
        from creator_insights.services import build_creator_insights
        data_a = build_creator_insights(self.creator_a, 'all')
        # Creator A has exactly 1 view (on joke_a); joke_b's view should not count
        self.assertEqual(data_a['overview']['views'], 1)

    def test_via_endpoint_scope_isolation(self):
        """Endpoint: Creator A's response never references Creator B's joke."""
        client = APIClient()
        client.force_authenticate(self.creator_a)
        response = client.get(INSIGHTS_URL + '?period=all')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        joke_ids = {j['id'] for j in data['top_jokes']}
        self.assertNotIn(self.joke_b.id, joke_ids)
