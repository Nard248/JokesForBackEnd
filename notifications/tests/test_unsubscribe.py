from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase
from django.urls import reverse
from freezegun import freeze_time

from jokes.models import UserProfile
from notifications.unsubscribe import (
    MAX_AGE_SECONDS,
    SALT,
    load_unsubscribe_token,
    unsubscribe_token,
)

User = get_user_model()


class UnsubscribeTokenTests(TestCase):
    """unsubscribe_token / load_unsubscribe_token round-trip (Task 2 embeds
    the token via unsubscribe_token; this covers the helper in isolation)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='reader@example.com', email='reader@example.com', password='pw',
        )

    def test_round_trips_uid_and_type(self):
        token = unsubscribe_token(self.user, 'digest')
        data = load_unsubscribe_token(token)
        self.assertEqual(data['uid'], self.user.pk)
        self.assertEqual(data['type'], 'digest')

    def test_token_carries_no_pii_in_plaintext(self):
        # The token must not leak identity beyond the opaque signed blob —
        # no email/username in the unsigned querystring representation.
        token = unsubscribe_token(self.user, 'milestone')
        self.assertNotIn(self.user.email, token)
        self.assertNotIn('reader', token)


class UnsubscribeViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='reader2@example.com', email='reader2@example.com', password='pw',
        )
        # Signal auto-creates the profile; both opt-ins default True.
        self.profile = self.user.profile
        self.url = reverse('email-unsubscribe')

    def _get(self, token):
        return self.client.get(self.url, {'token': token})

    def test_valid_digest_token_flips_flag_and_confirms(self):
        token = unsubscribe_token(self.user, 'digest')
        response = self._get(token)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'unsubscribed', response.content.lower())
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.email_digest_opt_in)
        self.assertTrue(self.profile.creator_milestone_opt_in)  # untouched

    def test_digest_unsubscribe_is_idempotent(self):
        token = unsubscribe_token(self.user, 'digest')
        first = self._get(token)
        second = self._get(token)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.email_digest_opt_in)

    def test_valid_milestone_token_flips_only_milestone_flag(self):
        token = unsubscribe_token(self.user, 'milestone')
        response = self._get(token)

        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.creator_milestone_opt_in)
        self.assertTrue(self.profile.email_digest_opt_in)  # untouched

    def test_tampered_token_returns_friendly_error_not_500(self):
        token = unsubscribe_token(self.user, 'digest')
        tampered = token[:-1] + ('a' if token[-1] != 'a' else 'b')

        response = self._get(tampered)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.get('Content-Type', '').startswith('text/html'))
        self.assertNotIn(b'Traceback', response.content)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.email_digest_opt_in)  # unchanged

    def test_expired_token_returns_friendly_error_not_500(self):
        signed_at = '2026-01-01 00:00:00'
        with freeze_time(signed_at):
            token = unsubscribe_token(self.user, 'digest')

        past_max_age = timedelta(seconds=MAX_AGE_SECONDS + 3600)
        with freeze_time(signed_at) as frozen:
            frozen.move_to(frozen.time_to_freeze + past_max_age)
            response = self._get(token)

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b'Traceback', response.content)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.email_digest_opt_in)  # unchanged

    def test_garbage_token_returns_friendly_error_not_500(self):
        response = self._get('not-a-real-token')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b'Traceback', response.content)

    def test_unknown_kind_in_signed_payload_is_rejected(self):
        bogus = signing.dumps({'uid': self.user.pk, 'type': 'not-a-kind'}, salt=SALT)
        response = self._get(bogus)
        self.assertEqual(response.status_code, 400)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.email_digest_opt_in)


class UserProfileDefaultsTests(TestCase):
    def test_new_profile_defaults_both_flags_true(self):
        user = User.objects.create_user(
            username='new@example.com', email='new@example.com', password='pw',
        )
        profile = UserProfile.objects.get(user=user)
        self.assertTrue(profile.email_digest_opt_in)
        self.assertTrue(profile.creator_milestone_opt_in)
