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

    def test_jokes_list_present_and_tier_1_visible(self):
        """Anon viewer gets a jokes array containing the tier_1 joke."""
        response = self.client.get(self._url())
        self.assertIn('jokes', response.data)
        ids = {row['id'] for row in response.data['jokes']}
        self.assertIn(self.joke.id, ids)

    def test_jokes_pagination_block(self):
        response = self.client.get(self._url())
        self.assertIn('jokes_pagination', response.data)
        self.assertEqual(response.data['jokes_pagination']['count'], 1)

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


class CreatorProfileTierFilterTests(APITestCase):
    """Public profile MUST re-apply allowed_tiers(request) to the jokes list.

    anon/minor: tier_1 only; adult opted-in: tier_1 + tier_2; tier_3: never served.
    """

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='tier_creator@test.com', email='tier_creator@test.com', password='x',
        )
        cls.t1 = _make_joke(cls.fmt, cls.age, cls.lang, text='Tier1 joke',
                            content_tier='tier_1', creator=cls.creator)
        _publish_submission(cls.creator, cls.fmt, cls.age, cls.lang, cls.t1)
        cls.t2 = _make_joke(cls.fmt, cls.age, cls.lang, text='Tier2 joke',
                            content_tier='tier_2', creator=cls.creator)
        _publish_submission(cls.creator, cls.fmt, cls.age, cls.lang, cls.t2)
        cls.t3 = _make_joke(cls.fmt, cls.age, cls.lang, text='Tier3 joke',
                            content_tier='tier_3', creator=cls.creator)
        _publish_submission(cls.creator, cls.fmt, cls.age, cls.lang, cls.t3)

        # Adult opted-in viewer (18+, show_mature=True)
        from datetime import date
        cls.adult = User.objects.create_user(
            username='adult_viewer@test.com', email='adult_viewer@test.com', password='x',
        )
        cls.adult.profile.date_of_birth = date(1990, 1, 1)
        cls.adult.profile.save(update_fields=['date_of_birth'])
        cls.adult.preference.show_mature = True
        cls.adult.preference.save(update_fields=['show_mature'])

    def _url(self):
        return reverse('creator-profile', kwargs={'creator_id': self.creator.pk})

    def test_anon_sees_only_tier_1(self):
        response = self.client.get(self._url())
        ids = {row['id'] for row in response.data['jokes']}
        self.assertEqual(ids, {self.t1.id})
        self.assertEqual(response.data['published_jokes'], 1)

    def test_adult_optedin_sees_tier_1_and_tier_2(self):
        self.client.force_authenticate(user=self.adult)
        response = self.client.get(self._url())
        ids = {row['id'] for row in response.data['jokes']}
        self.assertEqual(ids, {self.t1.id, self.t2.id})

    def test_tier_3_never_served(self):
        # Even the opted-in adult never sees tier_3
        self.client.force_authenticate(user=self.adult)
        response = self.client.get(self._url())
        ids = {row['id'] for row in response.data['jokes']}
        self.assertNotIn(self.t3.id, ids)


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
