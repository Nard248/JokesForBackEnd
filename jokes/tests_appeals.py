"""Appeals-wave Task 1 tests: Appeal model constraints, rejection-transition
notice, and reasoned takedown notice payload.

Task 2 tests (below): MediaAsset.quarantine()/release(), the reworked
take_down_joke (links kept, quarantine instead of delete), the lazy
expiry sweep, and the account-delete-still-purges-quarantined-files
invariant."""
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.contrib.messages.storage.fallback import FallbackStorage
from freezegun import freeze_time
from rest_framework.test import APIClient

from rest_framework.test import APIRequestFactory

from inbox.models import Notification
from jokes.admin import ContentReportAdmin
from jokes.models import (
    Appeal, ContentReport, Favorite, Joke, JokeMedia, JokePack, JokePackEntry,
    JokeSubmission, MediaAsset, SavedJoke,
)
from jokes.quarantine import purge_lapsed_quarantine
from jokes.serializers import JokeListSerializer, JokeSerializer
from jokes.tests_media import make_asset, make_image_joke, make_user, _taxonomy

_MEDIA_ROOT = tempfile.mkdtemp()


def _admin_request(user):
    req = RequestFactory().post('/')
    req.user = user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


def _make_joke(fmt, age, lang, creator, is_removed=False):
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text='Test', format=fmt, age_rating=age, language=lang,
            content_tier='tier_1', creator=creator, is_removed=is_removed,
        )


def _make_submission(user, fmt, age, lang, status='draft'):
    return JokeSubmission.objects.create(
        user=user, format=fmt, age_rating=age, language=lang,
        text='Test submission', status=status,
    )


class AppealTargetConstraintTests(TestCase):
    """Exactly one of joke/submission must be set (DB check constraint)."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('appellant@example.com')
        self.joke = _make_joke(self.fmt, self.age, self.lang, creator=self.user, is_removed=True)
        self.submission = _make_submission(self.user, self.fmt, self.age, self.lang, status='rejected')

    def test_both_targets_set_raises_integrity_error(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Appeal.objects.create(
                    user=self.user, joke=self.joke, submission=self.submission,
                    action_type='takedown', reason_text='please review',
                )

    def test_neither_target_set_raises_integrity_error(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Appeal.objects.create(
                    user=self.user, action_type='takedown', reason_text='please review',
                )

    def test_joke_only_is_valid(self):
        appeal = Appeal.objects.create(
            user=self.user, joke=self.joke, action_type='takedown', reason_text='please review',
        )
        self.assertIsNone(appeal.submission)

    def test_submission_only_is_valid(self):
        appeal = Appeal.objects.create(
            user=self.user, submission=self.submission, action_type='rejection',
            reason_text='please review',
        )
        self.assertIsNone(appeal.joke)


class AppealSingleOpenPerTargetTests(TestCase):
    """At most one PENDING appeal per (user, joke) or (user, submission)."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('appellant2@example.com')
        self.joke = _make_joke(self.fmt, self.age, self.lang, creator=self.user, is_removed=True)
        self.submission = _make_submission(self.user, self.fmt, self.age, self.lang, status='rejected')

    def test_second_pending_appeal_on_same_joke_raises(self):
        Appeal.objects.create(
            user=self.user, joke=self.joke, action_type='takedown', reason_text='first',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Appeal.objects.create(
                    user=self.user, joke=self.joke, action_type='takedown', reason_text='second',
                )

    def test_second_pending_appeal_on_same_submission_raises(self):
        Appeal.objects.create(
            user=self.user, submission=self.submission, action_type='rejection', reason_text='first',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Appeal.objects.create(
                    user=self.user, submission=self.submission, action_type='rejection', reason_text='second',
                )

    def test_resolved_appeal_allows_new_pending_on_joke(self):
        first = Appeal.objects.create(
            user=self.user, joke=self.joke, action_type='takedown', reason_text='first',
        )
        first.status = 'upheld'
        first.save(update_fields=['status'])
        second = Appeal.objects.create(
            user=self.user, joke=self.joke, action_type='takedown', reason_text='second',
        )
        self.assertEqual(second.status, 'pending')

    def test_resolved_appeal_allows_new_pending_on_submission(self):
        first = Appeal.objects.create(
            user=self.user, submission=self.submission, action_type='rejection', reason_text='first',
        )
        first.status = 'reversed'
        first.save(update_fields=['status'])
        second = Appeal.objects.create(
            user=self.user, submission=self.submission, action_type='rejection', reason_text='second',
        )
        self.assertEqual(second.status, 'pending')


class RejectionNoticeTests(TestCase):
    """A submission transitioning to 'rejected' notifies the author exactly
    once, with the rejection_reason in the notification payload."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('rejectee@example.com')

    def _rejected_notices(self):
        return Notification.objects.filter(recipient=self.user, verb='joke_rejected')

    def test_draft_to_rejected_fires_notice_once_with_reason(self):
        sub = _make_submission(self.user, self.fmt, self.age, self.lang, status='draft')
        sub.status = 'rejected'
        sub.rejection_reason = 'Duplicate of an existing joke'
        sub.save()
        notices = self._rejected_notices()
        self.assertEqual(notices.count(), 1)
        self.assertEqual(
            notices.get().data.get('rejection_reason'), 'Duplicate of an existing joke',
        )

    def test_saving_again_while_rejected_does_not_duplicate(self):
        sub = _make_submission(self.user, self.fmt, self.age, self.lang, status='draft')
        sub.status = 'rejected'
        sub.rejection_reason = 'Too long'
        sub.save()
        sub.text = 'Edited while rejected'
        sub.save()
        self.assertEqual(self._rejected_notices().count(), 1)

    def test_pending_to_published_fires_no_rejection_notice(self):
        sub = _make_submission(self.user, self.fmt, self.age, self.lang, status='pending')
        sub.status = 'published'
        sub.save()
        self.assertEqual(self._rejected_notices().count(), 0)


class TakedownNoticeTests(TestCase):
    """take_down_joke's joke_removed notice carries the most common triggering
    report reason and the 14-day appeal deadline (ISO)."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.creator = make_user('takendown@example.com')
        self.admin_user = make_user('mod@example.com')
        self.admin_obj = ContentReportAdmin(ContentReport, AdminSite())

    def _report(self, joke, reason, n):
        reporter = make_user(f'reporter{n}@example.com')
        return ContentReport.objects.create(
            reporter=reporter, joke=joke, reason=reason, status='pending',
        )

    def test_notice_carries_most_common_reason_and_deadline(self):
        joke = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        self._report(joke, 'spam', 1)
        self._report(joke, 'spam', 2)
        self._report(joke, 'harassment', 3)
        self.admin_obj.take_down_joke(
            _admin_request(self.admin_user), ContentReport.objects.filter(joke=joke),
        )
        notice = Notification.objects.get(recipient=self.creator, verb='joke_removed')
        self.assertEqual(notice.joke_id, joke.pk)
        self.assertEqual(notice.data['reason'], 'spam')
        removed_at = Joke.all_objects.get(pk=joke.pk).removed_at
        self.assertEqual(
            notice.data['appeal_deadline'], (removed_at + timedelta(days=14)).isoformat(),
        )

    def test_reason_is_grouped_per_joke(self):
        joke_a = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        joke_b = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        self._report(joke_a, 'spam', 4)
        self._report(joke_b, 'copyright', 5)
        self.admin_obj.take_down_joke(
            _admin_request(self.admin_user),
            ContentReport.objects.filter(joke__in=[joke_a, joke_b]),
        )
        notice_a = Notification.objects.get(
            recipient=self.creator, verb='joke_removed', joke=joke_a,
        )
        notice_b = Notification.objects.get(
            recipient=self.creator, verb='joke_removed', joke=joke_b,
        )
        self.assertEqual(notice_a.data['reason'], 'spam')
        self.assertEqual(notice_b.data['reason'], 'copyright')


# =============================================================================
# Task 2: MediaAsset.quarantine()/release()
# =============================================================================

def _asset_with_poster(owner):
    asset = make_asset(owner, kind='video')
    asset.poster.save('poster.jpg', ContentFile(b'fake-jpg-bytes'), save=False)
    asset.save(update_fields=['poster'])
    return asset


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class QuarantineMethodTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = make_user('quarantine-owner@example.com')

    def test_quarantine_moves_file_updates_name_and_stamps(self):
        asset = make_asset(self.user)
        old_name = asset.file.name
        asset.quarantine()
        self.assertFalse(default_storage.exists(old_name))
        self.assertTrue(asset.file.name.startswith(f'quarantine/{asset.pk}/'))
        self.assertTrue(default_storage.exists(asset.file.name))
        self.assertIsNotNone(asset.quarantined_at)
        # Persisted, not just in-memory.
        asset.refresh_from_db()
        self.assertTrue(asset.file.name.startswith(f'quarantine/{asset.pk}/'))
        self.assertIsNotNone(asset.quarantined_at)

    def test_quarantine_moves_poster_too(self):
        asset = _asset_with_poster(self.user)
        old_poster_name = asset.poster.name
        asset.quarantine()
        self.assertFalse(default_storage.exists(old_poster_name))
        self.assertTrue(asset.poster.name.startswith(f'quarantine/{asset.pk}/'))
        self.assertTrue(default_storage.exists(asset.poster.name))
        asset.refresh_from_db()
        self.assertTrue(asset.poster.name.startswith(f'quarantine/{asset.pk}/'))

    def test_quarantine_is_idempotent(self):
        asset = make_asset(self.user)
        asset.quarantine()
        name_after_first = asset.file.name
        stamp_after_first = asset.quarantined_at
        asset.quarantine()  # second call must be a no-op
        self.assertEqual(asset.file.name, name_after_first)
        self.assertEqual(asset.quarantined_at, stamp_after_first)
        self.assertTrue(default_storage.exists(asset.file.name))

    def test_release_restores_original_style_path_and_clears_stamp(self):
        asset = make_asset(self.user)
        asset.quarantine()
        quarantine_name = asset.file.name
        asset.release()
        self.assertFalse(default_storage.exists(quarantine_name))
        self.assertTrue(asset.file.name.startswith(f'media-assets/{asset.pk}/'))
        self.assertTrue(default_storage.exists(asset.file.name))
        self.assertIsNone(asset.quarantined_at)
        asset.refresh_from_db()
        self.assertTrue(asset.file.name.startswith(f'media-assets/{asset.pk}/'))
        self.assertIsNone(asset.quarantined_at)

    def test_release_restores_poster_too(self):
        asset = _asset_with_poster(self.user)
        asset.quarantine()
        asset.release()
        self.assertTrue(asset.poster.name.startswith(f'media-assets/{asset.pk}/'))
        self.assertTrue(default_storage.exists(asset.poster.name))


# =============================================================================
# Task 2: take_down_joke rework — links kept, quarantine instead of delete
# =============================================================================

@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class TakedownQuarantineReworkTests(TestCase):
    """REPLACES the wave-2 shared-asset takedown semantics (also updated
    directly in jokes/tests_media.py): takedown no longer detaches links or
    hard-deletes files. See jokes/tests_media.py::MediaPublishAndLifecycleTests
    for the equivalent coverage exercised through the publish flow; these
    tests exercise the same contract directly against JokeMedia."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.creator = make_user('media-creator@example.com')
        self.admin_user = make_user('media-mod@example.com')
        self.admin_obj = ContentReportAdmin(ContentReport, AdminSite())

    def test_unshared_asset_is_quarantined_and_link_kept(self):
        joke = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        asset = make_asset(self.creator)
        JokeMedia.objects.create(joke=joke, asset=asset, position=0)
        old_name = asset.file.name
        report = ContentReport.objects.create(
            reporter=self.admin_user, joke=joke, reason='spam',
        )
        self.admin_obj.take_down_joke(
            _admin_request(self.admin_user), ContentReport.objects.filter(pk=report.pk),
        )
        joke.refresh_from_db()
        self.assertTrue(joke.is_removed)
        # Link KEPT — needed to reverse on appeal.
        self.assertTrue(JokeMedia.objects.filter(joke=joke, asset=asset).exists())
        asset.refresh_from_db()
        self.assertIsNotNone(asset.quarantined_at)
        self.assertFalse(default_storage.exists(old_name))
        self.assertTrue(asset.file.name.startswith(f'quarantine/{asset.pk}/'))
        self.assertTrue(default_storage.exists(asset.file.name))
        self.assertTrue(MediaAsset.objects.filter(pk=asset.pk).exists())

    def test_asset_shared_with_live_joke_is_untouched(self):
        joke_a = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        joke_b = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        shared = make_asset(self.creator)
        JokeMedia.objects.create(joke=joke_a, asset=shared, position=0)
        JokeMedia.objects.create(joke=joke_b, asset=shared, position=0)
        shared_name = shared.file.name
        report = ContentReport.objects.create(
            reporter=self.admin_user, joke=joke_a, reason='spam',
        )
        self.admin_obj.take_down_joke(
            _admin_request(self.admin_user), ContentReport.objects.filter(pk=report.pk),
        )
        shared.refresh_from_db()
        self.assertIsNone(shared.quarantined_at)
        self.assertEqual(shared.file.name, shared_name)
        self.assertTrue(default_storage.exists(shared_name))
        # Both links intact — joke_a's too (kept, not detached).
        self.assertTrue(JokeMedia.objects.filter(joke=joke_a, asset=shared).exists())
        self.assertTrue(JokeMedia.objects.filter(joke=joke_b, asset=shared).exists())

    def test_partial_quarantine_failure_continues_batch_and_warns(self):
        # One asset's quarantine() blowing up must not abort the batch:
        # the other asset still gets quarantined, the takedown completes,
        # and the admin sees a WARNING naming the failed asset.
        joke = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        good = make_asset(self.creator)
        bad = make_asset(self.creator)
        JokeMedia.objects.create(joke=joke, asset=good, position=0)
        JokeMedia.objects.create(joke=joke, asset=bad, position=1)
        report = ContentReport.objects.create(
            reporter=self.admin_user, joke=joke, reason='spam',
        )
        real_quarantine = MediaAsset.quarantine

        def flaky_quarantine(asset_self):
            if asset_self.pk == bad.pk:
                raise RuntimeError('storage down')
            return real_quarantine(asset_self)

        req = _admin_request(self.admin_user)
        with patch.object(MediaAsset, 'quarantine', flaky_quarantine):
            self.admin_obj.take_down_joke(
                req, ContentReport.objects.filter(pk=report.pk),
            )
        joke.refresh_from_db()
        self.assertTrue(joke.is_removed)
        good.refresh_from_db()
        bad.refresh_from_db()
        self.assertIsNotNone(good.quarantined_at)
        self.assertIsNone(bad.quarantined_at)
        msgs = [str(m) for m in req._messages]
        self.assertTrue(
            any('quarantine' in m.lower() and str(bad.pk) in m for m in msgs),
            f'expected a warning naming asset {bad.pk}, got: {msgs}',
        )


# =============================================================================
# Fix: crash-safe quarantine ordering (copy-all -> save -> delete-old)
# =============================================================================

@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class QuarantineCrashSafetyTests(TestCase):
    """_move_stored_files must persist the new paths BEFORE deleting the old
    objects: a failed delete leaves at worst a recoverable duplicate — never a
    DB row pointing at an already-deleted path."""

    def test_failed_old_delete_leaves_recoverable_state(self):
        user = make_user('crash-safety@example.com')
        asset = make_asset(user)
        old_name = asset.file.name
        with patch(
            'jokes.models.default_storage.delete', side_effect=OSError('gcs 500'),
        ):
            with self.assertRaises(OSError):
                asset.quarantine()
        asset.refresh_from_db()
        # The DB already points at the NEW path and the bytes are there.
        self.assertTrue(asset.file.name.startswith(f'quarantine/{asset.pk}/'))
        self.assertTrue(default_storage.exists(asset.file.name))
        self.assertIsNotNone(asset.quarantined_at)
        # The old object still exists — a harmless duplicate, not a lost file.
        self.assertTrue(default_storage.exists(old_name))
        # A re-run completes cleanly (idempotent on the stamped asset).
        asset.quarantine()
        self.assertTrue(asset.file.name.startswith(f'quarantine/{asset.pk}/'))
        self.assertTrue(default_storage.exists(asset.file.name))


# =============================================================================
# Fix: removed jokes must vanish from saved-jokes / favorites / pack detail
# =============================================================================

@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class RemovedJokeSurfaceGatingTests(TestCase):
    """CRITICAL: these three surfaces never filtered joke__is_removed, so a
    taken-down joke kept serving its text AND (post-quarantine-rework, since
    JokeMedia links are now kept) its quarantine-path media URLs."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.creator = make_user('surface-creator@example.com')
        self.viewer = make_user('surface-viewer@example.com')
        self.admin_user = make_user('surface-mod@example.com')
        self.admin_obj = ContentReportAdmin(ContentReport, AdminSite())
        self.live = make_image_joke(self.creator, setup='live joke')
        self.removed = make_image_joke(self.creator, setup='doomed joke')

    def _take_down(self, joke):
        report = ContentReport.objects.create(
            reporter=self.admin_user, joke=joke, reason='spam',
        )
        self.admin_obj.take_down_joke(
            _admin_request(self.admin_user), ContentReport.objects.filter(pk=report.pk),
        )

    def _client(self):
        client = APIClient()
        client.force_authenticate(self.viewer)
        return client

    @staticmethod
    def _joke_ids(resp):
        data = resp.json()
        results = data.get('results', data) if isinstance(data, dict) else data
        return {item['joke']['id'] for item in (results if isinstance(results, list) else [])}

    def test_saved_jokes_list_drops_removed_joke(self):
        SavedJoke.objects.create(user=self.viewer, joke=self.live)
        SavedJoke.objects.create(user=self.viewer, joke=self.removed)
        self._take_down(self.removed)
        resp = self._client().get('/api/v1/saved-jokes/')
        self.assertEqual(resp.status_code, 200)
        ids = self._joke_ids(resp)
        self.assertIn(self.live.pk, ids)
        self.assertNotIn(self.removed.pk, ids)

    def test_favorites_list_drops_removed_joke(self):
        Favorite.objects.create(user=self.viewer, joke=self.live)
        Favorite.objects.create(user=self.viewer, joke=self.removed)
        self._take_down(self.removed)
        resp = self._client().get('/api/v1/favorites/')
        self.assertEqual(resp.status_code, 200)
        ids = self._joke_ids(resp)
        self.assertIn(self.live.pk, ids)
        self.assertNotIn(self.removed.pk, ids)

    def test_pack_detail_drops_removed_joke(self):
        pack = JokePack.objects.create(
            slug='appeals-gating-pack', title='Gating Pack', is_published=True,
        )
        JokePackEntry.objects.create(pack=pack, joke=self.live, order=1)
        JokePackEntry.objects.create(pack=pack, joke=self.removed, order=2)
        self._take_down(self.removed)
        resp = APIClient().get(f'/api/v1/packs/{pack.slug}/')
        self.assertEqual(resp.status_code, 200)
        ids = {e['joke']['id'] for e in resp.json().get('jokes', [])}
        self.assertIn(self.live.pk, ids)
        self.assertNotIn(self.removed.pk, ids)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class RemovedJokeSerializerMediaTests(TestCase):
    """Defense-in-depth choke point: even if some future path serializes a
    removed joke, get_media emits [] — no quarantine URLs can leak."""

    def setUp(self):
        self.user = make_user('serializer-belt@example.com')
        joke = make_image_joke(self.user)
        # Flip via queryset update (no model save side effects).
        Joke.all_objects.filter(pk=joke.pk).update(is_removed=True)
        self.joke = Joke.all_objects.get(pk=joke.pk)
        self.request = APIRequestFactory().get('/api/v1/jokes/')

    def test_detail_serializer_emits_empty_media_for_removed_joke(self):
        data = JokeSerializer(self.joke, context={'request': self.request}).data
        self.assertEqual(data['media'], [])

    def test_list_serializer_emits_empty_media_for_removed_joke(self):
        data = JokeListSerializer(self.joke, context={'request': self.request}).data
        self.assertEqual(data['media'], [])


# =============================================================================
# Task 2: lazy expiry sweep
# =============================================================================

@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class QuarantineExpiryTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.creator = make_user('expiry-owner@example.com')
        self.joke = _make_joke(
            self.fmt, self.age, self.lang, creator=self.creator, is_removed=True,
        )

    def _quarantined_asset(self, when):
        asset = make_asset(self.creator)
        JokeMedia.objects.create(joke=self.joke, asset=asset, position=0)
        with freeze_time(when):
            asset.quarantine()
        return asset

    def test_lapsed_15d_no_open_appeal_is_purged(self):
        asset = self._quarantined_asset('2026-07-01 12:00:00')
        name = asset.file.name
        with freeze_time('2026-07-16 12:00:01'):  # 15 days + 1s later
            purge_lapsed_quarantine()
        self.assertFalse(MediaAsset.objects.filter(pk=asset.pk).exists())
        self.assertFalse(default_storage.exists(name))

    def test_lapsed_15d_with_open_appeal_is_kept(self):
        asset = self._quarantined_asset('2026-07-01 12:00:00')
        Appeal.objects.create(
            user=self.creator, joke=self.joke, action_type='takedown',
            reason_text='please review',
        )
        with freeze_time('2026-07-16 12:00:01'):
            purge_lapsed_quarantine()
        self.assertTrue(MediaAsset.objects.filter(pk=asset.pk).exists())
        asset.refresh_from_db()
        self.assertIsNotNone(asset.quarantined_at)

    def test_not_yet_lapsed_13d_is_kept(self):
        asset = self._quarantined_asset('2026-07-01 12:00:00')
        with freeze_time('2026-07-14 12:00:00'):  # 13 days later
            purge_lapsed_quarantine()
        self.assertTrue(MediaAsset.objects.filter(pk=asset.pk).exists())

    def test_resolved_appeal_no_longer_blocks_purge(self):
        # An upheld/reversed appeal is no longer OPEN — it must not shield
        # a lapsed quarantine from the sweep forever.
        asset = self._quarantined_asset('2026-07-01 12:00:00')
        appeal = Appeal.objects.create(
            user=self.creator, joke=self.joke, action_type='takedown',
            reason_text='please review', status='upheld',
        )
        with freeze_time('2026-07-16 12:00:01'):
            purge_lapsed_quarantine()
        self.assertFalse(MediaAsset.objects.filter(pk=asset.pk).exists())


# =============================================================================
# Task 2: account deletion still purges quarantined files (erasure wins)
# =============================================================================

@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class AccountDeleteQuarantineTests(TestCase):
    def test_account_delete_removes_quarantined_files(self):
        user = make_user('delete-quarantined@example.com')
        asset = make_asset(user)
        asset.quarantine()
        name = asset.file.name
        self.assertTrue(default_storage.exists(name))

        client = APIClient()
        client.force_authenticate(user)
        response = client.delete(
            '/api/v1/users/me/', {'password': 'x'}, format='json',
        )
        self.assertIn(response.status_code, (200, 204))
        self.assertFalse(MediaAsset.objects.filter(pk=asset.pk).exists())
        self.assertFalse(default_storage.exists(name))
