"""Wave 2 moderation tests: takedown enforcement, blocks, follow side-effects, report dedup, admin triage."""
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase
from rest_framework.test import APIClient

from follows import services as follow_services
from follows.models import Follow
from jokes.admin import ContentReportAdmin, JokeAdmin
from jokes.models import AgeRating, ContentReport, Format, Joke, Language, UserBlock
from jokes.moderation import hidden_user_ids, is_blocked_between, visible_jokes

User = get_user_model()


def _admin_request(user):
    req = RequestFactory().post('/')
    req.user = user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


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


class BlockServingSurfaceTests(ModerationBase):
    """Per-viewer block-hiding on the personalized/mystery serving surfaces."""

    def test_recommendations_never_serve_blocked_creator(self):
        other = User.objects.create_user(username='ot@t.com', email='ot@t.com', password='x')
        blocked_j = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        visible_j = _make_joke(self.fmt, self.age, self.lang, creator=other)
        UserBlock.objects.create(blocker=self.viewer, blocked=self.creator)
        # Constrain the pool to just our two jokes so the result is deterministic.
        others = list(Joke.all_objects.exclude(pk__in=[blocked_j.pk, visible_j.pk]).values_list('pk', flat=True))
        from jokes.recommendations import get_personalized_joke
        result = get_personalized_joke(
            self.viewer, exclude_joke_ids=others,
            allowed_tiers=frozenset({'tier_1', 'tier_2', 'tier_3'}),
        )
        self.assertEqual(result.pk, visible_j.pk)

    def test_mystery_pool_excludes_blocked_creator(self):
        from jokes.views import _mystery_pool_for_user
        other = User.objects.create_user(username='ot2@t.com', email='ot2@t.com', password='x')
        blocked_j = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        visible_j = _make_joke(self.fmt, self.age, self.lang, creator=other)
        UserBlock.objects.create(blocker=self.viewer, blocked=self.creator)
        pool, _ = _mystery_pool_for_user(self.viewer, allowed=frozenset({'tier_1'}))
        ids = set(pool.values_list('pk', flat=True))
        self.assertIn(visible_j.pk, ids)
        self.assertNotIn(blocked_j.pk, ids)


class ModerationAdminTests(ModerationBase):
    def test_take_down_joke_removes_and_resolves_reports(self):
        j = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        ContentReport.objects.create(reporter=self.viewer, joke=j, reason='spam', status='pending')
        admin_obj = ContentReportAdmin(ContentReport, AdminSite())
        admin_obj.take_down_joke(_admin_request(self.viewer), ContentReport.objects.filter(joke=j))
        reloaded = Joke.all_objects.get(pk=j.pk)
        self.assertTrue(reloaded.is_removed)
        self.assertIsNotNone(reloaded.removed_at)
        self.assertFalse(Joke.objects.filter(pk=j.pk).exists())
        report = ContentReport.objects.get(joke=j)
        self.assertEqual(report.status, 'resolved')
        self.assertIsNotNone(report.resolved_at)

    def test_dismiss_reports_leaves_joke_untouched(self):
        j = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        r = ContentReport.objects.create(reporter=self.viewer, joke=j, reason='spam', status='pending')
        admin_obj = ContentReportAdmin(ContentReport, AdminSite())
        admin_obj.dismiss_reports(_admin_request(self.viewer), ContentReport.objects.filter(pk=r.pk))
        r.refresh_from_db()
        self.assertEqual(r.status, 'dismissed')
        self.assertIsNotNone(r.resolved_at)
        self.assertFalse(Joke.all_objects.get(pk=j.pk).is_removed)

    def test_restore_jokes_action(self):
        j = _make_joke(self.fmt, self.age, self.lang, creator=self.creator, is_removed=True)
        admin_obj = JokeAdmin(Joke, AdminSite())
        admin_obj.restore_jokes(_admin_request(self.viewer), Joke.all_objects.filter(pk=j.pk))
        j.refresh_from_db()
        self.assertFalse(j.is_removed)
        self.assertIsNone(j.removed_at)

    def test_joke_admin_queryset_includes_removed(self):
        j = _make_joke(self.fmt, self.age, self.lang, creator=self.creator, is_removed=True)
        admin_obj = JokeAdmin(Joke, AdminSite())
        qs = admin_obj.get_queryset(_admin_request(self.viewer))
        self.assertIn(j.pk, set(qs.values_list('pk', flat=True)))
