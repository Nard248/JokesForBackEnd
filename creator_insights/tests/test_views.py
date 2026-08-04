"""
Tests for the CreatorInsightsView endpoint.

Covers:
  - 200 shape for a creator
  - period param is respected and echoed
  - 401 for unauthenticated
  - 403 for authenticated non-creator
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from rest_framework.test import APIClient

from jokes.models import AgeRating, Format, Joke, JokeSubmission, Language

User = get_user_model()


def _make_joke(fmt, age, lang, text='View Test Joke'):
    with patch('jokes.models.Joke._generate_share_image'):
        j = Joke.objects.create(text=text, format=fmt, age_rating=age, language=lang)
    return j


def _make_published_submission(user, fmt, age, lang, text='View Test Joke'):
    joke = _make_joke(fmt, age, lang, text=text)
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


INSIGHTS_URL = '/api/v1/creators/me/insights/'


class CreatorInsightsViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='view_creator@test.com',
            email='view_creator@test.com',
            password='x',
        )
        _make_published_submission(cls.creator, cls.fmt, cls.age, cls.lang)

        cls.non_creator = User.objects.create_user(
            username='view_noncreator@test.com',
            email='view_noncreator@test.com',
            password='x',
        )

    def setUp(self):
        self.client = APIClient()

    def test_creator_gets_200_with_expected_shape(self):
        self.client.force_authenticate(self.creator)
        response = self.client.get(INSIGHTS_URL)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        required_keys = {
            'period', 'is_creator', 'overview', 'reactions_breakdown',
            'shares_breakdown', 'source_mix', 'top_jokes', 'audience', 'suggestions',
        }
        self.assertTrue(required_keys.issubset(data.keys()),
                        f'Missing keys: {required_keys - data.keys()}')

    def test_overview_fields_present(self):
        self.client.force_authenticate(self.creator)
        response = self.client.get(INSIGHTS_URL)
        overview = response.json()['overview']
        required = {'published_jokes', 'reach', 'views', 'payoff_rate',
                    'reactions', 'favorites', 'saves', 'shares',
                    'peak_read_hour', 'daily_reach_28d'}
        self.assertTrue(required.issubset(overview.keys()))

    def test_default_period_is_month(self):
        self.client.force_authenticate(self.creator)
        response = self.client.get(INSIGHTS_URL)
        self.assertEqual(response.json()['period'], 'month')

    def test_week_period_param_is_echoed(self):
        self.client.force_authenticate(self.creator)
        response = self.client.get(INSIGHTS_URL + '?period=week')
        self.assertEqual(response.json()['period'], 'week')

    def test_all_period_param_is_echoed(self):
        self.client.force_authenticate(self.creator)
        response = self.client.get(INSIGHTS_URL + '?period=all')
        self.assertEqual(response.json()['period'], 'all')

    def test_unauthenticated_gets_401(self):
        response = self.client.get(INSIGHTS_URL)
        self.assertEqual(response.status_code, 401)

    def test_non_creator_gets_403(self):
        self.client.force_authenticate(self.non_creator)
        response = self.client.get(INSIGHTS_URL)
        self.assertEqual(response.status_code, 403)

    def test_url_resolves_by_name(self):
        try:
            url = reverse('creator-insights')
            self.assertEqual(url, INSIGHTS_URL)
        except NoReverseMatch:
            self.fail("URL name 'creator-insights' did not resolve.")

    def test_is_creator_flag_is_true(self):
        self.client.force_authenticate(self.creator)
        response = self.client.get(INSIGHTS_URL)
        self.assertTrue(response.json()['is_creator'])

    def test_suggestions_has_three_kinds(self):
        self.client.force_authenticate(self.creator)
        response = self.client.get(INSIGHTS_URL)
        kinds = {s['kind'] for s in response.json()['suggestions']}
        self.assertIn('peak_hour', kinds)
        self.assertIn('what_resonates', kinds)
        self.assertIn('consistency', kinds)
