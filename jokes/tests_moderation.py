"""Wave 2 moderation tests: takedown enforcement, blocks, follow side-effects, report dedup."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from jokes.models import Format, AgeRating, Language, Joke, ContentReport, UserBlock
from jokes.moderation import hidden_user_ids, is_blocked_between, visible_jokes
from follows import services as follow_services
from follows.models import Follow

User = get_user_model()


def _make_joke(fmt, age, lang, creator=None, text='Test', content_tier='tier_1', is_removed=False):
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text=text, format=fmt, age_rating=age, language=lang,
            content_tier=content_tier, creator=creator, is_removed=is_removed,
        )


def _ids(resp):
    data = resp.data
    rows = data['results'] if isinstance(data, dict) and 'results' in data else data
    return {row['id'] for row in rows}


class ModerationBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')
        cls.creator = User.objects.create_user(username='cr@t.com', email='cr@t.com', password='x')
        cls.viewer = User.objects.create_user(username='vw@t.com', email='vw@t.com', password='x')


class TakedownEnforcementTests(ModerationBase):
    def test_removed_joke_hidden_from_default_manager_but_in_all_objects(self):
        j = _make_joke(self.fmt, self.age, self.lang, creator=self.creator, is_removed=True)
        self.assertFalse(Joke.objects.filter(pk=j.pk).exists())
        self.assertTrue(Joke.all_objects.filter(pk=j.pk).exists())

    def test_removed_joke_excluded_from_feed(self):
        visible = _make_joke(self.fmt, self.age, self.lang, creator=self.creator, text='Visible')
        removed = _make_joke(self.fmt, self.age, self.lang, creator=self.creator, text='Gone', is_removed=True)
        client = APIClient()
        client.force_authenticate(self.viewer)
        resp = client.get('/api/v1/jokes/')
        self.assertEqual(resp.status_code, 200)
        ids = _ids(resp)
        self.assertIn(visible.pk, ids)
        self.assertNotIn(removed.pk, ids)


class BlockHelperTests(ModerationBase):
    def test_is_blocked_between_symmetric(self):
        UserBlock.objects.create(blocker=self.viewer, blocked=self.creator)
        self.assertTrue(is_blocked_between(self.viewer, self.creator))
        self.assertTrue(is_blocked_between(self.creator, self.viewer))

    def test_hidden_user_ids_both_directions(self):
        other = User.objects.create_user(username='o@t.com', email='o@t.com', password='x')
        UserBlock.objects.create(blocker=self.viewer, blocked=self.creator)  # I blocked creator
        UserBlock.objects.create(blocker=other, blocked=self.viewer)         # other blocked me
        self.assertEqual(hidden_user_ids(self.viewer), {self.creator.pk, other.pk})

    def test_hidden_user_ids_empty_for_anonymous(self):
        self.assertEqual(hidden_user_ids(None), set())

    def test_visible_jokes_excludes_blocked_creator(self):
        j = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        UserBlock.objects.create(blocker=self.viewer, blocked=self.creator)

        class Req:
            user = self.viewer
        qs = visible_jokes(Joke.objects.all(), Req())
        self.assertNotIn(j.pk, set(qs.values_list('pk', flat=True)))


class BlockFeedAndProfileTests(ModerationBase):
    def test_feed_hides_blocked_users_jokes(self):
        j = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        client = APIClient()
        client.force_authenticate(self.viewer)
        self.assertIn(j.pk, _ids(client.get('/api/v1/jokes/')))
        UserBlock.objects.create(blocker=self.viewer, blocked=self.creator)
        self.assertNotIn(j.pk, _ids(client.get('/api/v1/jokes/')))

    def test_creator_profile_404_when_blocked(self):
        _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        UserBlock.objects.create(blocker=self.viewer, blocked=self.creator)
        client = APIClient()
        client.force_authenticate(self.viewer)
        resp = client.get(f'/api/v1/creators/{self.creator.pk}/profile/')
        self.assertEqual(resp.status_code, 404)


class BlockFollowInteractionTests(ModerationBase):
    def test_follow_blocked_user_raises(self):
        UserBlock.objects.create(blocker=self.viewer, blocked=self.creator)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            follow_services.follow(self.viewer, self.creator)

    def test_block_severs_follows_both_ways(self):
        Follow.objects.create(follower=self.viewer, creator=self.creator)
        Follow.objects.create(follower=self.creator, creator=self.viewer)
        client = APIClient()
        client.force_authenticate(self.viewer)
        resp = client.post(f'/api/v1/users/{self.creator.pk}/block/')
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(Follow.objects.filter(follower=self.viewer, creator=self.creator).exists())
        self.assertFalse(Follow.objects.filter(follower=self.creator, creator=self.viewer).exists())

    def test_my_blocks_lists_blocked_users(self):
        UserBlock.objects.create(blocker=self.viewer, blocked=self.creator)
        client = APIClient()
        client.force_authenticate(self.viewer)
        resp = client.get('/api/v1/users/me/blocks/')
        self.assertEqual(resp.status_code, 200)
        ids = {row['id'] for row in resp.data['results']}
        self.assertEqual(ids, {self.creator.pk})


class ReportDedupTests(ModerationBase):
    def test_duplicate_pending_report_returns_existing(self):
        j = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        client = APIClient()
        client.force_authenticate(self.viewer)
        r1 = client.post('/api/v1/reports/', {'joke': j.pk, 'reason': 'spam'}, format='json')
        self.assertEqual(r1.status_code, 201)
        r2 = client.post('/api/v1/reports/', {'joke': j.pk, 'reason': 'spam'}, format='json')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(ContentReport.objects.filter(reporter=self.viewer, joke=j).count(), 1)
