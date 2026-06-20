"""Tests for public identity (display_name/handle) — never derived from email."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from jokes.identity import (
    public_display_name, public_handle, normalize_handle, is_valid_handle,
)

User = get_user_model()

PROFILE_URL = '/api/v1/users/me/profile/'


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
