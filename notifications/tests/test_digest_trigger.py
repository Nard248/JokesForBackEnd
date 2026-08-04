"""Email-Digest-Wave Task 3: token-authed internal run-digests trigger.

Unauthenticated internal endpoint -- security-critical. Guarded only by the
X-Digest-Token header compared (constant-time) to settings.DIGEST_CRON_TOKEN.
Any failure mode (missing header, wrong token, unset/empty server secret)
must return 404 -- never 401/403 -- so the endpoint's existence is never
advertised to anyone probing it (see spec §Risks).
"""
import inspect
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from freezegun import freeze_time

from audit.models import AuditLog
from jokes.models import AgeRating, DailyJoke, Format, Joke, Language
from notifications import views as notifications_views
from notifications.models import EmailMessageLog

User = get_user_model()

TOKEN = 'test-cron-secret-token'
TODAY = '2026-08-04T15:00:00Z'


def _taxonomy():
    fmt, _ = Format.objects.get_or_create(slug='setup', defaults={'name': 'Setup/Punchline'})
    age, _ = AgeRating.objects.get_or_create(slug='all-ages', defaults={'name': 'All Ages'})
    lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
    return fmt, age, lang


class RunDigestsViewSecurityTests(TestCase):
    """The 404-on-any-failure guard is the whole security model here --
    this class is deliberately paranoid about every failure path."""

    def setUp(self):
        self.url = reverse('run-digests')

    @override_settings(DIGEST_CRON_TOKEN=TOKEN)
    def test_missing_token_header_returns_404(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 404)

    @override_settings(DIGEST_CRON_TOKEN=TOKEN)
    def test_wrong_token_returns_404_and_runs_nothing(self):
        with patch('notifications.views.run_daily_digests') as mock_run:
            response = self.client.post(self.url, HTTP_X_DIGEST_TOKEN='not-the-secret')

        self.assertEqual(response.status_code, 404)
        mock_run.assert_not_called()
        self.assertEqual(EmailMessageLog.objects.count(), 0)

    @override_settings(DIGEST_CRON_TOKEN='')
    def test_unset_token_setting_404s_even_with_a_supplied_token(self):
        # Dormant: an empty/unset DIGEST_CRON_TOKEN must reject EVERY caller,
        # including one that (perhaps accidentally) sends an empty header too.
        response = self.client.post(self.url, HTTP_X_DIGEST_TOKEN='anything')
        self.assertEqual(response.status_code, 404)

        response_empty_header = self.client.post(self.url, HTTP_X_DIGEST_TOKEN='')
        self.assertEqual(response_empty_header.status_code, 404)

    @override_settings(DIGEST_CRON_TOKEN=TOKEN)
    def test_correct_token_returns_200_with_summary_dict(self):
        summary = {'digests_sent': 3, 'milestones_sent': 1, 'skipped': False, 'remaining': 0}
        with patch('notifications.views.run_daily_digests', return_value=summary) as mock_run:
            response = self.client.post(self.url, HTTP_X_DIGEST_TOKEN=TOKEN)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), summary)
        mock_run.assert_called_once()

    @override_settings(DIGEST_CRON_TOKEN=TOKEN, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_correct_token_actually_sends_eligible_digests(self):
        fmt, age, lang = _taxonomy()
        with patch('jokes.models.Joke._generate_share_image'):
            joke = Joke.objects.create(
                text='', setup='Setup', punchline='Punchline', format=fmt,
                age_rating=age, language=lang, content_tier='tier_1',
            )
        with freeze_time(TODAY):
            today = '2026-08-04'
            seed = User.objects.create_user(
                username='seed@example.com', email='seed@example.com', password='pw',
            )
            DailyJoke.objects.create(user=seed, joke=joke, date=today)
            User.objects.create_user(
                username='reader@example.com', email='reader@example.com', password='pw',
            )

            response = self.client.post(self.url, HTTP_X_DIGEST_TOKEN=TOKEN)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['digests_sent'], 2)
        recipients = {m.to[0] for m in mail.outbox}
        self.assertIn('reader@example.com', recipients)
        self.assertIn('seed@example.com', recipients)

    @override_settings(DIGEST_CRON_TOKEN=TOKEN)
    def test_successful_run_writes_an_audit_row(self):
        summary = {'digests_sent': 0, 'milestones_sent': 0, 'skipped': True, 'remaining': 0}
        with patch('notifications.views.run_daily_digests', return_value=summary):
            self.client.post(self.url, HTTP_X_DIGEST_TOKEN=TOKEN)

        entry = AuditLog.objects.filter(action='digest_run').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.outcome, 'success')
        self.assertIsNone(entry.actor)

    @override_settings(DIGEST_CRON_TOKEN=TOKEN)
    def test_wrong_token_writes_no_audit_row(self):
        with patch('notifications.views.run_daily_digests'):
            self.client.post(self.url, HTTP_X_DIGEST_TOKEN='not-the-secret')

        self.assertFalse(AuditLog.objects.filter(action='digest_run').exists())


class RunDigestsViewConstantTimeCompareTests(TestCase):
    """Structural pin: the timing-safety property itself can't be reliably
    asserted via a test (network/CI jitter swamps microsecond differences),
    so this pins the implementation detail that makes it true -- the view
    must use hmac.compare_digest, never a plain `==` string comparison."""

    def test_view_source_uses_hmac_compare_digest(self):
        source = inspect.getsource(notifications_views)
        self.assertIn('hmac.compare_digest', source)
