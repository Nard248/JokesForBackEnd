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

    def test_patch_draft_revalidates(self):
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt_oneliner, age_rating=self.age,
            language=self.lang, text='A.', status='draft',
        )
        resp = self.client.patch(
            f'/api/v1/jokes/my-drafts/{sub.id}/',
            {'format': 'knock', 'text': ''},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('lines', resp.json())

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
