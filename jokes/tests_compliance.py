"""
Compliance tests for Wave 1B: COPPA age gate + content_tier serving lock.

Test classes:
  UserProfileAgeHelperTests  — DOB/age/is_adult/is_minor helpers + show_mature default
  RegistrationAgeGateTests   — Under-13 block, boundary, missing DOB, future DOB
  AllowedTiersResolverTests  — allowed_tiers() resolver matrix
  ServingLockTests           — per-endpoint tier exclusion proofs
"""
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase, APIRequestFactory

from jokes.models import (
    Joke, Format, AgeRating, Language, UserProfile, UserPreference,
)
from jokes.serving import allowed_tiers

User = get_user_model()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _years_ago(years):
    """Return a date exactly `years` years before today (same month/day)."""
    today = timezone.now().date()
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        # Feb 29 in a non-leap year → use Feb 28
        return today.replace(year=today.year - years, day=28)


# ---------------------------------------------------------------------------
# Task 1: UserProfile age helpers + UserPreference.show_mature default
# ---------------------------------------------------------------------------

class UserProfileAgeHelperTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='age_test@example.com',
            email='age_test@example.com',
            password='testpass123',
        )
        self.profile = self.user.profile  # auto-created by signal

    def _set_dob(self, years):
        self.profile.date_of_birth = _years_ago(years)
        self.profile.save(update_fields=['date_of_birth'])

    def test_age_12_is_minor_not_adult(self):
        self._set_dob(12)
        self.assertEqual(self.profile.age, 12)
        self.assertTrue(self.profile.is_minor)
        self.assertFalse(self.profile.is_adult)

    def test_age_13_is_minor_not_adult(self):
        self._set_dob(13)
        self.assertEqual(self.profile.age, 13)
        self.assertTrue(self.profile.is_minor)
        self.assertFalse(self.profile.is_adult)

    def test_age_17_is_minor_not_adult(self):
        self._set_dob(17)
        self.assertTrue(self.profile.is_minor)
        self.assertFalse(self.profile.is_adult)

    def test_age_18_is_adult_not_minor(self):
        self._set_dob(18)
        self.assertEqual(self.profile.age, 18)
        self.assertTrue(self.profile.is_adult)
        self.assertFalse(self.profile.is_minor)

    def test_age_25_is_adult_not_minor(self):
        self._set_dob(25)
        self.assertTrue(self.profile.is_adult)
        self.assertFalse(self.profile.is_minor)

    def test_null_dob_age_none_treated_as_minor(self):
        self.profile.date_of_birth = None
        self.profile.save(update_fields=['date_of_birth'])
        self.assertIsNone(self.profile.age)
        self.assertFalse(self.profile.is_adult)
        self.assertTrue(self.profile.is_minor)

    def test_show_mature_defaults_false(self):
        pref = self.user.preference  # auto-created by signal
        self.assertFalse(pref.show_mature)


# ---------------------------------------------------------------------------
# Task 2: Registration age gate
# ---------------------------------------------------------------------------

REG_URL = '/api/v1/auth/registration/'

UNDER_13_ERROR = 'You must be at least 13 years old to use Jokes For.'


@override_settings(EMAIL_VERIFICATION_REQUIRED=False)
class RegistrationAgeGateTests(APITestCase):

    def _dob(self, years):
        return _years_ago(years).isoformat()

    def _post(self, extra=None):
        payload = {
            'email': 'reg@example.com',
            'password1': 'Sup3rSecret!',
            'password2': 'Sup3rSecret!',
        }
        if extra:
            payload.update(extra)
        return self.client.post(REG_URL, payload, format='json')

    def test_under_13_blocked_with_exact_error(self):
        resp = self._post({'email': 'young@example.com', 'date_of_birth': self._dob(12)})
        self.assertEqual(resp.status_code, 400, resp.content)
        body = resp.json()
        self.assertIn('date_of_birth', body)
        self.assertIn(UNDER_13_ERROR, body['date_of_birth'])

    def test_exactly_13_succeeds_and_dob_stored(self):
        dob_str = self._dob(13)
        resp = self._post({'email': 'thirteen@example.com', 'date_of_birth': dob_str})
        self.assertEqual(resp.status_code, 201, resp.content)
        user = User.objects.get(email='thirteen@example.com')
        self.assertEqual(user.profile.date_of_birth.isoformat(), dob_str)

    def test_adult_20_succeeds_and_dob_stored(self):
        dob_str = self._dob(20)
        resp = self._post({'email': 'reg@example.com', 'date_of_birth': dob_str})
        self.assertEqual(resp.status_code, 201, resp.content)
        user = User.objects.get(email='reg@example.com')
        self.assertEqual(user.profile.date_of_birth.isoformat(), dob_str)

    def test_future_dob_rejected(self):
        future = (timezone.now().date().replace(year=timezone.now().year + 1)).isoformat()
        resp = self._post({'email': 'future@example.com', 'date_of_birth': future})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('date_of_birth', resp.json())

    def test_today_dob_rejected_as_invalid(self):
        today = timezone.now().date().isoformat()
        resp = self._post({'email': 'today@example.com', 'date_of_birth': today})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('date_of_birth', resp.json())

    def test_missing_dob_rejected(self):
        resp = self._post()  # no date_of_birth
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('date_of_birth', resp.json())

    def test_age_12_exact_error_value(self):
        """The response dict under date_of_birth key must be exactly the contract list."""
        resp = self._post({'email': 'kid@example.com', 'date_of_birth': self._dob(12)})
        self.assertEqual(resp.json()['date_of_birth'], [UNDER_13_ERROR])


# ---------------------------------------------------------------------------
# Task 3: allowed_tiers resolver matrix
# ---------------------------------------------------------------------------

class AllowedTiersResolverTests(TestCase):

    def setUp(self):
        self.factory = APIRequestFactory()

    def _make_user(self, dob_years=None, show_mature=False):
        import uuid
        uid = str(uuid.uuid4())[:8]
        u = User.objects.create_user(
            username=f'at_{uid}@example.com',
            email=f'at_{uid}@example.com',
            password='testpass',
        )
        if dob_years is not None:
            u.profile.date_of_birth = _years_ago(dob_years)
            u.profile.save(update_fields=['date_of_birth'])
        u.preference.show_mature = show_mature
        u.preference.save(update_fields=['show_mature'])
        return u

    def _request_for(self, user=None):
        req = self.factory.get('/')
        if user is None:
            from django.contrib.auth.models import AnonymousUser
            req.user = AnonymousUser()
        else:
            req.user = user
        return req

    def test_anonymous_gets_tier1_only(self):
        tiers = allowed_tiers(self._request_for())
        self.assertEqual(tiers, frozenset({'tier_1'}))
        self.assertNotIn('tier_2', tiers)
        self.assertNotIn('tier_3', tiers)

    def test_minor_gets_tier1_only(self):
        u = self._make_user(dob_years=15)
        tiers = allowed_tiers(self._request_for(u))
        self.assertEqual(tiers, frozenset({'tier_1'}))

    def test_null_dob_user_gets_tier1_only(self):
        u = self._make_user(dob_years=None)  # null DOB
        tiers = allowed_tiers(self._request_for(u))
        self.assertEqual(tiers, frozenset({'tier_1'}))

    def test_adult_no_optin_gets_tier1_only(self):
        u = self._make_user(dob_years=25, show_mature=False)
        tiers = allowed_tiers(self._request_for(u))
        self.assertEqual(tiers, frozenset({'tier_1'}))

    def test_adult_with_optin_gets_tier1_and_tier2(self):
        u = self._make_user(dob_years=25, show_mature=True)
        tiers = allowed_tiers(self._request_for(u))
        self.assertEqual(tiers, frozenset({'tier_1', 'tier_2'}))

    def test_tier3_never_in_any_result(self):
        for dob, mature in [(None, False), (15, False), (25, False), (25, True)]:
            u = self._make_user(dob_years=dob, show_mature=mature)
            tiers = allowed_tiers(self._request_for(u))
            self.assertNotIn('tier_3', tiers, f"tier_3 leaked for dob={dob} mature={mature}")

    def test_missing_profile_fails_safe_to_tier1(self):
        """If profile is deleted, resolver must not raise and must return {tier_1}."""
        u = self._make_user(dob_years=25, show_mature=True)
        u.profile.delete()
        req = self._request_for(u)
        # Refresh user (profile is gone)
        req.user = User.objects.get(pk=u.pk)
        tiers = allowed_tiers(req)
        self.assertEqual(tiers, frozenset({'tier_1'}))

    def test_missing_preference_fails_safe_to_tier1(self):
        """If preference is deleted, resolver must return {tier_1}."""
        u = self._make_user(dob_years=25, show_mature=True)
        u.preference.delete()
        req = self._request_for(u)
        req.user = User.objects.get(pk=u.pk)
        tiers = allowed_tiers(req)
        self.assertEqual(tiers, frozenset({'tier_1'}))


# ---------------------------------------------------------------------------
# Task 4: ServingLockTests — per-endpoint tier exclusion
# ---------------------------------------------------------------------------

def _make_joke(fmt, age_rating, lang, content_tier, text_seed):
    """Create a Joke with the given content_tier and a unique searchable text."""
    return Joke.objects.create(
        text=f'A {text_seed} joke that is uniquely {text_seed}able',
        format=fmt,
        age_rating=age_rating,
        language=lang,
        source=None,
        content_tier=content_tier,
    )


class ServingLockTests(APITestCase):
    """
    Verifies that every joke read path respects the content_tier serving lock.

    tier_1  — always allowed (for everyone)
    tier_2  — only for adults with show_mature=True
    tier_3  — NEVER served to anyone via the API
    """

    @classmethod
    def setUpTestData(cls):
        fmt = Format.objects.first()
        age_rating = AgeRating.objects.first()
        lang = Language.objects.filter(code='en').first() or Language.objects.first()

        if fmt is None or age_rating is None or lang is None:
            raise AssertionError(
                "Seed data missing (Format/AgeRating/Language). "
                "Run migrations with --keepdb."
            )

        # Patch out PNG generation (no PIL in test env)
        with patch.object(Joke, '_generate_share_image', return_value=None):
            cls.joke_t1 = _make_joke(fmt, age_rating, lang, 'tier_1', 'servinglock')
            cls.joke_t2 = _make_joke(fmt, age_rating, lang, 'tier_2', 'servinglock')
            cls.joke_t3 = _make_joke(fmt, age_rating, lang, 'tier_3', 'servinglock')

        # Users
        cls.minor = User.objects.create_user(
            username='minor_sl@example.com', email='minor_sl@example.com', password='pw',
        )
        cls.minor.profile.date_of_birth = _years_ago(15)
        cls.minor.profile.save(update_fields=['date_of_birth'])

        cls.adult_noopt = User.objects.create_user(
            username='adult_no@example.com', email='adult_no@example.com', password='pw',
        )
        cls.adult_noopt.profile.date_of_birth = _years_ago(25)
        cls.adult_noopt.profile.save(update_fields=['date_of_birth'])
        # show_mature=False is default

        cls.adult_opt = User.objects.create_user(
            username='adult_opt@example.com', email='adult_opt@example.com', password='pw',
        )
        cls.adult_opt.profile.date_of_birth = _years_ago(25)
        cls.adult_opt.profile.save(update_fields=['date_of_birth'])
        cls.adult_opt.preference.show_mature = True
        cls.adult_opt.preference.save(update_fields=['show_mature'])

    def _ids_from_paginated(self, resp):
        data = resp.json()
        if 'results' in data:
            return {j['id'] for j in data['results']}
        if isinstance(data, list):
            return {j['id'] for j in data}
        return set()

    # -- LIST endpoint --

    def test_list_anon_excludes_tier2_tier3(self):
        resp = self.client.get('/api/v1/jokes/')
        self.assertEqual(resp.status_code, 200)
        ids = self._ids_from_paginated(resp)
        self.assertIn(self.joke_t1.id, ids)
        self.assertNotIn(self.joke_t2.id, ids)
        self.assertNotIn(self.joke_t3.id, ids)

    def test_list_minor_excludes_tier2_tier3(self):
        self.client.force_authenticate(user=self.minor)
        resp = self.client.get('/api/v1/jokes/')
        self.assertEqual(resp.status_code, 200)
        ids = self._ids_from_paginated(resp)
        self.assertNotIn(self.joke_t2.id, ids)
        self.assertNotIn(self.joke_t3.id, ids)
        self.client.force_authenticate(user=None)

    def test_list_adult_noopt_excludes_tier2_tier3(self):
        self.client.force_authenticate(user=self.adult_noopt)
        resp = self.client.get('/api/v1/jokes/')
        ids = self._ids_from_paginated(resp)
        self.assertNotIn(self.joke_t2.id, ids)
        self.assertNotIn(self.joke_t3.id, ids)
        self.client.force_authenticate(user=None)

    def test_list_adult_opt_includes_tier2_excludes_tier3(self):
        self.client.force_authenticate(user=self.adult_opt)
        resp = self.client.get('/api/v1/jokes/')
        ids = self._ids_from_paginated(resp)
        self.assertIn(self.joke_t2.id, ids)
        self.assertNotIn(self.joke_t3.id, ids)
        self.client.force_authenticate(user=None)

    # -- SEARCH endpoint --

    def test_search_anon_excludes_tier2_tier3(self):
        resp = self.client.get('/api/v1/jokes/?q=servinglock')
        self.assertEqual(resp.status_code, 200)
        ids = self._ids_from_paginated(resp)
        self.assertNotIn(self.joke_t2.id, ids)
        self.assertNotIn(self.joke_t3.id, ids)

    def test_search_adult_opt_includes_tier2_excludes_tier3(self):
        self.client.force_authenticate(user=self.adult_opt)
        resp = self.client.get('/api/v1/jokes/?q=servinglock')
        ids = self._ids_from_paginated(resp)
        self.assertIn(self.joke_t2.id, ids)
        self.assertNotIn(self.joke_t3.id, ids)
        self.client.force_authenticate(user=None)

    # -- RANDOM endpoint --

    def test_random_anon_never_tier2_or_tier3(self):
        """Hit random 20 times; tier_2/tier_3 must never appear."""
        for _ in range(20):
            resp = self.client.get('/api/v1/jokes/random/')
            if resp.status_code == 404:
                continue
            tier = resp.json().get('content_tier', 'tier_1')
            self.assertIn(tier, ('tier_1',), f"random served {tier} to anon")

    def test_random_minor_never_tier2_or_tier3(self):
        self.client.force_authenticate(user=self.minor)
        for _ in range(20):
            resp = self.client.get('/api/v1/jokes/random/')
            if resp.status_code == 404:
                continue
            tier = resp.json().get('content_tier', 'tier_1')
            self.assertIn(tier, ('tier_1',), f"random served {tier} to minor")
        self.client.force_authenticate(user=None)

    def test_random_adult_opt_never_tier3(self):
        self.client.force_authenticate(user=self.adult_opt)
        for _ in range(20):
            resp = self.client.get('/api/v1/jokes/random/')
            if resp.status_code == 404:
                continue
            tier = resp.json().get('content_tier', 'tier_1')
            self.assertNotIn(tier, ('tier_3',), f"random served tier_3 to adult_opt")
        self.client.force_authenticate(user=None)

    # -- TRENDING endpoint --

    def test_trending_never_tier3(self):
        """Trending never leaks tier_3 (may return empty if no engagement)."""
        for user in (None, self.minor, self.adult_opt):
            if user:
                self.client.force_authenticate(user=user)
            else:
                self.client.force_authenticate(user=None)
            resp = self.client.get('/api/v1/jokes/trending/')
            self.assertEqual(resp.status_code, 200)
            results = resp.json().get('results', [])
            for item in results:
                joke_data = item.get('joke', item)
                tier = joke_data.get('content_tier', 'tier_1')
                self.assertNotIn(tier, ('tier_3',), "tier_3 leaked in trending")
        self.client.force_authenticate(user=None)

    # -- DAILY TODAY endpoint --

    def test_daily_today_anon_only_tier1(self):
        """Anonymous daily joke must always be tier_1."""
        for _ in range(5):
            resp = self.client.get('/api/v1/daily-jokes/today/')
            if resp.status_code != 200:
                continue
            data = resp.json()
            joke_data = data.get('joke', {})
            tier = joke_data.get('content_tier', 'tier_1')
            self.assertEqual(tier, 'tier_1', f"anon daily served {tier}")

    def test_daily_today_minor_only_tier1(self):
        self.client.force_authenticate(user=self.minor)
        resp = self.client.get('/api/v1/daily-jokes/today/')
        if resp.status_code == 200:
            joke_data = resp.json().get('joke', {})
            tier = joke_data.get('content_tier', 'tier_1')
            self.assertEqual(tier, 'tier_1', f"minor daily served {tier}")
        self.client.force_authenticate(user=None)

    def test_daily_today_adult_opt_never_tier3(self):
        self.client.force_authenticate(user=self.adult_opt)
        resp = self.client.get('/api/v1/daily-jokes/today/')
        if resp.status_code == 200:
            joke_data = resp.json().get('joke', {})
            tier = joke_data.get('content_tier', 'tier_1')
            self.assertNotIn(tier, ('tier_3',), "daily served tier_3 to adult_opt")
        self.client.force_authenticate(user=None)

    # -- MYSTERY BOX endpoint --

    def test_mystery_box_minor_never_tier2_tier3(self):
        self.client.force_authenticate(user=self.minor)
        for _ in range(5):
            resp = self.client.post('/api/v1/mystery-box/roll/')
            if resp.status_code in (404, 429):
                continue
            self.assertEqual(resp.status_code, 200)
            tier = resp.json().get('joke', {}).get('content_tier', 'tier_1')
            self.assertIn(tier, ('tier_1',), f"mystery box served {tier} to minor")
        self.client.force_authenticate(user=None)

    def test_mystery_box_adult_opt_never_tier3(self):
        self.client.force_authenticate(user=self.adult_opt)
        for _ in range(5):
            resp = self.client.post('/api/v1/mystery-box/roll/')
            if resp.status_code in (404, 429):
                continue
            self.assertEqual(resp.status_code, 200)
            tier = resp.json().get('joke', {}).get('content_tier', 'tier_1')
            self.assertNotIn(tier, ('tier_3',), f"mystery box served tier_3 to adult_opt")
        self.client.force_authenticate(user=None)

    # -- tier_3 never served to anyone --

    def test_tier3_never_returned_from_list_to_anyone(self):
        for user in (None, self.minor, self.adult_noopt, self.adult_opt):
            if user:
                self.client.force_authenticate(user=user)
            else:
                self.client.force_authenticate(user=None)
            resp = self.client.get('/api/v1/jokes/')
            ids = self._ids_from_paginated(resp)
            self.assertNotIn(
                self.joke_t3.id, ids,
                f"tier_3 joke appeared in list for user={getattr(user, 'email', 'anon')}"
            )
        self.client.force_authenticate(user=None)
