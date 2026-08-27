"""Achievements must be earnable.

Twelve Achievement rows are seeded and rendered in the profile UI, but no code
path ever created a UserAchievement -- `grep UserAchievement.objects.create`
matched nothing outside migrations. `criteria_type`/`criteria_value` were
decorative, so every badge read `unlocked: false` forever no matter what the
reader did. A shipped, visible, permanently-empty feature can only discourage.

Evaluation is request-triggered (this project runs a single Cloud Run service:
no Celery, no cron, no workers), idempotent, and never un-awards.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from jokes.models import (
    Achievement,
    AgeRating,
    Favorite,
    Format,
    Joke,
    Language,
    SavedJoke,
    UserAchievement,
)

User = get_user_model()


def _joke(i):
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text=f'Achievement fodder {i}.',
            format=Format.objects.get(slug='oneliner'),
            age_rating=AgeRating.objects.first(),
            language=Language.objects.get(code='en'),
        )


class AchievementUnlockTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='ach@example.com', email='ach@example.com', password='pw',
        )
        self.client.force_authenticate(user=self.user)
        Achievement.objects.get_or_create(
            slug='first-save',
            defaults={
                'title': 'First Save', 'description': 'Saved a joke.',
                'icon': 'bookmark', 'criteria_type': 'save_count', 'criteria_value': 1,
            },
        )
        Achievement.objects.get_or_create(
            slug='ten-saves',
            defaults={
                'title': 'Ten Saves', 'description': 'Saved ten jokes.',
                'icon': 'bookmark', 'criteria_type': 'save_count', 'criteria_value': 10,
            },
        )
        Achievement.objects.get_or_create(
            slug='first-favorite',
            defaults={
                'title': 'First Favorite', 'description': 'Favorited a joke.',
                'icon': 'heart', 'criteria_type': 'favorite_count', 'criteria_value': 1,
            },
        )

    def _badges(self):
        resp = self.client.get('/api/v1/users/me/achievements/')
        self.assertEqual(resp.status_code, 200, resp.content)
        return {b['id']: b for b in resp.json()['results']}

    def test_nothing_is_unlocked_before_the_user_does_anything(self):
        self.assertFalse(any(b['unlocked'] for b in self._badges().values()))

    def test_crossing_a_threshold_unlocks_the_badge(self):
        SavedJoke.objects.create(user=self.user, joke=_joke(1))

        badges = self._badges()
        self.assertTrue(badges['first-save']['unlocked'])
        self.assertIsNotNone(badges['first-save']['unlocked_at'])
        self.assertFalse(badges['ten-saves']['unlocked'], 'threshold not reached yet')

    def test_higher_threshold_unlocks_only_when_reached(self):
        for i in range(10):
            SavedJoke.objects.create(user=self.user, joke=_joke(100 + i))
        badges = self._badges()
        self.assertTrue(badges['first-save']['unlocked'])
        self.assertTrue(badges['ten-saves']['unlocked'])

    def test_a_different_metric_unlocks_independently(self):
        Favorite.objects.create(user=self.user, joke=_joke(2))
        badges = self._badges()
        self.assertTrue(badges['first-favorite']['unlocked'])
        self.assertFalse(badges['first-save']['unlocked'])

    def test_evaluation_is_idempotent(self):
        SavedJoke.objects.create(user=self.user, joke=_joke(3))
        self._badges()
        self._badges()
        self.assertEqual(
            UserAchievement.objects.filter(
                user=self.user, achievement__slug='first-save',
            ).count(),
            1,
        )

    def test_an_award_is_never_revoked(self):
        saved = SavedJoke.objects.create(user=self.user, joke=_joke(4))
        self._badges()
        saved.delete()  # user un-saves; the badge they earned stays earned
        self.assertTrue(self._badges()['first-save']['unlocked'])

    def test_one_users_activity_does_not_unlock_anothers_badge(self):
        other = User.objects.create_user(
            username='other@example.com', email='other@example.com', password='pw',
        )
        SavedJoke.objects.create(user=other, joke=_joke(5))
        self.assertFalse(self._badges()['first-save']['unlocked'])


class AllSeededCriteriaResolveTests(APITestCase):
    """Every criteria_type the seed ships must resolve without raising.

    The engine looks up counts via related names; a wrong one would raise
    AttributeError on the profile page for real users while unit tests that
    only exercise save_count/favorite_count stayed green.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='allmetrics@example.com', email='allmetrics@example.com', password='pw',
        )
        self.client.force_authenticate(user=self.user)

    def test_seeded_achievements_cover_more_than_two_metrics(self):
        from django.core.management import call_command
        call_command('seed_achievements', verbosity=0)
        kinds = set(Achievement.objects.values_list('criteria_type', flat=True))
        self.assertGreaterEqual(len(kinds), 5, f'seed only covers {kinds}')

    def test_endpoint_evaluates_every_seeded_criteria_type_without_error(self):
        from django.core.management import call_command
        call_command('seed_achievements', verbosity=0)

        resp = self.client.get('/api/v1/users/me/achievements/')

        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            len(resp.json()['results']), Achievement.objects.count(),
        )

    def test_unknown_criteria_type_is_ignored_not_awarded(self):
        Achievement.objects.create(
            slug='bogus-metric', title='Bogus', description='typo in seed',
            icon='x', criteria_type='not_a_real_metric', criteria_value=1,
        )
        resp = self.client.get('/api/v1/users/me/achievements/')
        self.assertEqual(resp.status_code, 200, resp.content)
        badge = next(b for b in resp.json()['results'] if b['id'] == 'bogus-metric')
        self.assertFalse(badge['unlocked'])
