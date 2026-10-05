"""Joke admin review queue: editorial filters and audited publication actions."""
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from audit.models import AuditLog
from jokes.admin import JokeAdmin
from jokes.models import Joke, Tone
from jokes.tests_editorial_gate import GateFixture

User = get_user_model()


class ReviewQueueAdminTests(GateFixture):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(username='ed@t.com', email='ed@t.com', password='x')
        self.model_admin = JokeAdmin(Joke, AdminSite())
        self.dark = Tone.objects.get_or_create(slug='dark', defaults={'name': 'Dark'})[0]

    def request(self):
        req = RequestFactory().post('/')
        req.user = self.admin_user
        req.session = {}
        req._messages = FallbackStorage(req)
        return req

    def queryset(self, *jokes):
        return Joke.all_objects.filter(pk__in=[j.pk for j in jokes])

    def test_review_filters_are_available(self):
        for name in ('editorial_status', 'language', 'origin_country'):
            self.assertIn(name, self.model_admin.list_filter)

    def test_publish_as_ai_screened_refuses_dark_and_audits(self):
        dark = self.make('Held dark joke', status='generated')
        dark.tones.add(self.dark)
        self.model_admin.publish_ai_screened(self.request(), self.queryset(self.held, dark))
        self.assertEqual(Joke.all_objects.get(pk=self.held.pk).editorial_status, 'ai_screened')
        self.assertEqual(Joke.all_objects.get(pk=dark.pk).editorial_status, 'generated')
        self.assertTrue(AuditLog.objects.filter(
            action='editorial_publish_ai_screened', target_id=str(self.held.pk)).exists())
        self.assertFalse(AuditLog.objects.filter(target_id=str(dark.pk)).exists())

    def test_mark_native_reviewed_keeps_dark_out_of_tier_1(self):
        dark = self.make('Held dark joke', status='generated')
        dark.tones.add(self.dark)
        self.model_admin.mark_native_reviewed(self.request(), self.queryset(dark, self.screened))
        dark.refresh_from_db()
        self.assertEqual(dark.editorial_status, 'native_reviewed')
        self.assertEqual(dark.content_tier, 'tier_2')
        self.assertEqual(Joke.all_objects.get(pk=self.screened.pk).editorial_status, 'native_reviewed')
        self.assertEqual(AuditLog.objects.filter(action='editorial_native_reviewed').count(), 2)

    def test_hold_unpublishes_ai_content_but_never_creator_jokes(self):
        creator_joke = self.make('Creator joke', creator=self.creator, status='native_reviewed')
        self.model_admin.hold_jokes(self.request(), self.queryset(self.screened, creator_joke, self.human))
        self.assertEqual(Joke.all_objects.get(pk=self.screened.pk).editorial_status, 'generated')
        self.assertEqual(Joke.all_objects.get(pk=creator_joke.pk).editorial_status, 'native_reviewed')
        self.assertEqual(Joke.all_objects.get(pk=self.human.pk).editorial_status, 'legacy')
        self.assertTrue(AuditLog.objects.filter(action='editorial_hold', target_id=str(self.screened.pk)).exists())

    def test_actions_never_touch_removed_or_prohibited_jokes(self):
        Joke.all_objects.filter(pk=self.held.pk).update(is_removed=True)
        prohibited = self.make('Prohibited', status='generated', tier='tier_3')
        self.model_admin.publish_ai_screened(self.request(), self.queryset(self.held, prohibited))
        self.assertEqual(Joke.all_objects.get(pk=self.held.pk).editorial_status, 'generated')
        self.assertEqual(Joke.all_objects.get(pk=prohibited.pk).editorial_status, 'generated')


class UnpublishSideEffectTests(ReviewQueueAdminTests):
    """Bulk editorial updates bypass signals: unpublishing must still clean up
    the two surfaces that are not read-gated (share cards, community caches)."""

    def test_hold_deletes_the_share_card_file(self):
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.screened.share_image.save('card.png', SimpleUploadedFile('card.png', b'png-bytes'), save=False)
            Joke.all_objects.filter(pk=self.screened.pk).update(share_image=self.screened.share_image.name)
            path = self.screened.share_image.path
            self.model_admin.hold_jokes(self.request(), self.queryset(self.screened))
            held = Joke.all_objects.get(pk=self.screened.pk)
            self.assertEqual(held.editorial_status, 'generated')
            self.assertFalse(held.share_image)
            import os
            self.assertFalse(os.path.exists(path))

    def test_hold_refreshes_community_state_after_commit(self):
        from django.core.cache import cache

        from communities import services
        services.invalidate()
        before = cache.get(services.VERSION_KEY)
        with self.captureOnCommitCallbacks(execute=True):
            self.model_admin.hold_jokes(self.request(), self.queryset(self.screened))
        self.assertNotEqual(cache.get(services.VERSION_KEY), before)

    def test_held_joke_leaves_community_trending(self):
        from communities.models import Community
        from jokes.models import ContextTag
        tag = ContextTag.objects.create(name='Holdtheme', slug='holdtheme')
        self.screened.context_tags.add(tag)
        Community.objects.get_or_create(tag=tag)
        ids = lambda: [j['id'] for j in self.client.get('/api/v1/communities/holdtheme/').data['trending']]  # noqa: E731
        self.assertIn(self.screened.pk, ids())
        with self.captureOnCommitCallbacks(execute=True):
            self.model_admin.hold_jokes(self.request(), self.queryset(self.screened))
        self.assertNotIn(self.screened.pk, ids())
