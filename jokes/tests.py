from django.test import SimpleTestCase

from jokes.submission_rules import FORMAT_RULES, validate_per_format


class FormatRulesTests(SimpleTestCase):
    def test_all_six_format_slugs_present(self):
        self.assertEqual(
            set(FORMAT_RULES.keys()),
            {'oneliner', 'setup', 'knock', 'story', 'anti', 'observ'},
        )

    # oneliner
    def test_oneliner_valid(self):
        self.assertEqual(validate_per_format('oneliner', {'text': 'A short joke.'}), {})

    def test_oneliner_missing_text(self):
        errs = validate_per_format('oneliner', {'text': ''})
        self.assertIn('text', errs)

    def test_oneliner_rejects_setup(self):
        errs = validate_per_format('oneliner', {'text': 'A.', 'setup': 'B.'})
        self.assertIn('setup', errs)

    # setup-punchline
    def test_setup_valid(self):
        self.assertEqual(
            validate_per_format('setup', {'setup': 'Why?', 'punchline': 'Because.'}),
            {},
        )

    def test_setup_missing_punchline(self):
        errs = validate_per_format('setup', {'setup': 'Why?', 'punchline': ''})
        self.assertIn('punchline', errs)

    def test_setup_rejects_lines(self):
        errs = validate_per_format(
            'setup', {'setup': 'A.', 'punchline': 'B.', 'lines': ['x', 'y']}
        )
        self.assertIn('lines', errs)

    # knock
    def test_knock_valid(self):
        self.assertEqual(
            validate_per_format(
                'knock',
                {'lines': ['Knock, knock.', "Who's there?", 'Olive.', 'Olive who?']},
            ),
            {},
        )

    def test_knock_too_few_lines(self):
        errs = validate_per_format('knock', {'lines': ['A.', 'B.']})
        self.assertIn('lines', errs)

    def test_knock_too_many_lines(self):
        errs = validate_per_format('knock', {'lines': ['x'] * 9})
        self.assertIn('lines', errs)

    def test_knock_line_too_long(self):
        errs = validate_per_format(
            'knock', {'lines': ['A.', 'B.', 'C.', 'x' * 201]}
        )
        self.assertIn('lines', errs)

    def test_knock_lines_not_a_list(self):
        errs = validate_per_format('knock', {'lines': 'not a list'})
        self.assertIn('lines', errs)

    def test_knock_empty_line_rejected(self):
        errs = validate_per_format(
            'knock', {'lines': ['A.', '', 'C.', 'D.']}
        )
        self.assertIn('lines', errs)

    def test_knock_rejects_text(self):
        errs = validate_per_format(
            'knock',
            {'lines': ['A.', 'B.', 'C.', 'D.'], 'text': 'oops'},
        )
        self.assertIn('text', errs)

    # story
    def test_story_valid(self):
        long_text = ' '.join(['word'] * 35)
        self.assertEqual(validate_per_format('story', {'text': long_text}), {})

    def test_story_too_short(self):
        errs = validate_per_format('story', {'text': 'Too short.'})
        self.assertIn('text', errs)

    # anti
    def test_anti_valid(self):
        self.assertEqual(
            validate_per_format('anti', {'setup': 'A.', 'punchline': 'B.'}),
            {},
        )

    def test_anti_missing_setup(self):
        errs = validate_per_format('anti', {'setup': '', 'punchline': 'B.'})
        self.assertIn('setup', errs)

    # observational
    def test_observ_valid(self):
        self.assertEqual(
            validate_per_format('observ', {'text': 'Have you ever noticed...'}),
            {},
        )

    def test_observ_missing_text(self):
        errs = validate_per_format('observ', {'text': ''})
        self.assertIn('text', errs)

    # unknown
    def test_unknown_format_slug(self):
        errs = validate_per_format('bogus', {'text': 'x'})
        self.assertIn('format', errs)


import io
import json
import zipfile
from datetime import date, timedelta

from django.utils import timezone
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from jokes.models import (
    Format, AgeRating, Language, Tone, ContextTag, CultureTag, JokeSubmission,
)

User = get_user_model()


class SubmissionApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='creator', email='creator@example.com', password='pw',
        )
        cls.fmt_oneliner = Format.objects.get(slug='oneliner')
        cls.fmt_setup = Format.objects.get(slug='setup')
        cls.fmt_knock = Format.objects.get(slug='knock')
        cls.fmt_story = Format.objects.get(slug='story')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')
        cls.culture, _ = CultureTag.objects.get_or_create(
            slug='test-culture', defaults={'name': 'Test Culture'},
        )

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def _payload(self, **overrides):
        base = {
            'format': 'oneliner',
            'age_rating': self.age.slug,
            'language': self.lang.code,
            'text': 'I told my wife she was drawing her eyebrows too high. She looked surprised.',
            'source': 'original',
        }
        base.update(overrides)
        return base

    def test_oneliner_valid_creates_pending(self):
        resp = self.client.post('/api/v1/jokes/submit/', self._payload(), format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        sub = JokeSubmission.objects.get(id=resp.json()['id'])
        self.assertEqual(sub.status, 'pending')
        self.assertEqual(sub.format.slug, 'oneliner')

    def test_oneliner_missing_text_rejected(self):
        resp = self.client.post(
            '/api/v1/jokes/submit/', self._payload(text=''), format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('text', resp.json())

    def test_setup_punchline_valid(self):
        resp = self.client.post(
            '/api/v1/jokes/submit/',
            self._payload(format='setup', text='', setup='Why?', punchline='Because.'),
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_setup_missing_punchline_rejected(self):
        resp = self.client.post(
            '/api/v1/jokes/submit/',
            self._payload(format='setup', text='', setup='Why?', punchline=''),
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('punchline', resp.json())

    def test_knock_with_lines_valid(self):
        resp = self.client.post(
            '/api/v1/jokes/submit/',
            self._payload(
                format='knock',
                text='',
                lines=['Knock, knock.', "Who's there?", 'Olive.', 'Olive who?'],
            ),
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        sub = JokeSubmission.objects.get(id=resp.json()['id'])
        self.assertEqual(len(sub.lines), 4)

    def test_knock_without_lines_rejected(self):
        resp = self.client.post(
            '/api/v1/jokes/submit/',
            self._payload(format='knock', text=''),
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('lines', resp.json())

    def test_knock_with_text_rejected(self):
        resp = self.client.post(
            '/api/v1/jokes/submit/',
            self._payload(
                format='knock',
                text='oops',
                lines=['A.', 'B.', 'C.', 'D.'],
            ),
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('text', resp.json())

    def test_story_too_short_rejected(self):
        resp = self.client.post(
            '/api/v1/jokes/submit/',
            self._payload(format='story', text='Just a few words.'),
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('text', resp.json())

    def test_culture_tags_accepted_and_stored(self):
        resp = self.client.post(
            '/api/v1/jokes/submit/',
            self._payload(culture_tags=[self.culture.slug]),
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        sub = JokeSubmission.objects.get(id=resp.json()['id'])
        self.assertEqual(
            list(sub.culture_tags.values_list('slug', flat=True)),
            [self.culture.slug],
        )

    def test_patch_draft_skips_format_validation(self):
        """Draft autosave must persist incomplete state (200), not 400 and lose
        the creator's typed text. Format validation is deferred to submit."""
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt_knock, age_rating=self.age,
            language=self.lang, status='draft',
        )
        # Knock requires `lines`; this partial autosave has none yet.
        resp = self.client.patch(
            f'/api/v1/jokes/my-drafts/{sub.id}/',
            {'setup': 'Work in progress...'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        sub.refresh_from_db()
        self.assertEqual(sub.setup, 'Work in progress...')
        self.assertEqual(sub.status, 'draft')

    def test_submit_incomplete_draft_rejected(self):
        """Submitting an incomplete draft must 400 with per-format errors so it
        can't reach moderation."""
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt_knock, age_rating=self.age,
            language=self.lang, status='draft',
        )
        resp = self.client.post(f'/api/v1/jokes/my-drafts/{sub.id}/submit/')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('lines', resp.json())
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'draft')

    def test_submit_complete_draft_pending(self):
        """A complete draft submits successfully and flips to pending."""
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt_knock, age_rating=self.age,
            language=self.lang, status='draft',
            lines=['Knock, knock.', "Who's there?", 'Olive.', 'Olive who?'],
        )
        resp = self.client.post(f'/api/v1/jokes/my-drafts/{sub.id}/submit/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['status'], 'pending')
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'pending')

    def test_patch_format_falls_back_to_instance(self):
        """A PATCH with no `format` key should reuse the instance's format."""
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt_oneliner, age_rating=self.age,
            language=self.lang, text='A short joke.', status='draft',
        )
        resp = self.client.patch(
            f'/api/v1/jokes/my-drafts/{sub.id}/',
            {'text': 'An updated one-liner.'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        sub.refresh_from_db()
        self.assertEqual(sub.text, 'An updated one-liner.')

    def test_setup_punchline_text_backfilled(self):
        """For setup/punchline formats, text is auto-derived from setup+punchline
        so previews, search, and downstream Joke.text are non-empty."""
        resp = self.client.post(
            '/api/v1/jokes/submit/',
            self._payload(format='setup', text='', setup='Why?', punchline='Because.'),
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        sub = JokeSubmission.objects.get(id=resp.json()['id'])
        self.assertEqual(sub.text, 'Why? Because.')

    def test_knock_text_backfilled_from_lines(self):
        resp = self.client.post(
            '/api/v1/jokes/submit/',
            self._payload(
                format='knock', text='',
                lines=['Knock, knock.', "Who's there?", 'Olive.', 'Olive who?'],
            ),
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        sub = JokeSubmission.objects.get(id=resp.json()['id'])
        self.assertIn('Olive who?', sub.text)

    def test_drafts_list_includes_lines_and_culture_tags(self):
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt_knock, age_rating=self.age,
            language=self.lang, lines=['A.', 'B.', 'C.', 'D.'], status='draft',
        )
        sub.culture_tags.add(self.culture)
        resp = self.client.get(f'/api/v1/jokes/my-drafts/{sub.id}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['lines'], ['A.', 'B.', 'C.', 'D.'])
        self.assertEqual(body['culture_tags'], [self.culture.slug])


class DraftCreateApiTests(APITestCase):
    """POST /api/v1/jokes/my-drafts/ — minimal draft creation (no full validation)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='draftcreator', email='draftcreator@example.com', password='pw',
        )

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def test_post_creates_draft_for_user(self):
        resp = self.client.post(
            '/api/v1/jokes/my-drafts/', {'format': 'oneliner'}, format='json'
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        # Returns the list/GET shape so the frontend fromDTO works.
        self.assertEqual(body['status'], 'draft')
        self.assertEqual(body['format'], 'oneliner')
        self.assertIn('id', body)
        sub = JokeSubmission.objects.get(id=body['id'])
        self.assertEqual(sub.user, self.user)
        self.assertEqual(sub.status, 'draft')
        self.assertEqual(sub.format.slug, 'oneliner')
        # Non-null FKs are backfilled with defaults.
        self.assertIsNotNone(sub.age_rating)
        self.assertIsNotNone(sub.language)

    def test_created_draft_appears_in_users_list(self):
        create = self.client.post(
            '/api/v1/jokes/my-drafts/', {'format': 'oneliner'}, format='json'
        )
        draft_id = create.json()['id']
        listing = self.client.get('/api/v1/jokes/my-drafts/')
        self.assertEqual(listing.status_code, 200)
        results = listing.json()
        rows = results['results'] if isinstance(results, dict) else results
        self.assertIn(draft_id, [r['id'] for r in rows])

    def test_post_unauthenticated_401(self):
        self.client.force_authenticate(user=None)
        resp = self.client.post(
            '/api/v1/jokes/my-drafts/', {'format': 'oneliner'}, format='json'
        )
        self.assertEqual(resp.status_code, 401)

    def test_post_missing_format_400(self):
        resp = self.client.post('/api/v1/jokes/my-drafts/', {}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('format', resp.json())

    def test_post_unknown_format_400(self):
        resp = self.client.post(
            '/api/v1/jokes/my-drafts/', {'format': 'nope-not-real'}, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('format', resp.json())


class FormatSchemaApiTests(APITestCase):
    def test_formats_endpoint_exposes_per_format_schema(self):
        resp = self.client.get('/api/v1/formats/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        rows = body.get('results', body)  # paginated or not
        by_slug = {row['slug']: row for row in rows}

        knock = by_slug['knock']
        self.assertEqual(knock['required_fields'], ['lines'])
        self.assertIn('text', knock['forbidden_fields'])
        self.assertEqual(knock['constraints']['min_lines'], 4)
        self.assertEqual(knock['constraints']['max_lines'], 8)

        oneliner = by_slug['oneliner']
        self.assertEqual(oneliner['required_fields'], ['text'])
        self.assertIn('setup', oneliner['forbidden_fields'])
        self.assertEqual(oneliner.get('constraints', {}), {})

        story = by_slug['story']
        self.assertEqual(story['constraints']['min_text_words'], 30)


from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from jokes.admin import JokeSubmissionAdmin
from jokes.models import Joke


class AdminApproveTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='creator2', email='c2@example.com', password='pw',
        )
        cls.staff = User.objects.create_user(
            username='mod', email='mod@example.com', password='pw',
            is_staff=True, is_superuser=True,
        )
        cls.fmt = Format.objects.get(slug='knock')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')
        cls.tone = Tone.objects.first()
        cls.theme = ContextTag.objects.first()
        cls.culture, _ = CultureTag.objects.get_or_create(
            slug='test-culture-admin', defaults={'name': 'Test Culture Admin'},
        )

    def _make_pending_knock(self):
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt, age_rating=self.age, language=self.lang,
            source='original',
            lines=['Knock, knock.', "Who's there?", 'Olive.', 'Olive who?'],
            text="Knock, knock. Who's there? Olive. Olive who?",
            status='pending',
        )
        sub.tones.add(self.tone)
        sub.context_tags.add(self.theme)
        sub.culture_tags.add(self.culture)
        return sub

    def _admin_request(self):
        req = RequestFactory().post('/admin/')
        req.user = self.staff
        # Silence Django messages framework — it requires the messages middleware
        # to be set up, which isn't available in this lightweight admin invocation.
        req._messages = type('M', (), {'add': lambda *a, **kw: None})()
        return req

    @patch('jokes.models.Joke._generate_share_image')
    def test_approve_action_publishes_and_creates_joke(self, _mock_img):
        sub = self._make_pending_knock()
        admin_instance = JokeSubmissionAdmin(JokeSubmission, AdminSite())
        admin_instance.approve_and_publish(
            self._admin_request(), JokeSubmission.objects.filter(id=sub.id)
        )

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'published')
        self.assertIsNotNone(sub.published_joke_id)

        joke = sub.published_joke
        self.assertEqual(joke.format.slug, 'knock')
        self.assertEqual(joke.lines, sub.lines)
        self.assertIn(self.tone, joke.tones.all())
        self.assertIn(self.theme, joke.context_tags.all())
        self.assertIn(self.culture, joke.culture_tags.all())

    @patch('jokes.models.Joke._generate_share_image')
    def test_approve_skips_drafts(self, _mock_img):
        sub = self._make_pending_knock()
        sub.status = 'draft'
        sub.save(update_fields=['status'])

        admin_instance = JokeSubmissionAdmin(JokeSubmission, AdminSite())
        admin_instance.approve_and_publish(
            self._admin_request(), JokeSubmission.objects.filter(id=sub.id)
        )

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'draft')
        self.assertIsNone(sub.published_joke_id)


# =============================================================================
# GDPR: DataExportView tests  (Task 1)
# =============================================================================

from jokes.models import (
    Joke, Collection, SavedJoke, Favorite, JokeRating, JokeReaction,
    DailyJoke, JokeView, Streak, StreakDay, JokeSubmission as _JS,
    ContentReport, UserBlock, UserPreference, UserProfile, UserVibe, Vibe,
    MysteryBoxRoll, ShareEvent, Achievement, UserAchievement,
    JokePack, JokePackProgress,
)
from notifications.models import EmailMessageLog, EmailVerification


class DataExportTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='exporter@example.com',
            email='exporter@example.com',
            password='pw12345!',
        )
        cls.other = User.objects.create_user(
            username='other@example.com',
            email='other@example.com',
            password='pw12345!',
        )
        fmt = Format.objects.get(slug='oneliner')
        age = AgeRating.objects.first()
        lang = Language.objects.get(code='en')
        with patch('jokes.models.Joke._generate_share_image'):
            cls.joke = Joke.objects.create(
                text='My export joke', format=fmt, age_rating=age, language=lang,
            )
        col = Collection.objects.create(user=cls.user, name='Mine')
        SavedJoke.objects.create(user=cls.user, joke=cls.joke, collection=col, note='keep')
        Favorite.objects.create(user=cls.user, joke=cls.joke)
        JokeRating.objects.create(user=cls.user, joke=cls.joke, rating=JokeRating.LIKE)
        JokeReaction.objects.create(user=cls.user, joke=cls.joke, reaction=JokeReaction.REACTION_LOL)
        DailyJoke.objects.create(user=cls.user, joke=cls.joke, date=date.today())
        JokeView.objects.create(user=cls.user, joke=cls.joke, source=JokeView.SOURCE_DAILY)
        EmailMessageLog.objects.create(
            user=cls.user, to_email=cls.user.email,
            template_name='welcome', subject='Hi', status='sent',
        )
        ContentReport.objects.create(reporter=cls.user, joke=cls.joke, reason='spam')
        UserBlock.objects.create(blocker=cls.user, blocked=cls.other)
        # Other user's data — must NOT appear in user_a's export
        Favorite.objects.create(user=cls.other, joke=cls.joke)
        EmailMessageLog.objects.create(
            user=cls.other, to_email=cls.other.email,
            template_name='welcome', subject='Hi', status='sent',
        )

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def _export(self):
        resp = self.client.get('/api/v1/users/me/data-export/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp['Content-Type'], 'application/zip')
        self.assertIn('attachment', resp['Content-Disposition'])
        raw = resp.content
        zf = zipfile.ZipFile(io.BytesIO(raw))
        return json.loads(zf.read(zf.namelist()[0]))

    def test_export_headers_and_zip(self):
        resp = self.client.get('/api/v1/users/me/data-export/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/zip')
        self.assertIn('attachment', resp['Content-Disposition'])
        self.assertIn('.zip', resp['Content-Disposition'])

    def test_export_contains_all_sections(self):
        data = self._export()
        expected_sections = [
            'export_meta', 'account', 'profile', 'preferences',
            'collections', 'saved_jokes', 'favorites', 'ratings', 'reactions',
            'daily_jokes', 'streak', 'streak_days', 'views', 'submissions',
            'reports_filed', 'blocks', 'achievements', 'vibes', 'pack_progress',
            'mystery_rolls', 'share_events', 'email_logs',
        ]
        for key in expected_sections:
            self.assertIn(key, data, f'Missing export section: {key}')
        # Sections seeded for user_a must be non-empty
        self.assertTrue(len(data['collections']) > 0)
        self.assertTrue(len(data['saved_jokes']) > 0)
        self.assertTrue(len(data['favorites']) > 0)
        self.assertTrue(len(data['ratings']) > 0)
        self.assertTrue(len(data['reactions']) > 0)
        self.assertTrue(len(data['daily_jokes']) > 0)
        self.assertTrue(len(data['views']) > 0)
        self.assertTrue(len(data['email_logs']) > 0)
        self.assertTrue(len(data['reports_filed']) > 0)
        self.assertTrue(len(data['blocks']) > 0)

    def test_export_excludes_other_users_data(self):
        data = self._export()
        # Only 1 favorite (user_a's), not other's
        self.assertEqual(len(data['favorites']), 1)
        # Only user_a's email log, not other's
        self.assertEqual(len(data['email_logs']), 1)
        # Blocks store blocked_id only — never other's email
        self.assertNotIn('other@example.com', json.dumps(data))
        # The block row should reference other.id as blocked_id
        self.assertEqual(data['blocks'][0]['blocked_id'], self.other.id)

    def test_export_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get('/api/v1/users/me/data-export/')
        self.assertIn(resp.status_code, [401, 403])


# =============================================================================
# GDPR: AccountDeleteView tests  (Task 3)
# =============================================================================

from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken


class AccountDeleteTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        fmt = Format.objects.get(slug='oneliner')
        age = AgeRating.objects.first()
        lang = Language.objects.get(code='en')
        with patch('jokes.models.Joke._generate_share_image'):
            cls.joke = Joke.objects.create(
                text='Delete test joke', format=fmt, age_rating=age, language=lang,
            )

    def _make_pw_user(self):
        u = User.objects.create_user(
            username='del@example.com', email='del@example.com', password='pw12345!',
        )
        EmailMessageLog.objects.create(
            user=u, to_email=u.email, template_name='welcome', subject='Hi', status='sent',
        )
        EmailVerification.objects.create(
            user=u, code_hash='xhash', expires_at=timezone.now() + timedelta(minutes=10),
        )
        SavedJoke.objects.create(user=u, joke=self.joke)
        return u

    def _make_oauth_user(self):
        u = User.objects.create_user(
            username='g@example.com', email='g@example.com',
        )
        u.set_unusable_password()
        u.save()
        EmailMessageLog.objects.create(
            user=u, to_email=u.email, template_name='welcome', subject='Hi', status='sent',
        )
        EmailVerification.objects.create(
            user=u, code_hash='xhash2', expires_at=timezone.now() + timedelta(minutes=10),
        )
        return u

    def test_delete_missing_password(self):
        u = self._make_pw_user()
        self.client.force_authenticate(user=u)
        resp = self.client.delete('/api/v1/users/me/', {}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('password', resp.json())
        self.assertTrue(User.objects.filter(pk=u.pk).exists())

    def test_delete_wrong_password(self):
        u = self._make_pw_user()
        self.client.force_authenticate(user=u)
        resp = self.client.delete('/api/v1/users/me/', {'password': 'nope'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('password', resp.json())
        self.assertTrue(User.objects.filter(pk=u.pk).exists())

    def test_delete_correct_password_removes_user_and_cascades(self):
        u = self._make_pw_user()
        u_pk = u.pk
        u_email = u.email
        self.client.force_authenticate(user=u)
        resp = self.client.delete('/api/v1/users/me/', {'password': 'pw12345!'}, format='json')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(User.objects.filter(pk=u_pk).exists())
        # Email logs and verifications must be explicitly purged (SET_NULL doesn't auto-delete)
        self.assertFalse(
            EmailMessageLog.objects.filter(to_email__iexact=u_email).exists()
        )
        self.assertFalse(
            EmailVerification.objects.filter(user_id=u_pk).exists()
        )

    def test_oauth_requires_confirm(self):
        u = self._make_oauth_user()
        u_pk = u.pk
        self.client.force_authenticate(user=u)
        # Missing confirm
        resp = self.client.delete('/api/v1/users/me/', {}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('confirm', resp.json())
        # Wrong confirm value
        resp = self.client.delete('/api/v1/users/me/', {'confirm': 'nope'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('confirm', resp.json())
        # Correct confirm
        resp = self.client.delete('/api/v1/users/me/', {'confirm': 'DELETE'}, format='json')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(User.objects.filter(pk=u_pk).exists())

    def test_delete_blacklists_refresh_token(self):
        u = self._make_pw_user()
        u_pk = u.pk
        # Mint a real refresh token so OutstandingToken row is created
        refresh = RefreshToken.for_user(u)
        jti = refresh['jti']
        self.client.force_authenticate(user=u)
        resp = self.client.delete('/api/v1/users/me/', {'password': 'pw12345!'}, format='json')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(User.objects.filter(pk=u_pk).exists())
        # The outstanding token should now be blacklisted
        ot = OutstandingToken.objects.filter(jti=jti).first()
        self.assertIsNotNone(ot, 'OutstandingToken row should still exist (SET_NULL)')
        self.assertTrue(
            BlacklistedToken.objects.filter(token=ot).exists(),
            'Refresh token should be blacklisted after account deletion',
        )
