"""Regression tests for the launch-blocker batch (fix/launch-blockers-batch1).

Covers:
  Fix 1 — content_tier is derived from age_rating at publish (COPPA gating).
  Fix 2 — password-reset emails an absolute frontend link (no NoReverseMatch).
  Fix 4 — password change requires the current password (CSRF mitigation).

Draft-vs-submit validation (Fix 3) is covered in jokes/tests.py.
"""
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APITestCase

from jokes.admin import JokeSubmissionAdmin
from jokes.models import AgeRating, Format, Joke, JokeSubmission, Language
from jokes.serving import BASE_TIERS

User = get_user_model()


def _admin_request(user):
    request = RequestFactory().post('/admin/')
    request.user = user
    setattr(request, 'session', {})
    setattr(request, '_messages', FallbackStorage(request))
    return request


class ContentTierAtPublishTests(TestCase):
    """Fix 1: adult/mature submissions must publish as the mature tier, not
    tier_1, so the COPPA age gate (serving.allowed_tiers keys on content_tier)
    keeps them away from minors and anonymous viewers."""

    @classmethod
    def setUpTestData(cls):
        cls.creator = User.objects.create_user(
            username='pub-creator', email='pub@example.com', password='pw',
        )
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.lang = Language.objects.get(code='en')
        cls.staff = User.objects.create_superuser(
            username='mod', email='mod@example.com', password='pw',
        )

    def _publish(self, age_slug):
        sub = JokeSubmission.objects.create(
            user=self.creator,
            format=self.fmt,
            age_rating=AgeRating.objects.get(slug=age_slug),
            language=self.lang,
            text='An edgy one-liner.',
            status='pending',
        )
        admin = JokeSubmissionAdmin(JokeSubmission, AdminSite())
        # Share-card PNG generation needs libcairo (not present in CI/local);
        # it's irrelevant to tier derivation, so stub it out.
        with patch('jokes.models.Joke._generate_share_image'):
            admin.approve_and_publish(
                _admin_request(self.staff),
                JokeSubmission.objects.filter(pk=sub.pk),
            )
        sub.refresh_from_db()
        return sub.published_joke

    def test_adult_publishes_as_mature_tier_and_is_age_gated(self):
        joke = self._publish('adult')
        self.assertIsNotNone(joke)
        self.assertEqual(joke.content_tier, 'tier_2')
        # Excluded from the minor/anon allowed tiers.
        self.assertNotIn(joke.content_tier, BASE_TIERS)
        self.assertFalse(
            Joke.objects.filter(pk=joke.pk, content_tier__in=BASE_TIERS).exists()
        )

    def test_mature_publishes_as_mature_tier(self):
        joke = self._publish('mature')
        self.assertEqual(joke.content_tier, 'tier_2')

    def test_teen_publishes_as_tier_1(self):
        joke = self._publish('teen')
        self.assertEqual(joke.content_tier, 'tier_1')
        self.assertIn(joke.content_tier, BASE_TIERS)

    def test_kid_safe_publishes_as_tier_1(self):
        joke = self._publish('kid-safe')
        self.assertEqual(joke.content_tier, 'tier_1')


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    FRONTEND_URL='https://jokesforfront.web.app',
)
class PasswordResetEmailTests(APITestCase):
    """Fix 2: the reset endpoint must render an email with an absolute link to
    the frontend /reset-password route (uid+token), with no NoReverseMatch."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='reset-me', email='reset@example.com', password='pw',
        )
        EmailAddress.objects.create(
            user=self.user, email=self.user.email, primary=True, verified=True,
        )

    def test_reset_renders_frontend_link(self):
        resp = self.client.post(
            '/api/v1/auth/password/reset/',
            {'email': 'reset@example.com'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn('https://jokesforfront.web.app/reset-password?uid=', body)
        self.assertIn('&token=', body)
        # The default reverse('password_reset_confirm') path must NOT appear.
        self.assertNotIn('/password/reset/confirm', body)


class OldPasswordRequiredTests(APITestCase):
    """Fix 4: password change must require the current password."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='changer', email='changer@example.com', password='OldPass123!x',
        )
        self.client.force_authenticate(user=self.user)

    def test_change_without_old_password_rejected(self):
        resp = self.client.post(
            '/api/v1/auth/password/change/',
            {'new_password1': 'BrandNew456!z', 'new_password2': 'BrandNew456!z'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('old_password', resp.json())

    def test_change_with_old_password_succeeds(self):
        resp = self.client.post(
            '/api/v1/auth/password/change/',
            {
                'old_password': 'OldPass123!x',
                'new_password1': 'BrandNew456!z',
                'new_password2': 'BrandNew456!z',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BrandNew456!z'))
