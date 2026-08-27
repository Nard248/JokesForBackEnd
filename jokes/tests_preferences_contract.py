"""The preferences contract that onboarding depends on.

The 3-step onboarding flow (/flow) sends vibes, formats and a daily ritual.
Only the vibes were ever persisted: PATCH /users/me/preferences/ handled four
keys and silently dropped the rest, while `humor_types` -- sent by the SPA as
FORMAT slugs -- was matched against Tone, resolved to nothing, and WIPED the
user's tone preferences. `get_personalized_joke` reads exactly those tones, so
completing onboarding actively degraded personalization and `onboarding_completed`
never flipped.
"""
from datetime import time

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from jokes.models import Tone, UserPreference, Vibe

User = get_user_model()


class PreferencesUpdateContractTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='prefs@example.com', email='prefs@example.com', password='pw',
        )
        self.client.force_authenticate(user=self.user)
        self.pref, _ = UserPreference.objects.get_or_create(user=self.user)
        self.tones = list(Tone.objects.all()[:3])
        assert self.tones, 'taxonomy seed required'
        self.pref.preferred_tones.set(self.tones)

    def _patch(self, payload):
        return self.client.patch('/api/v1/users/me/preferences/', payload, format='json')

    def test_unresolvable_humor_types_do_not_wipe_existing_tones(self):
        """Slugs that match no Tone must be rejected, never silently applied.

        Onboarding sends format slugs here; the old code ran
        Tone.objects.filter(slug__in=[...]) -> empty -> .set([]) and erased the
        user's real preferences with a 200 OK.
        """
        resp = self._patch({'humor_types': ['oneliner', 'setup']})  # format slugs

        self.assertEqual(resp.status_code, 400, resp.content)
        self.pref.refresh_from_db()
        self.assertEqual(
            self.pref.preferred_tones.count(), 3,
            'existing tone preferences must survive a rejected update',
        )

    def test_valid_humor_types_still_replace_tones(self):
        keep = self.tones[0].slug
        resp = self._patch({'humor_types': [keep]})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            list(self.pref.preferred_tones.values_list('slug', flat=True)), [keep],
        )

    def test_empty_humor_types_clears_deliberately(self):
        resp = self._patch({'humor_types': []})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.pref.preferred_tones.count(), 0)

    def test_ritual_fields_persist(self):
        """The whole of onboarding step 3 used to evaporate with a 200 OK."""
        resp = self._patch({
            'notification_enabled': True,
            'notification_time': '21:00',
            'notification_days': ['mon', 'sat'],
            'streak_saver_enabled': False,
        })
        self.assertEqual(resp.status_code, 200, resp.content)

        self.pref.refresh_from_db()
        self.assertTrue(self.pref.notification_enabled)
        self.assertEqual(self.pref.notification_time, time(21, 0))
        self.assertEqual(self.pref.notification_days, ['mon', 'sat'])
        self.assertFalse(self.pref.streak_saver_enabled)

    def test_onboarding_completed_persists(self):
        resp = self._patch({'onboarding_completed': True})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.pref.refresh_from_db()
        self.assertTrue(self.pref.onboarding_completed)

    def test_get_reflects_the_persisted_ritual(self):
        self._patch({
            'notification_enabled': True,
            'notification_time': '07:30',
            'notification_days': ['tue'],
            'onboarding_completed': True,
        })
        body = self.client.get('/api/v1/users/me/preferences/').json()
        self.assertTrue(body['onboarding_completed'])
        self.assertEqual(body['notification_time'], '07:30:00')
        self.assertEqual(body['notification_days'], ['tue'])
        self.assertTrue(body['notification_enabled'])

    def test_a_non_object_body_is_a_400_not_a_500(self):
        """A malformed body must never be a server error on an authed endpoint.

        `set(request.data)` over a JSON ARRAY raises
        TypeError: unhashable type: 'dict', which DRF turns into a 500 and
        Sentry into a page. Scanners send exactly this.
        """
        resp = self.client.patch(
            '/api/v1/users/me/preferences/', [{'theme': 'dark'}], format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_unknown_keys_are_rejected_rather_than_ignored(self):
        """A silent 200 is how the original contract drift went unnoticed."""
        resp = self._patch({'totally_made_up_field': 'x'})
        self.assertEqual(resp.status_code, 400, resp.content)


class VibeSelectionDrivesPersonalizationTests(APITestCase):
    """Choosing vibes must change what the reader is served.

    Onboarding's only durable effect was a UserVibe row -- and nothing read it:
    `UserVibe` appears in its own CRUD view, the admin and serializers, and
    nowhere in any serving path. Meanwhile `get_personalized_joke` filters on
    `preferred_tones` / `preferred_contexts`, which onboarding left empty (and
    actively wiped). So the vibes screen promised "we'll tune your daily joke
    around these" and tuned nothing.

    A Vibe is already a filter recipe over Format/Theme/Category, so selecting
    vibes can project straight onto the axes personalization reads.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='vibes@example.com', email='vibes@example.com', password='pw',
        )
        self.client.force_authenticate(user=self.user)
        self.vibes = list(
            Vibe.objects.filter(is_active=True)
            .prefetch_related('categories', 'themes')[:3]
        )
        assert len(self.vibes) == 3, 'vibe seed required'

    def test_saving_vibes_populates_the_axes_personalization_reads(self):
        slugs = [v.slug for v in self.vibes]
        expected_tones = {t.slug for v in self.vibes for t in v.categories.all()}
        expected_themes = {c.slug for v in self.vibes for c in v.themes.all()}
        self.assertTrue(expected_tones or expected_themes, 'seeded vibes carry axes')

        resp = self.client.put(
            '/api/v1/users/me/vibes/', {'slugs': slugs}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        pref = UserPreference.objects.get(user=self.user)
        self.assertEqual(
            set(pref.preferred_tones.values_list('slug', flat=True)), expected_tones,
        )
        self.assertEqual(
            set(pref.preferred_contexts.values_list('slug', flat=True)), expected_themes,
        )

    def test_replacing_the_selection_replaces_the_derived_axes(self):
        """A later selection must not leave the earlier one's axes behind.

        (The endpoint requires 3-12 slugs, so both selections are triples.)
        """
        later = list(
            Vibe.objects.filter(is_active=True)
            .exclude(slug__in=[v.slug for v in self.vibes])
            .prefetch_related('categories', 'themes')[:3]
        )
        self.assertEqual(len(later), 3, 'need a second disjoint triple of vibes')

        self.client.put(
            '/api/v1/users/me/vibes/',
            {'slugs': [v.slug for v in self.vibes]}, format='json',
        )
        resp = self.client.put(
            '/api/v1/users/me/vibes/',
            {'slugs': [v.slug for v in later]}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        pref = UserPreference.objects.get(user=self.user)
        self.assertEqual(
            set(pref.preferred_tones.values_list('slug', flat=True)),
            {t.slug for v in later for t in v.categories.all()},
        )
