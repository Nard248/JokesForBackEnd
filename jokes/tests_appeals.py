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

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.contrib.messages.storage.fallback import FallbackStorage
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from rest_framework.test import APIRequestFactory

from audit.models import AuditLog
from inbox.models import Notification
from inbox.services import notify
from jokes.admin import AppealAdmin, ContentReportAdmin, JokeAdmin, OverdueAppealFilter
from jokes.models import (
    Appeal, Collection, ContentReport, DailyJoke, Favorite, Joke, JokeMedia,
    JokePack, JokePackEntry, JokeSubmission, JokeSubmissionMedia, JokeView,
    MediaAsset, SavedJoke,
)
from jokes.quarantine import purge_lapsed_quarantine
from jokes.serializers import (
    JokeListSerializer, JokeSerializer, JokeSubmissionListSerializer,
)
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


def _removed_joke(fmt, age, lang, creator, removed_at=None):
    """A removed joke with `removed_at` actually stamped (unlike the bare
    `_make_joke(is_removed=True)`, needed for the appeal window checks)."""
    joke = _make_joke(fmt, age, lang, creator=creator, is_removed=True)
    Joke.all_objects.filter(pk=joke.pk).update(removed_at=removed_at or timezone.now())
    return Joke.all_objects.get(pk=joke.pk)


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
        notice = notices.get()
        self.assertEqual(
            notice.data.get('rejection_reason'), 'Duplicate of an existing joke',
        )
        self.assertEqual(notice.data.get('submission_id'), sub.pk)

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
        # The joke FK (not `data`) is how the FE deep-links the appeal for a
        # removed joke: the notification serializer's `joke` field already
        # exposes {'id': ..., 'preview': ...} off this FK, so no joke_id
        # needs duplicating into `data`.
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

    def test_quarantine_path_is_not_derivable_from_public_path(self):
        """R1 (final-review): the pk is the SAME uuid that was in the
        pre-takedown PUBLIC url, so the quarantine path must carry an
        unguessable segment BEYOND pk/basename — otherwise anyone who saw the
        live joke can reconstruct the quarantine url by prefix substitution
        and fetch the taken-down file from the public bucket."""
        asset = make_asset(self.user)
        public_name = asset.file.name  # media-assets/<uuid>/image.webp
        basename = public_name.rsplit('/', 1)[-1]
        asset.quarantine()
        derivable = f'quarantine/{asset.pk}/{basename}'
        # The naive/derivable path must NOT be where the file lives.
        self.assertNotEqual(asset.file.name, derivable)
        self.assertFalse(default_storage.exists(derivable))
        # There is an unguessable segment between the pk dir and the basename.
        middle = asset.file.name[len(f'quarantine/{asset.pk}/'):-len(basename) - 1]
        self.assertTrue(len(middle) >= 16)
        # Two quarantines of two assets don't collide on a shared secret.
        other = make_asset(self.user)
        other.quarantine()
        other_middle = other.file.name[len(f'quarantine/{other.pk}/'):-len(basename) - 1]
        self.assertNotEqual(middle, other_middle)

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

    def test_detail_serializer_share_image_url_is_none_for_removed_joke(self):
        data = JokeSerializer(self.joke, context={'request': self.request}).data
        self.assertIsNone(data['share_image_url'])

    def test_list_serializer_share_image_url_is_none_for_removed_joke(self):
        data = JokeListSerializer(self.joke, context={'request': self.request}).data
        self.assertIsNone(data['share_image_url'])


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


# =============================================================================
# Task 3: POST /appeals/ — create validation matrix
# =============================================================================

class AppealCreateHappyPathTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('appeal-happy@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_takedown_appeal_returns_201_pending_row_and_audit(self):
        joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.user)
        response = self.client.post(
            '/api/v1/appeals/',
            {'joke_id': joke.pk, 'reason_text': 'please review my joke'},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data['status'], 'pending')
        self.assertEqual(data['action_type'], 'takedown')
        self.assertEqual(data['target_type'], 'joke')
        self.assertEqual(data['target_id'], joke.pk)
        appeal = Appeal.objects.get(user=self.user, joke=joke)
        self.assertEqual(appeal.status, 'pending')
        self.assertTrue(AuditLog.objects.filter(action='appeal_filed').exists())

    def test_rejection_appeal_returns_201_pending_row_and_audit(self):
        sub = _make_submission(self.user, self.fmt, self.age, self.lang, status='rejected')
        response = self.client.post(
            '/api/v1/appeals/',
            {'submission_id': sub.pk, 'reason_text': 'please reconsider'},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data['status'], 'pending')
        self.assertEqual(data['action_type'], 'rejection')
        self.assertEqual(data['target_type'], 'submission')
        self.assertEqual(data['target_id'], sub.pk)
        appeal = Appeal.objects.get(user=self.user, submission=sub)
        self.assertEqual(appeal.status, 'pending')
        self.assertTrue(AuditLog.objects.filter(action='appeal_filed').exists())


class AppealCreateValidationTests(TestCase):
    """The security surface: every rejection path must be a clean 400/404.
    404 for not-your-target/nonexistent (avoid existence leaks); 400 for
    window/duplicate/wrong-state (caller already knows it's their own)."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('appeal-validate@example.com')
        self.other = make_user('appeal-validate-other@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_both_targets_given_is_400(self):
        joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.user)
        sub = _make_submission(self.user, self.fmt, self.age, self.lang, status='rejected')
        response = self.client.post(
            '/api/v1/appeals/',
            {'joke_id': joke.pk, 'submission_id': sub.pk, 'reason_text': 'x'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_neither_target_given_is_400(self):
        response = self.client.post(
            '/api/v1/appeals/', {'reason_text': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_nonexistent_joke_is_404(self):
        response = self.client.post(
            '/api/v1/appeals/', {'joke_id': 9_999_999, 'reason_text': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_submission_is_404(self):
        response = self.client.post(
            '/api/v1/appeals/', {'submission_id': 9_999_999, 'reason_text': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_not_your_joke_is_404(self):
        joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.other)
        response = self.client.post(
            '/api/v1/appeals/', {'joke_id': joke.pk, 'reason_text': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_not_your_submission_is_404(self):
        sub = _make_submission(self.other, self.fmt, self.age, self.lang, status='rejected')
        response = self.client.post(
            '/api/v1/appeals/', {'submission_id': sub.pk, 'reason_text': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_joke_not_removed_is_400(self):
        joke = _make_joke(self.fmt, self.age, self.lang, creator=self.user, is_removed=False)
        response = self.client.post(
            '/api/v1/appeals/', {'joke_id': joke.pk, 'reason_text': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_submission_not_rejected_is_400(self):
        sub = _make_submission(self.user, self.fmt, self.age, self.lang, status='draft')
        response = self.client.post(
            '/api/v1/appeals/', {'submission_id': sub.pk, 'reason_text': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_takedown_window_lapsed_is_400(self):
        joke = _removed_joke(
            self.fmt, self.age, self.lang, creator=self.user,
            removed_at=timezone.now() - timedelta(days=15),
        )
        response = self.client.post(
            '/api/v1/appeals/', {'joke_id': joke.pk, 'reason_text': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_rejection_window_lapsed_is_400(self):
        with freeze_time(timezone.now() - timedelta(days=15)):
            sub = _make_submission(self.user, self.fmt, self.age, self.lang, status='rejected')
        response = self.client.post(
            '/api/v1/appeals/', {'submission_id': sub.pk, 'reason_text': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_open_takedown_appeal_is_400(self):
        joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.user)
        Appeal.objects.create(
            user=self.user, joke=joke, action_type='takedown', reason_text='first',
        )
        response = self.client.post(
            '/api/v1/appeals/', {'joke_id': joke.pk, 'reason_text': 'second'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_open_rejection_appeal_is_400(self):
        sub = _make_submission(self.user, self.fmt, self.age, self.lang, status='rejected')
        Appeal.objects.create(
            user=self.user, submission=sub, action_type='rejection', reason_text='first',
        )
        response = self.client.post(
            '/api/v1/appeals/', {'submission_id': sub.pk, 'reason_text': 'second'}, format='json',
        )
        self.assertEqual(response.status_code, 400)


class AppealThrottleScopeTests(TestCase):
    def test_appeals_throttle_scope_is_registered(self):
        rates = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
        self.assertIn('appeals', rates)
        self.assertEqual(rates['appeals'], '10/day')


class MyAppealsViewTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('my-appeals@example.com')
        self.other = make_user('my-appeals-other@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_returns_only_callers_appeals(self):
        joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.user)
        other_joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.other)
        mine = Appeal.objects.create(
            user=self.user, joke=joke, action_type='takedown', reason_text='mine',
        )
        Appeal.objects.create(
            user=self.other, joke=other_joke, action_type='takedown', reason_text='theirs',
        )
        response = self.client.get('/api/v1/users/me/appeals/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        results = payload.get('results', payload) if isinstance(payload, dict) else payload
        ids = {item['id'] for item in results}
        self.assertEqual(ids, {mine.pk})


class NotificationDataEncoderTests(TestCase):
    """Injected item 1: Notification.data needs encoder=DjangoJSONEncoder or
    a raw datetime in notify(**extra) crashes create() at write time."""

    def test_datetime_in_notify_payload_survives(self):
        user = make_user('encoder-datetime@example.com')
        notice = notify(user, 'appeal_resolved', outcome='upheld', resolved_at=timezone.now())
        notice.refresh_from_db()
        self.assertIsInstance(notice.data['resolved_at'], str)
        self.assertEqual(notice.data['outcome'], 'upheld')


# =============================================================================
# Task 3: AppealAdmin resolution actions (uphold / reverse)
# =============================================================================

@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class AppealUpholdTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.creator = make_user('uphold-creator@example.com')
        self.admin_user = make_user('uphold-mod@example.com')
        self.report_admin = ContentReportAdmin(ContentReport, AdminSite())
        self.appeal_admin = AppealAdmin(Appeal, AdminSite())

    def _take_down(self, joke):
        report = ContentReport.objects.create(
            reporter=self.admin_user, joke=joke, reason='spam',
        )
        self.report_admin.take_down_joke(
            _admin_request(self.admin_user), ContentReport.objects.filter(pk=report.pk),
        )

    def test_uphold_purges_quarantined_media_and_notifies(self):
        joke = make_image_joke(self.creator)
        asset = JokeMedia.objects.get(joke=joke).asset
        self._take_down(joke)
        asset.refresh_from_db()
        file_name = asset.file.name
        self.assertIsNotNone(asset.quarantined_at)
        self.assertTrue(default_storage.exists(file_name))

        appeal = Appeal.objects.create(
            user=self.creator, joke=Joke.all_objects.get(pk=joke.pk),
            action_type='takedown', reason_text='please review',
        )
        req = _admin_request(self.admin_user)
        self.appeal_admin.uphold_appeals(req, Appeal.objects.filter(pk=appeal.pk))

        appeal.refresh_from_db()
        self.assertEqual(appeal.status, 'upheld')
        self.assertEqual(appeal.resolver_id, self.admin_user.pk)
        self.assertIsNotNone(appeal.resolved_at)
        # The media asset's row AND its storage file are truly gone.
        self.assertFalse(MediaAsset.objects.filter(pk=asset.pk).exists())
        self.assertFalse(default_storage.exists(file_name))

        notice = Notification.objects.get(recipient=self.creator, verb='appeal_resolved')
        self.assertEqual(notice.data['outcome'], 'upheld')
        self.assertEqual(notice.data['action_type'], 'takedown')

    def test_uphold_skips_non_pending_appeal(self):
        joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.creator)
        appeal = Appeal.objects.create(
            user=self.creator, joke=joke, action_type='takedown',
            reason_text='x', status='reversed',
        )
        req = _admin_request(self.admin_user)
        self.appeal_admin.uphold_appeals(req, Appeal.objects.filter(pk=appeal.pk))
        appeal.refresh_from_db()
        self.assertEqual(appeal.status, 'reversed')
        self.assertFalse(
            Notification.objects.filter(recipient=self.creator, verb='appeal_resolved').exists()
        )

    def test_uphold_skips_purge_for_asset_shared_with_live_joke(self):
        """Minor fix: uphold's purge must mirror take_down_joke's
        still_shared guard — a quarantined asset that got re-attached to a
        different, still-live joke (a reversal-era reshare) must survive."""
        joke_a = make_image_joke(self.creator)
        asset = JokeMedia.objects.get(joke=joke_a).asset
        self._take_down(joke_a)
        asset.refresh_from_db()
        self.assertIsNotNone(asset.quarantined_at)
        file_name = asset.file.name

        joke_b = make_image_joke(self.creator)  # live, untouched
        JokeMedia.objects.create(joke=joke_b, asset=asset, position=1)

        appeal = Appeal.objects.create(
            user=self.creator, joke=Joke.all_objects.get(pk=joke_a.pk),
            action_type='takedown', reason_text='please review',
        )
        req = _admin_request(self.admin_user)
        self.appeal_admin.uphold_appeals(req, Appeal.objects.filter(pk=appeal.pk))

        appeal.refresh_from_db()
        self.assertEqual(appeal.status, 'upheld')
        # Survives — still shared with the live joke_b.
        self.assertTrue(MediaAsset.objects.filter(pk=asset.pk).exists())
        self.assertTrue(default_storage.exists(file_name))


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class AppealReverseTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.creator = make_user('reverse-creator@example.com')
        self.admin_user = make_user('reverse-mod@example.com')
        self.report_admin = ContentReportAdmin(ContentReport, AdminSite())
        self.appeal_admin = AppealAdmin(Appeal, AdminSite())

    def _take_down(self, joke):
        report = ContentReport.objects.create(
            reporter=self.admin_user, joke=joke, reason='spam',
        )
        self.report_admin.take_down_joke(
            _admin_request(self.admin_user), ContentReport.objects.filter(pk=report.pk),
        )

    def test_reverse_takedown_restores_media_joke_and_serving(self):
        joke = make_image_joke(self.creator)
        asset = JokeMedia.objects.get(joke=joke).asset
        self._take_down(joke)
        asset.refresh_from_db()
        self.assertIsNotNone(asset.quarantined_at)

        appeal = Appeal.objects.create(
            user=self.creator, joke=Joke.all_objects.get(pk=joke.pk),
            action_type='takedown', reason_text='please review',
        )
        req = _admin_request(self.admin_user)
        self.appeal_admin.reverse_appeals(req, Appeal.objects.filter(pk=appeal.pk))

        appeal.refresh_from_db()
        self.assertEqual(appeal.status, 'reversed')
        self.assertEqual(appeal.resolver_id, self.admin_user.pk)

        asset.refresh_from_db()
        self.assertIsNone(asset.quarantined_at)
        self.assertTrue(asset.file.name.startswith(f'media-assets/{asset.pk}/'))
        self.assertTrue(default_storage.exists(asset.file.name))

        # Visible again through the default (filtered) manager.
        restored = Joke.objects.get(pk=joke.pk)
        self.assertFalse(restored.is_removed)
        self.assertIsNone(restored.removed_at)

        # Serving again: media URLs present post-reverse.
        request = APIRequestFactory().get('/api/v1/jokes/')
        data = JokeSerializer(restored, context={'request': request}).data
        self.assertEqual(len(data['media']), 1)
        self.assertTrue(data['media'][0]['url'])

        notice = Notification.objects.get(recipient=self.creator, verb='appeal_resolved')
        self.assertEqual(notice.data['outcome'], 'reversed')
        self.assertEqual(notice.data['action_type'], 'takedown')

    def test_reverse_rejection_sets_draft_and_notifies(self):
        sub = JokeSubmission.objects.create(
            user=self.creator, format=self.fmt, age_rating=self.age, language=self.lang,
            text='Test submission', status='rejected', rejection_reason='duplicate',
        )
        appeal = Appeal.objects.create(
            user=self.creator, submission=sub, action_type='rejection',
            reason_text='please reconsider',
        )
        req = _admin_request(self.admin_user)
        self.appeal_admin.reverse_appeals(req, Appeal.objects.filter(pk=appeal.pk))

        appeal.refresh_from_db()
        self.assertEqual(appeal.status, 'reversed')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'draft')

        notice = Notification.objects.get(recipient=self.creator, verb='appeal_resolved')
        self.assertEqual(notice.data['outcome'], 'reversed')
        self.assertEqual(notice.data['action_type'], 'rejection')

    def test_reverse_skips_non_pending_appeal(self):
        joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.creator)
        appeal = Appeal.objects.create(
            user=self.creator, joke=joke, action_type='takedown',
            reason_text='x', status='upheld',
        )
        req = _admin_request(self.admin_user)
        self.appeal_admin.reverse_appeals(req, Appeal.objects.filter(pk=appeal.pk))
        appeal.refresh_from_db()
        self.assertEqual(appeal.status, 'upheld')
        self.assertFalse(
            Notification.objects.filter(recipient=self.creator, verb='appeal_resolved').exists()
        )


# =============================================================================
# Task 3: AppealAdmin display — hours_open SLA flag, overdue filter, ordering
# =============================================================================

class AppealAdminDisplayTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.creator = make_user('admin-display@example.com')
        self.admin_obj = AppealAdmin(Appeal, AdminSite())

    def test_hours_open_is_red_when_pending_over_36h(self):
        joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.creator)
        appeal = Appeal.objects.create(
            user=self.creator, joke=joke, action_type='takedown', reason_text='x',
        )
        Appeal.objects.filter(pk=appeal.pk).update(
            created_at=timezone.now() - timedelta(hours=40),
        )
        appeal.refresh_from_db()
        html = str(self.admin_obj.hours_open(appeal))
        self.assertIn('color:red', html)

    def test_hours_open_not_red_under_36h(self):
        joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.creator)
        appeal = Appeal.objects.create(
            user=self.creator, joke=joke, action_type='takedown', reason_text='x',
        )
        html = str(self.admin_obj.hours_open(appeal))
        self.assertNotIn('color:red', html)

    def test_overdue_filter_returns_only_lapsed_pending(self):
        old_joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.creator)
        recent_joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.creator)
        old = Appeal.objects.create(
            user=self.creator, joke=old_joke, action_type='takedown', reason_text='old',
        )
        Appeal.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(hours=40),
        )
        recent = Appeal.objects.create(
            user=self.creator, joke=recent_joke, action_type='takedown', reason_text='recent',
        )
        # SimpleListFilter expects QueryDict-style params: a list per key
        # (it indexes `value[-1]`), so a plain {'overdue': 'yes'} would
        # silently resolve to 's' (the last char of the string) instead.
        filt = OverdueAppealFilter(None, {'overdue': ['yes']}, Appeal, self.admin_obj)
        qs = filt.queryset(None, Appeal.objects.all())
        ids = set(qs.values_list('pk', flat=True))
        self.assertIn(old.pk, ids)
        self.assertNotIn(recent.pk, ids)

    def test_pending_first_ordering(self):
        joke_a = _removed_joke(self.fmt, self.age, self.lang, creator=self.creator)
        joke_b = _removed_joke(self.fmt, self.age, self.lang, creator=self.creator)
        resolved = Appeal.objects.create(
            user=self.creator, joke=joke_a, action_type='takedown',
            reason_text='r', status='upheld',
        )
        pending = Appeal.objects.create(
            user=self.creator, joke=joke_b, action_type='takedown', reason_text='p',
        )
        req = _admin_request(self.creator)
        qs = self.admin_obj.get_queryset(req)
        ids = list(qs.values_list('pk', flat=True))
        self.assertLess(ids.index(pending.pk), ids.index(resolved.pk))


# =============================================================================
# Task 3 review-fix: race-to-500 on the create() IntegrityError path
# =============================================================================

class AppealCreateRaceConditionTests(TestCase):
    """validate()'s duplicate check is check-then-act; the DB's partial
    unique index (uniq_pending_appeal_per_user_joke/_submission) is the real
    guard. Two concurrent same-user POSTs can both pass validate() before
    either commits — the second .create() must surface as a clean 400 with
    the same message validate() uses, never an uncaught 500."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('race-appeal@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_duplicate_caught_by_validate_is_400_with_message(self):
        joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.user)
        Appeal.objects.create(
            user=self.user, joke=joke, action_type='takedown', reason_text='first',
        )
        response = self.client.post(
            '/api/v1/appeals/', {'joke_id': joke.pk, 'reason_text': 'second'}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('already pending', str(response.data))

    def test_integrity_error_race_bypassing_validate_is_400_not_500(self):
        joke = _removed_joke(self.fmt, self.age, self.lang, creator=self.user)
        # The "winning" concurrent request's row, already committed.
        Appeal.objects.create(
            user=self.user, joke=joke, action_type='takedown', reason_text='racer',
        )
        # Simulate THIS request having evaluated validate()'s duplicate
        # pre-check before the winner landed (the actual race window): the
        # pre-check is the ONLY use of Appeal.objects.filter() reached during
        # this request, so patching it to report "no duplicate" reproduces
        # exactly that interleaving, leaving the DB's partial unique index
        # as the sole thing standing between this request and a 500.
        with patch('jokes.serializers.Appeal.objects.filter') as mock_filter:
            mock_filter.return_value.exists.return_value = False
            response = self.client.post(
                '/api/v1/appeals/',
                {'joke_id': joke.pk, 'reason_text': 'second'},
                format='json',
            )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('already pending', str(response.data))
        # The race loser never landed — still exactly one appeal for this joke.
        self.assertEqual(Appeal.objects.filter(joke=joke).count(), 1)


# =============================================================================
# Task 3 review-fix: null removed_at on a manually is_removed=True joke
# =============================================================================

class AppealCreateNullRemovedAtTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('null-removed-at@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_is_removed_true_but_removed_at_none_is_400_not_500(self):
        # A moderator can flip is_removed via the JokeAdmin change form
        # directly (removed_at stays null there — that path bypasses
        # take_down_joke entirely, so no takedown timestamp is ever set).
        joke = _make_joke(self.fmt, self.age, self.lang, creator=self.user, is_removed=True)
        self.assertIsNone(Joke.all_objects.get(pk=joke.pk).removed_at)
        response = self.client.post(
            '/api/v1/appeals/', {'joke_id': joke.pk, 'reason_text': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('not eligible for appeal', str(response.data))


# =============================================================================
# Whole-branch review fixes
# =============================================================================

def _take_down(admin_user, joke):
    report = ContentReport.objects.create(
        reporter=admin_user, joke=joke, reason='spam', status='pending',
    )
    ContentReportAdmin(ContentReport, AdminSite()).take_down_joke(
        _admin_request(admin_user), ContentReport.objects.filter(pk=report.pk),
    )


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class C1QuarantineUrlOwnerLeakTests(TestCase):
    """C1: the taken-down content's OWNER must never get a resolvable
    quarantine URL back — path-unguessability is the whole takedown model."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.owner = make_user('c1-owner@example.com')
        self.admin_user = make_user('c1-mod@example.com')

    def _published_then_removed_with_submission_link(self):
        """A media joke that was published (so the submission keeps its
        JokeSubmissionMedia link) and then taken down (asset quarantined)."""
        joke = make_image_joke(self.owner, setup='doomed')
        asset = joke.media.first().asset
        sub = _make_submission(self.owner, self.fmt, self.age, self.lang, status='published')
        sub.published_joke = joke
        sub.save(update_fields=['published_joke', 'status'])
        JokeSubmissionMedia.objects.create(submission=sub, asset=asset, position=0)
        _take_down(self.admin_user, joke)
        asset.refresh_from_db()
        self.assertIsNotNone(asset.quarantined_at)  # precondition
        return sub, asset

    def test_drafts_serializer_emits_dims_only_for_quarantined_asset(self):
        sub, asset = self._published_then_removed_with_submission_link()
        request = APIRequestFactory().get('/api/v1/jokes/my-drafts/')
        data = JokeSubmissionListSerializer(sub, context={'request': request}).data
        self.assertEqual(len(data['media']), 1)
        item = data['media'][0]
        # No resolvable URL for a quarantined asset.
        self.assertIsNone(item.get('url'))
        self.assertIsNone(item.get('poster_url'))
        # The quarantine path must not appear anywhere in the payload.
        self.assertNotIn('quarantine/', str(item))

    def test_drafts_list_endpoint_has_no_quarantine_url(self):
        sub, asset = self._published_then_removed_with_submission_link()
        client = APIClient()
        client.force_authenticate(self.owner)
        resp = client.get('/api/v1/jokes/my-drafts/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('quarantine/', resp.content.decode())

    def test_data_export_omits_url_for_quarantined_asset(self):
        joke = make_image_joke(self.owner)
        asset = joke.media.first().asset
        _take_down(self.admin_user, joke)
        asset.refresh_from_db()
        self.assertIsNotNone(asset.quarantined_at)
        client = APIClient()
        client.force_authenticate(self.owner)
        resp = client.get('/api/v1/users/me/data-export/')
        self.assertEqual(resp.status_code, 200)
        import io, json, zipfile
        payload = json.loads(
            zipfile.ZipFile(io.BytesIO(resp.content)).read('jokes-for-data-export.json')
        )
        rows = [r for r in payload['media_assets'] if r['id'] == str(asset.pk)]
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['url'])
        self.assertEqual(rows[0].get('status'), 'quarantined')
        self.assertNotIn('quarantine/', json.dumps(payload))


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class C2RestoreVsLapseSweepTests(TestCase):
    """C2: restoring a taken-down joke must release its quarantined assets,
    and the lapse sweep must never purge media of a LIVE joke."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.owner = make_user('c2-owner@example.com')
        self.admin_user = make_user('c2-mod@example.com')

    def _quarantined_joke(self):
        joke = make_image_joke(self.owner)
        _take_down(self.admin_user, joke)
        asset = joke.media.first().asset
        asset.refresh_from_db()
        self.assertIsNotNone(asset.quarantined_at)
        return joke, asset

    def test_restore_jokes_releases_quarantined_assets(self):
        joke, asset = self._quarantined_joke()
        JokeAdmin(Joke, AdminSite()).restore_jokes(
            _admin_request(self.admin_user),
            Joke.all_objects.filter(pk=joke.pk),
        )
        joke.refresh_from_db()
        asset.refresh_from_db()
        self.assertFalse(joke.is_removed)
        # Asset released back to a serving path, stamp cleared.
        self.assertIsNone(asset.quarantined_at)
        self.assertTrue(asset.file.name.startswith(f'media-assets/{asset.pk}/'))
        self.assertTrue(default_storage.exists(asset.file.name))

    def test_lapse_sweep_never_purges_live_joke_media(self):
        # Quarantine at T; restore (joke live again, asset released); then a
        # 15-day-later sweep must NOT purge it. Belt: even without release,
        # the live-joke guard alone protects it.
        joke = make_image_joke(self.owner)
        with freeze_time('2026-07-01 12:00:00'):
            _take_down(self.admin_user, joke)
        asset = joke.media.first().asset
        JokeAdmin(Joke, AdminSite()).restore_jokes(
            _admin_request(self.admin_user), Joke.all_objects.filter(pk=joke.pk),
        )
        with freeze_time('2026-07-16 12:00:01'):
            purge_lapsed_quarantine()
        self.assertTrue(MediaAsset.objects.filter(pk=asset.pk).exists())
        asset.refresh_from_db()  # released → name now points at media-assets/
        self.assertTrue(default_storage.exists(asset.file.name))

    def test_lapse_sweep_live_link_guard_without_release(self):
        # Directly exercise the guard: an asset still quarantined but linked
        # to a live joke must be skipped even though 15d elapsed and no appeal.
        joke = make_image_joke(self.owner)
        asset = joke.media.first().asset
        with freeze_time('2026-07-01 12:00:00'):
            asset.quarantine()
        # Joke stays live (is_removed=False) — the guard must protect it.
        with freeze_time('2026-07-16 12:00:01'):
            purge_lapsed_quarantine()
        self.assertTrue(MediaAsset.objects.filter(pk=asset.pk).exists())

    def test_lapse_sweep_still_purges_removed_joke_media(self):
        # Control: no restore, joke stays removed, no appeal → purged at 15d.
        joke, asset = self._quarantined_joke()
        with freeze_time('2026-07-16 12:00:01'):
            # quarantine happened 'now' in setUp (real time); re-quarantine
            # under a frozen past so it's genuinely lapsed.
            pass
        # Re-stamp the quarantine time to 15 days before the sweep.
        MediaAsset.objects.filter(pk=asset.pk).update(
            quarantined_at=timezone.now() - timedelta(days=15),
        )
        purge_lapsed_quarantine()
        self.assertFalse(MediaAsset.objects.filter(pk=asset.pk).exists())


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class I1RemovedJokeGateTests(TestCase):
    """I1: four more surfaces must drop removed jokes (text + share_image +
    media leak): collection jokes, recently-viewed, daily today/history,
    data-export saved/favorites."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.creator = make_user('i1-creator@example.com')
        self.admin_user = make_user('i1-mod@example.com')
        self.viewer = make_user('i1-viewer@example.com')
        self.live = make_image_joke(self.creator, setup='live one')
        self.removed = make_image_joke(self.creator, setup='doomed one')

    def _client(self):
        c = APIClient()
        c.force_authenticate(self.viewer)
        return c

    def test_collection_jokes_excludes_removed(self):
        col = Collection.objects.create(user=self.viewer, name='c', is_default=True)
        SavedJoke.objects.create(user=self.viewer, joke=self.live, collection=col)
        SavedJoke.objects.create(user=self.viewer, joke=self.removed, collection=col)
        _take_down(self.admin_user, self.removed)
        resp = self._client().get(f'/api/v1/collections/{col.id}/jokes/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data.get('results', data)
        ids = {r['joke']['id'] for r in results}
        self.assertIn(self.live.pk, ids)
        self.assertNotIn(self.removed.pk, ids)

    def test_recently_viewed_excludes_removed(self):
        JokeView.objects.create(user=self.viewer, joke=self.live, source='explore')
        JokeView.objects.create(user=self.viewer, joke=self.removed, source='explore')
        _take_down(self.admin_user, self.removed)
        resp = self._client().get('/api/v1/users/me/recently-viewed/')
        self.assertEqual(resp.status_code, 200)
        ids = {r['joke']['id'] for r in resp.json()}
        self.assertIn(self.live.pk, ids)
        self.assertNotIn(self.removed.pk, ids)

    def test_daily_today_regenerates_when_stored_joke_removed(self):
        # A DailyJoke row exists for the viewer pointing at a joke that then
        # gets removed. today/ must NOT serve the removed joke.
        DailyJoke.objects.create(
            user=self.viewer, joke=self.removed, date=timezone.now().date(),
        )
        _take_down(self.admin_user, self.removed)
        resp = self._client().get('/api/v1/daily-jokes/today/')
        # Either regenerated to a live joke, or 404 if none available — never
        # the removed joke.
        if resp.status_code == 200:
            self.assertNotEqual(resp.json()['joke']['id'], self.removed.pk)
        else:
            self.assertEqual(resp.status_code, 404)

    def test_daily_history_excludes_removed(self):
        DailyJoke.objects.create(
            user=self.viewer, joke=self.live, date=timezone.now().date(),
        )
        DailyJoke.objects.create(
            user=self.viewer, joke=self.removed,
            date=timezone.now().date() - timedelta(days=1),
        )
        _take_down(self.admin_user, self.removed)
        resp = self._client().get('/api/v1/daily-jokes/history/')
        self.assertEqual(resp.status_code, 200)
        ids = {r['joke']['id'] for r in resp.json()}
        self.assertIn(self.live.pk, ids)
        self.assertNotIn(self.removed.pk, ids)

    def test_data_export_excludes_removed_joke_text(self):
        # Viewer saved + favorited a joke that later gets removed — export
        # must not leak that other-user joke's text back to the viewer.
        SavedJoke.objects.create(user=self.viewer, joke=self.removed)
        Favorite.objects.create(user=self.viewer, joke=self.removed)
        SavedJoke.objects.create(user=self.viewer, joke=self.live)
        _take_down(self.admin_user, self.removed)
        client = APIClient()
        client.force_authenticate(self.viewer)
        resp = client.get('/api/v1/users/me/data-export/')
        self.assertEqual(resp.status_code, 200)
        import io, json, zipfile
        payload = json.loads(
            zipfile.ZipFile(io.BytesIO(resp.content)).read('jokes-for-data-export.json')
        )
        saved_ids = {r['joke_id'] for r in payload['saved_jokes']}
        fav_ids = {r['joke_id'] for r in payload['favorites']}
        self.assertIn(self.live.pk, saved_ids)
        self.assertNotIn(self.removed.pk, saved_ids)
        self.assertNotIn(self.removed.pk, fav_ids)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class I2UpholdSiblingAppealGuardTests(TestCase):
    """I2: upholding appeal A must not purge an asset that a co-taken-down
    joke B (also under a pending appeal) needs to be restorable."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.owner = make_user('i2-owner@example.com')
        self.admin_user = make_user('i2-mod@example.com')

    def test_uphold_a_spares_asset_shared_with_pending_appeal_joke_b(self):
        joke_a = make_image_joke(self.owner)
        joke_b = make_image_joke(self.owner)
        shared = make_asset(self.owner)
        # Both jokes link the shared asset (plus their own from make_image_joke).
        JokeMedia.objects.create(joke=joke_a, asset=shared, position=1)
        JokeMedia.objects.create(joke=joke_b, asset=shared, position=1)
        # Take both down together so the shared asset is quarantined once.
        report_a = ContentReport.objects.create(
            reporter=self.admin_user, joke=joke_a, reason='spam', status='pending',
        )
        report_b = ContentReport.objects.create(
            reporter=self.admin_user, joke=joke_b, reason='spam', status='pending',
        )
        ContentReportAdmin(ContentReport, AdminSite()).take_down_joke(
            _admin_request(self.admin_user),
            ContentReport.objects.filter(pk__in=[report_a.pk, report_b.pk]),
        )
        shared.refresh_from_db()
        self.assertIsNotNone(shared.quarantined_at)
        # Both jokes get a pending appeal.
        appeal_a = Appeal.objects.create(
            user=self.owner, joke=joke_a, action_type='takedown', reason_text='a',
        )
        Appeal.objects.create(
            user=self.owner, joke=joke_b, action_type='takedown', reason_text='b',
        )
        # Uphold only A — must NOT purge the shared asset (B still pending).
        AppealAdmin(Appeal, AdminSite()).uphold_appeals(
            _admin_request(self.admin_user), Appeal.objects.filter(pk=appeal_a.pk),
        )
        self.assertTrue(
            MediaAsset.objects.filter(pk=shared.pk).exists(),
            'shared asset was purged despite joke B having a pending appeal',
        )
