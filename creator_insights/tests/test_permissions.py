"""
Tests for IsCreator permission.

A user must have at least one published JokeSubmission to pass.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory

from jokes.models import Format, AgeRating, Language, JokeSubmission, Joke

User = get_user_model()


def _make_joke(fmt, age, lang, text='Test joke'):
    """Create a Joke bypassing the share-image generation."""
    with patch('jokes.models.Joke._generate_share_image'):
        j = Joke.objects.create(text=text, format=fmt, age_rating=age, language=lang)
    return j


def _make_published_submission(user, fmt, age, lang):
    """Create a JokeSubmission in 'published' state with a linked published_joke."""
    joke = _make_joke(fmt, age, lang)
    sub = JokeSubmission.objects.create(
        user=user,
        format=fmt,
        age_rating=age,
        language=lang,
        status='published',
        text=joke.text,
        published_joke=joke,
    )
    return sub


class IsCreatorPermissionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')

        cls.creator = User.objects.create_user(
            username='creator@example.com',
            email='creator@example.com',
            password='pass',
        )
        _make_published_submission(cls.creator, cls.fmt, cls.age, cls.lang)

        cls.non_creator = User.objects.create_user(
            username='noncreator@example.com',
            email='noncreator@example.com',
            password='pass',
        )

    def _request(self, user=None, authenticated=True):
        from rest_framework.request import Request as DRFRequest
        factory = RequestFactory()
        req = factory.get('/')
        if user and authenticated:
            req.user = user
        else:
            from django.contrib.auth.models import AnonymousUser
            req.user = AnonymousUser()
        return req

    def test_user_with_published_submission_passes(self):
        from creator_insights.permissions import IsCreator
        perm = IsCreator()
        req = self._request(self.creator)
        self.assertTrue(perm.has_permission(req, None))

    def test_authenticated_user_without_published_submission_fails(self):
        from creator_insights.permissions import IsCreator
        perm = IsCreator()
        req = self._request(self.non_creator)
        self.assertFalse(perm.has_permission(req, None))

    def test_anonymous_user_fails(self):
        from creator_insights.permissions import IsCreator
        perm = IsCreator()
        req = self._request(authenticated=False)
        self.assertFalse(perm.has_permission(req, None))

    def test_user_with_only_draft_submission_fails(self):
        """A user with only draft (not published) submissions should not pass."""
        from creator_insights.permissions import IsCreator
        draft_user = User.objects.create_user(
            username='draft@example.com',
            email='draft@example.com',
            password='pass',
        )
        JokeSubmission.objects.create(
            user=draft_user,
            format=self.fmt,
            age_rating=self.age,
            language=self.lang,
            status='draft',
            text='Draft joke',
        )
        perm = IsCreator()
        req = self._request(draft_user)
        self.assertFalse(perm.has_permission(req, None))
