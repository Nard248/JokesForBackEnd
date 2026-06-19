"""Tests for the public CreatorProfileView."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from follows.models import Follow
from jokes.models import Format, AgeRating, Language, Joke, JokeSubmission

User = get_user_model()


def _make_joke(fmt, age, lang, text='Test', content_tier='tier_1', creator=None):
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text=text, format=fmt, age_rating=age, language=lang,
            content_tier=content_tier, creator=creator,
        )


def _publish_submission(user, fmt, age, lang, joke):
    return JokeSubmission.objects.create(
        user=user, format=fmt, age_rating=age, language=lang,
        status='published', text=joke.text, published_joke=joke,
    )


class CreatorProfileViewTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='profile_creator@test.com',
            email='profile_creator@test.com',
            password='x',
            first_name='Alice',
        )
        cls.viewer = User.objects.create_user(
            username='profile_viewer@test.com',
            email='profile_viewer@test.com',
            password='x',
        )

        # Creator has one published joke (FK-stamped)
        cls.joke = _make_joke(cls.fmt, cls.age, cls.lang, text='Profile joke', creator=cls.creator)
        _publish_submission(cls.creator, cls.fmt, cls.age, cls.lang, cls.joke)

    def setUp(self):
        self.client = APIClient()
        Follow.objects.all().delete()

    def _url(self, creator_id=None):
        return reverse('creator-profile', kwargs={'creator_id': creator_id or self.creator.pk})

    def test_returns_200_for_creator_with_published_jokes(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_response_shape(self):
        response = self.client.get(self._url())
        data = response.data
        self.assertIn('id', data)
        self.assertIn('display_name', data)
        self.assertIn('handle', data)
        self.assertIn('published_jokes', data)
        self.assertIn('follower_count', data)
        self.assertIn('is_following', data)

    def test_published_jokes_count(self):
        response = self.client.get(self._url())
        self.assertEqual(response.data['published_jokes'], 1)

    def test_follower_count_zero(self):
        response = self.client.get(self._url())
        self.assertEqual(response.data['follower_count'], 0)

    def test_follower_count_with_followers(self):
        from follows.services import follow
        follow(self.viewer, self.creator)
        response = self.client.get(self._url())
        self.assertEqual(response.data['follower_count'], 1)

    def test_is_following_null_for_anonymous(self):
        response = self.client.get(self._url())
        self.assertIsNone(response.data['is_following'])

    def test_is_following_false_when_not_following(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(self._url())
        self.assertFalse(response.data['is_following'])

    def test_is_following_true_when_following(self):
        from follows.services import follow
        follow(self.viewer, self.creator)
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(self._url())
        self.assertTrue(response.data['is_following'])

    def test_is_following_null_when_viewing_own_profile(self):
        self.client.force_authenticate(user=self.creator)
        response = self.client.get(self._url())
        self.assertIsNone(response.data['is_following'])

    def test_display_name_uses_first_name(self):
        response = self.client.get(self._url())
        self.assertEqual(response.data['display_name'], 'Alice')

    def test_handle_format(self):
        response = self.client.get(self._url())
        self.assertTrue(response.data['handle'].startswith('@'))

    def test_404_for_nonexistent_user(self):
        url = reverse('creator-profile', kwargs={'creator_id': 999999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_404_for_user_with_no_published_jokes(self):
        bare = User.objects.create_user(
            username='bare_profile@test.com',
            email='bare_profile@test.com',
            password='x',
        )
        url = reverse('creator-profile', kwargs={'creator_id': bare.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_no_email_in_response(self):
        response = self.client.get(self._url())
        self.assertNotIn('email', response.data)


class CreatorProfileFallbackJokeTests(APITestCase):
    """Creator with null-creator jokes (legacy) still appears on the profile via submission join."""

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='legacy_profile@test.com',
            email='legacy_profile@test.com',
            password='x',
        )
        # Null-creator (legacy) joke linked via submission
        cls.legacy_joke = _make_joke(cls.fmt, cls.age, cls.lang, text='Legacy joke', creator=None)
        _publish_submission(cls.creator, cls.fmt, cls.age, cls.lang, cls.legacy_joke)

    def test_profile_visible_for_null_creator_via_submission(self):
        url = reverse('creator-profile', kwargs={'creator_id': self.creator.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['published_jokes'], 1)
