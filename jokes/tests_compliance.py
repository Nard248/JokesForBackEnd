"""
Compliance tests for Wave 1B: COPPA age gate + content_tier serving lock.

Test classes:
  UserProfileAgeHelperTests  — DOB/age/is_adult/is_minor helpers + show_mature default
  RegistrationAgeGateTests   — Under-13 block, boundary, missing DOB, future DOB
  AllowedTiersResolverTests  — allowed_tiers() resolver matrix
  ServingLockTests           — per-endpoint tier exclusion proofs
"""
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, APITestCase

from jokes.models import (
    AgeRating,
    Collection,
    Favorite,
    Format,
    Joke,
    JokePack,
    JokePackEntry,
    JokeView,
    Language,
    SavedJoke,
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

def _make_joke(fmt, age_rating, lang, content_tier, text_seed, setup='', punchline=''):
    """Create a Joke with the given content_tier and a unique searchable text."""
    return Joke.objects.create(
        text=f'A {text_seed} joke that is uniquely {text_seed}able',
        setup=setup,
        punchline=punchline,
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
            # tier_2 joke carries a real setup/punchline so the share-page
            # redirect tests can assert those exact strings never leak into
            # the gated response body.
            cls.joke_t2 = _make_joke(
                fmt, age_rating, lang, 'tier_2', 'servinglock',
                setup='Why did the mature servinglock joke cross the road?',
                punchline='To reach the tier_2 punchline on the other side.',
            )
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
        """Anon random must never return the tier_2 or tier_3 joke IDs."""
        forbidden = {self.joke_t2.id, self.joke_t3.id}
        for _ in range(20):
            resp = self.client.get('/api/v1/jokes/random/')
            if resp.status_code == 404:
                continue
            joke_id = resp.json().get('id')
            self.assertNotIn(joke_id, forbidden, f"random served forbidden joke id={joke_id} to anon")

    def test_random_minor_never_tier2_or_tier3(self):
        self.client.force_authenticate(user=self.minor)
        forbidden = {self.joke_t2.id, self.joke_t3.id}
        for _ in range(20):
            resp = self.client.get('/api/v1/jokes/random/')
            if resp.status_code == 404:
                continue
            joke_id = resp.json().get('id')
            self.assertNotIn(joke_id, forbidden, f"random served forbidden joke id={joke_id} to minor")
        self.client.force_authenticate(user=None)

    def test_random_adult_opt_never_tier3(self):
        self.client.force_authenticate(user=self.adult_opt)
        forbidden = {self.joke_t3.id}
        for _ in range(20):
            resp = self.client.get('/api/v1/jokes/random/')
            if resp.status_code == 404:
                continue
            joke_id = resp.json().get('id')
            self.assertNotIn(joke_id, forbidden, f"random served tier_3 joke id={joke_id} to adult_opt")
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
                joke_id = joke_data.get('id')
                self.assertNotEqual(joke_id, self.joke_t3.id, "tier_3 joke leaked in trending")
        self.client.force_authenticate(user=None)

    # -- DAILY TODAY endpoint --

    def test_daily_today_anon_only_tier1(self):
        """Anonymous daily joke must always be tier_1 (i.e., not tier_2 or tier_3 joke IDs)."""
        forbidden = {self.joke_t2.id, self.joke_t3.id}
        for _ in range(5):
            resp = self.client.get('/api/v1/daily-jokes/today/')
            if resp.status_code != 200:
                continue
            joke_id = resp.json().get('joke', {}).get('id')
            self.assertNotIn(joke_id, forbidden, f"anon daily served forbidden joke id={joke_id}")

    def test_daily_today_minor_only_tier1(self):
        forbidden = {self.joke_t2.id, self.joke_t3.id}
        self.client.force_authenticate(user=self.minor)
        resp = self.client.get('/api/v1/daily-jokes/today/')
        if resp.status_code == 200:
            # For authenticated path, resp has 'joke' nested under the DailyJoke serializer
            joke_data = resp.json().get('joke', {})
            joke_id = joke_data.get('id')
            self.assertNotIn(joke_id, forbidden, f"minor daily served forbidden joke id={joke_id}")
        self.client.force_authenticate(user=None)

    def test_daily_today_adult_opt_never_tier3(self):
        forbidden = {self.joke_t3.id}
        self.client.force_authenticate(user=self.adult_opt)
        resp = self.client.get('/api/v1/daily-jokes/today/')
        if resp.status_code == 200:
            joke_data = resp.json().get('joke', {})
            joke_id = joke_data.get('id')
            self.assertNotIn(joke_id, forbidden, f"daily served tier_3 joke id={joke_id} to adult_opt")
        self.client.force_authenticate(user=None)

    # -- MYSTERY BOX endpoint --

    def test_mystery_box_minor_never_tier2_tier3(self):
        forbidden = {self.joke_t2.id, self.joke_t3.id}
        self.client.force_authenticate(user=self.minor)
        for _ in range(5):
            resp = self.client.post('/api/v1/mystery-box/roll/')
            if resp.status_code in (404, 429):
                continue
            self.assertEqual(resp.status_code, 200)
            joke_id = resp.json().get('joke', {}).get('id')
            self.assertNotIn(joke_id, forbidden, f"mystery box served forbidden joke id={joke_id} to minor")
        self.client.force_authenticate(user=None)

    def test_mystery_box_adult_opt_never_tier3(self):
        forbidden = {self.joke_t3.id}
        self.client.force_authenticate(user=self.adult_opt)
        for _ in range(5):
            resp = self.client.post('/api/v1/mystery-box/roll/')
            if resp.status_code in (404, 429):
                continue
            self.assertEqual(resp.status_code, 200)
            joke_id = resp.json().get('joke', {}).get('id')
            self.assertNotIn(joke_id, forbidden, f"mystery box served tier_3 joke id={joke_id} to adult_opt")
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

    # -- RETRIEVE endpoint (surface 5: explicit test) --

    def test_retrieve_minor_tier2_returns_404(self):
        """GET /api/v1/jokes/<tier2_id>/ as a minor must return 404."""
        self.client.force_authenticate(user=self.minor)
        resp = self.client.get(f'/api/v1/jokes/{self.joke_t2.id}/')
        self.assertEqual(resp.status_code, 404, "minor must get 404 for tier_2 joke retrieve")
        self.client.force_authenticate(user=None)

    def test_retrieve_anon_tier2_returns_404(self):
        """GET /api/v1/jokes/<tier2_id>/ as anon must return 404."""
        resp = self.client.get(f'/api/v1/jokes/{self.joke_t2.id}/')
        self.assertEqual(resp.status_code, 404, "anon must get 404 for tier_2 joke retrieve")

    def test_retrieve_adult_opt_tier2_returns_200(self):
        """GET /api/v1/jokes/<tier2_id>/ as opted-in adult must return 200."""
        self.client.force_authenticate(user=self.adult_opt)
        resp = self.client.get(f'/api/v1/jokes/{self.joke_t2.id}/')
        self.assertEqual(resp.status_code, 200, "opted-in adult must get 200 for tier_2 joke retrieve")
        self.client.force_authenticate(user=None)

    # -- SHARE PAGE (surface 1) --
    #
    # A tier-gated share page no longer 404s -- a 404 here was a dead-link
    # regression: scrapers got no preview and human recipients got a raw
    # backend 404 instead of being bounced to the SPA's own age-gate. It now
    # 200s with a minimal, content-free redirect shell (share_redirect.html)
    # that sends the human on to the frontend while exposing NONE of the
    # joke's mature content (no text/setup/punchline, no og:image, no
    # JSON-LD) to the anon/scraper eyes that can't see it. This preserves
    # the compliance intent -- no mature content served to anon/minors --
    # while fixing the dead-link UX. The `full preview 200` behavior for an
    # allowed (opted-in adult) requester is unchanged and covered below.

    def _assert_gated_redirect_shell(self, resp, joke):
        """Shared assertions for a tier-gated share-page response: 200,
        redirects to the frontend joke URL, and leaks none of the joke's
        mature content."""
        self.assertEqual(resp.status_code, 200, "gated share page must 200 with a redirect shell, not 404")
        body = resp.content.decode('utf-8')

        expected_target = f"{settings.FRONTEND_URL.rstrip('/')}/jokes/{joke.id}"
        self.assertIn(expected_target, body, "redirect shell must point at the frontend joke URL")

        # None of the joke's actual content may appear in the response.
        self.assertNotIn(joke.text, body, "joke text leaked into gated share page")
        self.assertNotIn(joke.setup, body, "joke setup leaked into gated share page")
        self.assertNotIn(joke.punchline, body, "joke punchline leaked into gated share page")
        if joke.share_image:
            self.assertNotIn(joke.share_image.name, body, "share_image leaked into gated share page")
        # Check actual tag markup (not a bare substring match) since the
        # template's own explanatory comment mentions "og:image" by name.
        self.assertNotIn('property="og:image"', body, "og:image tag must not appear on the gated share page")
        self.assertNotIn('name="twitter:image"', body, "twitter:image tag must not appear on the gated share page")
        self.assertNotIn('application/ld+json', body, "JSON-LD must not appear on the gated share page")
        return body

    def test_share_page_anon_tier2_returns_gated_redirect_no_content_leak(self):
        """GET /jokes/<tier2_id>/share/ as anon must NOT 404 (dead link) and
        must NOT leak any of the joke's mature content."""
        resp = self.client.get(f'/jokes/{self.joke_t2.id}/share/')
        self._assert_gated_redirect_shell(resp, self.joke_t2)

    def test_share_page_minor_tier2_returns_gated_redirect_no_content_leak(self):
        """GET /jokes/<tier2_id>/share/ as minor must NOT 404 (dead link) and
        must NOT leak any of the joke's mature content.

        Uses force_login (session auth), not force_authenticate: this is a
        plain Django view (not a DRF view), so force_authenticate -- which
        only patches the DRF Request object -- has no effect on it and would
        silently leave the request looking anonymous.
        """
        self.client.force_login(self.minor)
        resp = self.client.get(f'/jokes/{self.joke_t2.id}/share/')
        self._assert_gated_redirect_shell(resp, self.joke_t2)
        self.client.logout()

    def test_share_page_adult_opt_tier2_returns_200(self):
        """GET /jokes/<tier2_id>/share/ as opted-in adult must return 200.

        The share page is a plain Django view (not DRF), so session-based
        force_login is required — force_authenticate only affects DRF views.
        """
        self.client.force_login(self.adult_opt)
        resp = self.client.get(f'/jokes/{self.joke_t2.id}/share/')
        self.assertEqual(resp.status_code, 200, "opted-in adult must get 200 for tier_2 share page")
        self.client.logout()

    def test_share_page_tier1_always_accessible(self):
        """GET /jokes/<tier1_id>/share/ must work for everyone (anon)."""
        resp = self.client.get(f'/jokes/{self.joke_t1.id}/share/')
        self.assertEqual(resp.status_code, 200, "tier_1 share page must be accessible to everyone")


# ---------------------------------------------------------------------------
# Extra surfaces: JokePack, Collection.jokes, Favorite
# ---------------------------------------------------------------------------

class JokePackTierFilterTests(APITestCase):
    """JokePackViewSet (AllowAny) must not embed tier_2 jokes for anon/minors."""

    @classmethod
    def setUpTestData(cls):
        fmt = Format.objects.first()
        age_rating = AgeRating.objects.first()
        lang = Language.objects.filter(code='en').first() or Language.objects.first()

        with patch.object(Joke, '_generate_share_image', return_value=None):
            cls.joke_t1 = _make_joke(fmt, age_rating, lang, 'tier_1', 'packtest')
            cls.joke_t2 = _make_joke(fmt, age_rating, lang, 'tier_2', 'packtest')

        cls.pack = JokePack.objects.create(
            slug='test-pack-compliance',
            title='Compliance Test Pack',
            is_published=True,
        )
        JokePackEntry.objects.create(pack=cls.pack, joke=cls.joke_t1, order=1)
        JokePackEntry.objects.create(pack=cls.pack, joke=cls.joke_t2, order=2)

        cls.minor = User.objects.create_user(
            username='pack_minor@example.com', email='pack_minor@example.com', password='pw',
        )
        cls.minor.profile.date_of_birth = _years_ago(15)
        cls.minor.profile.save(update_fields=['date_of_birth'])

        cls.adult_opt = User.objects.create_user(
            username='pack_adult@example.com', email='pack_adult@example.com', password='pw',
        )
        cls.adult_opt.profile.date_of_birth = _years_ago(25)
        cls.adult_opt.profile.save(update_fields=['date_of_birth'])
        cls.adult_opt.preference.show_mature = True
        cls.adult_opt.preference.save(update_fields=['show_mature'])

    def _joke_ids_in_pack(self, resp):
        data = resp.json()
        return {entry['joke']['id'] for entry in data.get('jokes', [])}

    def test_pack_detail_anon_excludes_tier2(self):
        """Anon must NOT see tier_2 jokes embedded in pack detail."""
        resp = self.client.get(f'/api/v1/packs/{self.pack.slug}/')
        self.assertEqual(resp.status_code, 200)
        ids = self._joke_ids_in_pack(resp)
        self.assertIn(self.joke_t1.id, ids)
        self.assertNotIn(self.joke_t2.id, ids, "anon must not see tier_2 joke in pack detail")

    def test_pack_detail_minor_excludes_tier2(self):
        """Minor must NOT see tier_2 jokes embedded in pack detail."""
        self.client.force_authenticate(user=self.minor)
        resp = self.client.get(f'/api/v1/packs/{self.pack.slug}/')
        self.assertEqual(resp.status_code, 200)
        ids = self._joke_ids_in_pack(resp)
        self.assertNotIn(self.joke_t2.id, ids, "minor must not see tier_2 joke in pack detail")
        self.client.force_authenticate(user=None)

    def test_pack_detail_adult_opt_includes_tier2(self):
        """Opted-in adult MUST see tier_2 jokes in pack detail."""
        self.client.force_authenticate(user=self.adult_opt)
        resp = self.client.get(f'/api/v1/packs/{self.pack.slug}/')
        self.assertEqual(resp.status_code, 200)
        ids = self._joke_ids_in_pack(resp)
        self.assertIn(self.joke_t2.id, ids, "opted-in adult must see tier_2 joke in pack detail")
        self.client.force_authenticate(user=None)


class CollectionJokesTierFilterTests(APITestCase):
    """CollectionViewSet.jokes must not expose re-tiered mature jokes."""

    @classmethod
    def setUpTestData(cls):
        fmt = Format.objects.first()
        age_rating = AgeRating.objects.first()
        lang = Language.objects.filter(code='en').first() or Language.objects.first()

        with patch.object(Joke, '_generate_share_image', return_value=None):
            cls.joke_t1 = _make_joke(fmt, age_rating, lang, 'tier_1', 'collectiontest')
            cls.joke_t2 = _make_joke(fmt, age_rating, lang, 'tier_2', 'collectiontest')

        cls.minor = User.objects.create_user(
            username='col_minor@example.com', email='col_minor@example.com', password='pw',
        )
        cls.minor.profile.date_of_birth = _years_ago(15)
        cls.minor.profile.save(update_fields=['date_of_birth'])

        # Give minor a collection that contains a tier_2 joke (simulates re-tiering scenario)
        cls.collection = Collection.objects.create(
            user=cls.minor, name='Minor Collection', is_default=True,
        )
        SavedJoke.objects.create(user=cls.minor, joke=cls.joke_t1, collection=cls.collection)
        SavedJoke.objects.create(user=cls.minor, joke=cls.joke_t2, collection=cls.collection)

    def _joke_ids(self, resp):
        data = resp.json()
        results = data.get('results', data) if isinstance(data, dict) else data
        return {item['joke']['id'] for item in (results if isinstance(results, list) else [])}

    def test_collection_jokes_minor_excludes_tier2(self):
        """Minor's collection jokes endpoint must not return tier_2 jokes."""
        self.client.force_authenticate(user=self.minor)
        resp = self.client.get(f'/api/v1/collections/{self.collection.id}/jokes/')
        self.assertEqual(resp.status_code, 200)
        ids = self._joke_ids(resp)
        self.assertIn(self.joke_t1.id, ids)
        self.assertNotIn(self.joke_t2.id, ids, "minor must not see tier_2 joke in collection")
        self.client.force_authenticate(user=None)


class FavoriteTierFilterTests(APITestCase):
    """FavoriteViewSet must not expose re-tiered mature jokes."""

    @classmethod
    def setUpTestData(cls):
        fmt = Format.objects.first()
        age_rating = AgeRating.objects.first()
        lang = Language.objects.filter(code='en').first() or Language.objects.first()

        with patch.object(Joke, '_generate_share_image', return_value=None):
            cls.joke_t1 = _make_joke(fmt, age_rating, lang, 'tier_1', 'favtest')
            cls.joke_t2 = _make_joke(fmt, age_rating, lang, 'tier_2', 'favtest')

        cls.minor = User.objects.create_user(
            username='fav_minor@example.com', email='fav_minor@example.com', password='pw',
        )
        cls.minor.profile.date_of_birth = _years_ago(15)
        cls.minor.profile.save(update_fields=['date_of_birth'])

        # Minor favorited a joke that later became tier_2 (re-tiering simulation)
        Favorite.objects.create(user=cls.minor, joke=cls.joke_t1)
        Favorite.objects.create(user=cls.minor, joke=cls.joke_t2)

    def _joke_ids(self, resp):
        data = resp.json()
        results = data.get('results', data) if isinstance(data, dict) else data
        return {item['joke']['id'] for item in (results if isinstance(results, list) else [])}

    def test_favorites_minor_excludes_tier2(self):
        """Minor's favorites endpoint must not return tier_2 jokes."""
        self.client.force_authenticate(user=self.minor)
        resp = self.client.get('/api/v1/favorites/')
        self.assertEqual(resp.status_code, 200)
        ids = self._joke_ids(resp)
        self.assertIn(self.joke_t1.id, ids)
        self.assertNotIn(self.joke_t2.id, ids, "minor must not see tier_2 joke in favorites")
        self.client.force_authenticate(user=None)


# ---------------------------------------------------------------------------
# Fix 1: user-details endpoint exposes date_of_birth
# ---------------------------------------------------------------------------

class UserDetailsDateOfBirthTests(APITestCase):
    """GET /api/v1/auth/user/ must include date_of_birth from the user's profile."""

    @classmethod
    def setUpTestData(cls):
        cls.user_with_dob = User.objects.create_user(
            username='dob_user@example.com',
            email='dob_user@example.com',
            password='pw',
        )
        cls.user_with_dob.profile.date_of_birth = _years_ago(25)
        cls.user_with_dob.profile.save(update_fields=['date_of_birth'])

        # OAuth/legacy user — profile exists but DOB is null
        cls.user_no_dob = User.objects.create_user(
            username='nodob_user@example.com',
            email='nodob_user@example.com',
            password='pw',
        )
        # profile.date_of_birth is null by default

    def test_user_details_includes_date_of_birth_when_set(self):
        """Authenticated user with a DOB sees it in the user-details response."""
        self.client.force_authenticate(user=self.user_with_dob)
        resp = self.client.get('/api/v1/auth/user/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('date_of_birth', data, "date_of_birth must be present in user-details response")
        expected = self.user_with_dob.profile.date_of_birth.isoformat()
        self.assertEqual(data['date_of_birth'], expected)

    def test_user_details_returns_null_dob_when_not_set(self):
        """Authenticated user with no DOB (OAuth/legacy) sees null for date_of_birth."""
        self.client.force_authenticate(user=self.user_no_dob)
        resp = self.client.get('/api/v1/auth/user/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('date_of_birth', data, "date_of_birth field must be present even when null")
        self.assertIsNone(data['date_of_birth'])


# ---------------------------------------------------------------------------
# Fix 2: recently-viewed endpoint respects tier lock
# ---------------------------------------------------------------------------

class RecentlyViewedTierFilterTests(APITestCase):
    """GET /api/v1/users/me/recently-viewed/ must respect the content_tier lock."""

    @classmethod
    def setUpTestData(cls):
        fmt = Format.objects.first()
        age_rating = AgeRating.objects.first()
        lang = Language.objects.filter(code='en').first() or Language.objects.first()

        with patch.object(Joke, '_generate_share_image', return_value=None):
            cls.joke_t1 = _make_joke(fmt, age_rating, lang, 'tier_1', 'recentview')
            cls.joke_t2 = _make_joke(fmt, age_rating, lang, 'tier_2', 'recentview')

        # User who was once opted-in (viewed tier_2 joke), then turned off show_mature
        cls.user = User.objects.create_user(
            username='rv_user@example.com',
            email='rv_user@example.com',
            password='pw',
        )
        cls.user.profile.date_of_birth = _years_ago(25)
        cls.user.profile.save(update_fields=['date_of_birth'])
        # show_mature is now False (default) — simulates user who opted back out

        # Seed view history directly (bypasses the view debounce/signal)
        JokeView.objects.create(user=cls.user, joke=cls.joke_t1)
        JokeView.objects.create(user=cls.user, joke=cls.joke_t2)

    def test_recently_viewed_excludes_tier2_when_not_opted_in(self):
        """User who turned off show_mature must NOT see tier_2 in their history."""
        self.client.force_authenticate(user=self.user)
        resp = self.client.get('/api/v1/users/me/recently-viewed/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        joke_ids = {entry['joke']['id'] for entry in data}
        self.assertIn(self.joke_t1.id, joke_ids, "tier_1 must still appear in recently-viewed")
        self.assertNotIn(self.joke_t2.id, joke_ids,
                         "tier_2 must NOT appear when show_mature=False")

    def test_recently_viewed_includes_tier2_when_opted_in(self):
        """Adult with show_mature=True DOES see tier_2 in their history."""
        self.user.preference.show_mature = True
        self.user.preference.save(update_fields=['show_mature'])
        try:
            self.client.force_authenticate(user=self.user)
            resp = self.client.get('/api/v1/users/me/recently-viewed/')
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            joke_ids = {entry['joke']['id'] for entry in data}
            self.assertIn(self.joke_t1.id, joke_ids)
            self.assertIn(self.joke_t2.id, joke_ids,
                          "opted-in adult must see tier_2 in recently-viewed")
        finally:
            self.user.preference.show_mature = False
            self.user.preference.save(update_fields=['show_mature'])
