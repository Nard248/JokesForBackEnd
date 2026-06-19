"""Tests for Joke.creator FK: nullable field, related_name, SET_NULL, publish stamp, backfill."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.contrib.messages.storage.fallback import FallbackStorage

from jokes.models import Format, AgeRating, Language, Joke, JokeSubmission

User = get_user_model()


def _make_joke(fmt, age, lang, text='Test', content_tier='tier_1', creator=None):
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text=text, format=fmt, age_rating=age, language=lang,
            content_tier=content_tier, creator=creator,
        )


class JokeCreatorFieldTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')
        cls.user = User.objects.create_user(
            username='fk_user@test.com', email='fk_user@test.com', password='x',
        )

    def test_creator_nullable(self):
        j = _make_joke(self.fmt, self.age, self.lang, text='No creator')
        self.assertIsNone(j.creator)

    def test_creator_set(self):
        j = _make_joke(self.fmt, self.age, self.lang, text='Has creator', creator=self.user)
        self.assertEqual(j.creator_id, self.user.pk)

    def test_related_name(self):
        j = _make_joke(self.fmt, self.age, self.lang, text='RN', creator=self.user)
        self.assertIn(j, self.user.created_jokes.all())

    def test_set_null_on_user_delete(self):
        temp = User.objects.create_user(username='del@t.com', email='del@t.com', password='x')
        j = _make_joke(self.fmt, self.age, self.lang, text='Del', creator=temp)
        temp.delete()
        j.refresh_from_db()
        self.assertIsNone(j.creator)
        self.assertTrue(Joke.objects.filter(pk=j.pk).exists())


class PublishStampsCreatorTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')
        cls.creator = User.objects.create_user(
            username='stamp@test.com', email='stamp@test.com', password='x',
        )

    def test_approve_and_publish_stamps_creator(self):
        from jokes.admin import JokeSubmissionAdmin
        from django.contrib.admin.sites import AdminSite

        sub = JokeSubmission.objects.create(
            user=self.creator, format=self.fmt, age_rating=self.age,
            language=self.lang, status='pending', text='Publishable joke',
        )
        admin_obj = JokeSubmissionAdmin(JokeSubmission, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.creator
        request.session = {}
        request._messages = FallbackStorage(request)
        with patch('jokes.models.Joke._generate_share_image'):
            admin_obj.approve_and_publish(request, JokeSubmission.objects.filter(pk=sub.pk))

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'published')
        self.assertIsNotNone(sub.published_joke)
        self.assertEqual(sub.published_joke.creator, self.creator)


class BackfillLogicTests(TestCase):
    """Test the backfill logic (inline, using live models)."""

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')
        cls.creator = User.objects.create_user(
            username='bf_creator@test.com', email='bf_creator@test.com', password='x',
        )

    def _run_backfill(self):
        """Replicate the migration forward logic with live models."""
        qs = JokeSubmission.objects.filter(
            status='published',
            published_joke__isnull=False,
            published_joke__creator__isnull=True,
        ).iterator()
        for s in qs:
            Joke.objects.filter(pk=s.published_joke_id).update(creator_id=s.user_id)

    def test_backfill_stamps_null_creator(self):
        j = _make_joke(self.fmt, self.age, self.lang, text='BF joke', creator=None)
        JokeSubmission.objects.create(
            user=self.creator, format=self.fmt, age_rating=self.age,
            language=self.lang, status='published', text='BF joke', published_joke=j,
        )
        self._run_backfill()
        j.refresh_from_db()
        self.assertEqual(j.creator, self.creator)

    def test_backfill_idempotent_skips_already_stamped(self):
        other = User.objects.create_user(
            username='idem_other@test.com', email='idem_other@test.com', password='x',
        )
        j = _make_joke(self.fmt, self.age, self.lang, text='Already stamped', creator=self.creator)
        JokeSubmission.objects.create(
            user=other, format=self.fmt, age_rating=self.age,
            language=self.lang, status='published', text='Already stamped', published_joke=j,
        )
        self._run_backfill()
        j.refresh_from_db()
        # Should remain self.creator, not be overwritten with other
        self.assertEqual(j.creator, self.creator)
