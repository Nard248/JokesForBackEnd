"""COPPA age-gate tests for the Google OAuth signup path (fix/google-age-gate).

The email/password path collects date_of_birth and rejects under-13 users. The
Google path was a bare SocialLoginView that auto-created a live account with
date_of_birth = NULL, letting a child bypass the gate. SocialAccountAdapter
(JokesForProject/adapters.py) closes this. These tests drive the real endpoint
with the Google token/identity exchange mocked, exercising the full pipeline
(serializer -> complete_social_login -> adapter -> save_user).

Four contract cases:
  1. Existing linked Google user, NO date_of_birth -> logs in, DOB untouched.
  2. New user, NO date_of_birth -> 400 {"code": "dob_required"}, no account.
  3. New user, age < 13 -> 400 under-13 message, no account.
  4. New user, age >= 13 -> account created, DOB persisted, JWT returned.
"""
from datetime import date, timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialLogin, SocialToken
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.test import RequestFactory, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from jokes.models import UserProfile

User = get_user_model()

GOOGLE_UID = 'google-uid-0001'


@override_settings(
    SOCIALACCOUNT_ADAPTER='JokesForProject.adapters.SocialAccountAdapter',
    ACCOUNT_EMAIL_VERIFICATION='none',
)
class GoogleAgeGateTests(APITestCase):
    url = '/api/v1/auth/google/'

    @classmethod
    def setUpTestData(cls):
        cls.app = SocialApp.objects.create(
            provider='google', name='Google', client_id='cid', secret='secret',
        )
        cls.app.sites.add(Site.objects.get_current())

    def _sociallogin(self, email, uid=GOOGLE_UID):
        """Build the (unsaved) SocialLogin that GoogleOAuth2Adapter.complete_login
        would return after fetching identity from Google. lookup() runs against
        the DB inside pre_social_login, so an existing SocialAccount with `uid`
        makes this resolve to the linked user. `provider` must be set — allauth's
        email lookup reads login.provider.app."""
        user = User(email=email, username=email)
        account = SocialAccount(provider='google', uid=uid, extra_data={'email': email})
        sl = SocialLogin(
            user=user,
            account=account,
            email_addresses=[EmailAddress(email=email, verified=True, primary=True)],
        )
        sl.provider = self.app.get_provider(RequestFactory().get('/'))
        return sl

    def _post(self, sociallogin, body):
        """POST to the Google endpoint with token exchange + identity mocked."""
        with patch.object(OAuth2Client, 'get_access_token',
                          return_value={'access_token': 'mock-access-token'}), \
             patch.object(GoogleOAuth2Adapter, 'parse_token',
                          return_value=SocialToken(token='mock-access-token')), \
             patch.object(GoogleOAuth2Adapter, 'complete_login',
                          return_value=sociallogin):
            return self.client.post(self.url, body, format='json')

    # -- Case 1: existing linked user, no DOB -> logs in, DOB untouched --------
    def test_existing_linked_user_logs_in_without_dob(self):
        """REGRESSION GUARD: real returning Google users sign in with no
        date_of_birth and must not be prompted or blocked."""
        existing = User.objects.create_user(
            username='returning@example.com', email='returning@example.com',
        )
        # Their profile DOB was set at their original signup; must stay put.
        existing_dob = date(1990, 5, 20)
        UserProfile.objects.filter(user=existing).update(date_of_birth=existing_dob)
        SocialAccount.objects.create(user=existing, provider='google', uid=GOOGLE_UID)

        before = User.objects.count()
        resp = self._post(self._sociallogin('returning@example.com'), {'code': 'auth-code'})

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertIn('user', resp.data)
        self.assertEqual(User.objects.count(), before)  # no new account
        existing.profile.refresh_from_db()
        self.assertEqual(existing.profile.date_of_birth, existing_dob)  # untouched

    # -- Case 2: new user, no DOB -> dob_required, no account ------------------
    def test_new_user_without_dob_is_rejected_and_creates_nothing(self):
        resp = self._post(self._sociallogin('newbie@example.com'), {'code': 'auth-code'})

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertEqual(resp.data.get('code'), 'dob_required')
        self.assertFalse(User.objects.filter(email='newbie@example.com').exists())
        self.assertEqual(SocialAccount.objects.filter(uid=GOOGLE_UID).count(), 0)

    # -- Case 3: new user, under 13 -> same under-13 contract, no account ------
    def test_new_user_under_13_is_rejected_and_creates_nothing(self):
        five_years_old = (timezone.now().date() - timedelta(days=5 * 365)).isoformat()
        resp = self._post(
            self._sociallogin('kid@example.com'),
            {'code': 'auth-code', 'date_of_birth': five_years_old},
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertIn('at least 13 years old', str(resp.data))
        self.assertFalse(User.objects.filter(email='kid@example.com').exists())
        self.assertEqual(SocialAccount.objects.filter(uid=GOOGLE_UID).count(), 0)

    # -- Case 4: new user, 13+ -> account created, DOB persisted, JWT ----------
    def test_new_user_over_13_is_created_with_dob(self):
        dob = date(2000, 1, 1)
        resp = self._post(
            self._sociallogin('adult@example.com'),
            {'code': 'auth-code', 'date_of_birth': dob.isoformat()},
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertIn('user', resp.data)
        user = User.objects.get(email='adult@example.com')
        self.assertTrue(user.is_active)
        self.assertEqual(user.profile.date_of_birth, dob)  # same place email path stores it
        self.assertTrue(SocialAccount.objects.filter(user=user, uid=GOOGLE_UID).exists())

    # -- Guard: malformed DOB is rejected, no account -------------------------
    def test_new_user_malformed_dob_is_rejected(self):
        resp = self._post(
            self._sociallogin('bad@example.com'),
            {'code': 'auth-code', 'date_of_birth': 'not-a-date'},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertFalse(User.objects.filter(email='bad@example.com').exists())
