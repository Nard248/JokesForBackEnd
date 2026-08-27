"""Tests for public identity (display_name/handle) — never derived from email."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from jokes.identity import (
    is_valid_handle,
    normalize_handle,
    public_display_name,
    public_handle,
)
from jokes.models import AgeRating, Format, JokeSubmission, Language

User = get_user_model()

PROFILE_URL = '/api/v1/users/me/profile/'
TOP_JOKESTERS_URL = '/api/v1/users/top-jokesters/'


class IdentityHelperTests(TestCase):
    def test_display_name_chosen_then_realname_then_opaque(self):
        u = User.objects.create_user(username='a@x.com', email='a@x.com', password='x')
        self.assertEqual(public_display_name(u), f'user_{u.pk}')
        u.first_name, u.last_name = 'Jane', 'Doe'
        u.save()
        self.assertEqual(public_display_name(u), 'Jane Doe')
        u.profile.display_name = 'Funny Jane'
        u.profile.save()
        self.assertEqual(public_display_name(u), 'Funny Jane')

    def test_handle_chosen_then_opaque(self):
        u = User.objects.create_user(username='b@x.com', email='b@x.com', password='x')
        self.assertEqual(public_handle(u), f'@user{u.pk}')
        u.profile.handle = 'janedoe'
        u.profile.save()
        self.assertEqual(public_handle(u), '@janedoe')

    def test_handle_never_falls_back_to_the_username(self):
        """username is NOT a handle and must never be published.

        Registration stores the full email there, and allauth's social signup
        stores the email's LOCAL PART — which looks like a valid handle. It is
        also outside the UserProfile.handle uniqueness check, so publishing it
        would let two accounts render the same @handle.
        """
        u = User.objects.create_user(
            username='pipetest26', email='pipe@x.com', password='x',
        )
        self.assertEqual(public_handle(u), f'@user{u.pk}')

    def test_an_email_local_part_username_is_never_published(self):
        """The Google signup path stores the email local part as username."""
        u = User.objects.create_user(
            username='janedoe', email='janedoe@gmail.com', password='x',
        )
        self.assertNotIn('janedoe', public_handle(u))
        self.assertEqual(public_handle(u), f'@user{u.pk}')

    def test_chosen_profile_handle_is_what_gets_published(self):
        u = User.objects.create_user(username='fromsignup', email='c@x.com', password='x')
        u.profile.handle = 'chosenlater'
        u.profile.save()
        self.assertEqual(public_handle(u), '@chosenlater')

    def test_never_leak_email(self):
        u = User.objects.create_user(username='secretlocal@x.com', email='secretlocal@x.com', password='x')
        self.assertNotIn('secretlocal', public_display_name(u))
        self.assertNotIn('secretlocal', public_handle(u))

    def test_normalize_and_validate(self):
        self.assertEqual(normalize_handle('  @JaneDoe '), 'janedoe')
        self.assertEqual(normalize_handle(''), '')
        self.assertTrue(is_valid_handle('jane_doe1'))
        self.assertFalse(is_valid_handle('ab'))       # too short
        self.assertFalse(is_valid_handle('Jane'))     # uppercase (not normalized)
        self.assertFalse(is_valid_handle('a b'))      # space


class ProfileHandlePatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='c@x.com', email='c@x.com', password='pw')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_set_display_name_and_handle_normalized(self):
        r = self.client.patch(PROFILE_URL, {'display_name': 'Cee', 'handle': '@CoolCee'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.display_name, 'Cee')
        self.assertEqual(self.user.profile.handle, 'coolcee')
        self.assertEqual(r.data['handle'], 'coolcee')
        self.assertEqual(r.data['username'], '@coolcee')
        self.assertEqual(r.data['name'], 'Cee')

    def test_invalid_handle_rejected(self):
        r = self.client.patch(PROFILE_URL, {'handle': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('handle', r.data)

    def test_duplicate_handle_rejected(self):
        other = User.objects.create_user(username='d@x.com', email='d@x.com', password='pw')
        other.profile.handle = 'taken'
        other.profile.save()
        r = self.client.patch(PROFILE_URL, {'handle': 'TAKEN'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('handle', r.data)

    def test_clear_handle(self):
        self.user.profile.handle = 'cee'
        self.user.profile.save()
        r = self.client.patch(PROFILE_URL, {'handle': ''}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.user.profile.refresh_from_db()
        self.assertIsNone(self.user.profile.handle)


class TopJokestersIdentityTests(TestCase):
    """The public leaderboard (AllowAny) must use chosen identity, never email."""

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')
        cls.user = User.objects.create_user(
            username='jokester@secretdomain.com', email='jokester@secretdomain.com', password='x',
        )
        cls.user.profile.display_name = 'Top Comic'
        cls.user.profile.handle = 'topcomic'
        cls.user.profile.save()
        JokeSubmission.objects.create(
            user=cls.user, format=cls.fmt, age_rating=cls.age,
            language=cls.lang, status='published', text='A published bit',
        )

    def test_leaderboard_uses_handle_and_never_leaks_email(self):
        r = self.client.get(TOP_JOKESTERS_URL)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('secretdomain', r.content.decode())
        entry = next(e for e in r.data['results'] if e['id'] == self.user.pk)
        self.assertEqual(entry['name'], 'Top Comic')
        self.assertEqual(entry['username'], '@topcomic')
