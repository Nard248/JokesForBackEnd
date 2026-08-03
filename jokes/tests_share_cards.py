"""Tests for Share-Cards-Wave Task 1: media-card generator + dispatch.

Deliberately does NOT patch Joke._generate_share_image / cairosvg — card
generation is the code under test here (unlike jokes/tests_media.py, which
stubs it out because it's irrelevant to what those tests cover). Requires a
working libcairo (see run notes in the task report).

Task 2 tests (below): regeneration triggers -- the ordering trap
(approve_and_publish), the takedown leak (take_down_joke blanking
share_image), reversal regeneration (reverse_appeals / restore_jokes), the
audio badge, and the fail-open guard on a corrupt raster. Also real
generation throughout -- these exercise the actual admin actions end to end.
"""
import io
import shutil
import tempfile
from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models.fields.files import FieldFile
from django.test import RequestFactory, TestCase, override_settings
from PIL import Image
from rest_framework.test import APIRequestFactory

from inbox.models import Notification
from jokes.admin import AppealAdmin, ContentReportAdmin, JokeAdmin, JokeSubmissionAdmin
from jokes.models import (
    Appeal, ContentReport, Format, Joke, JokeMedia, JokeSubmission,
    JokeSubmissionMedia, MediaAsset, Tone,
)
from jokes.serializers import JokeListSerializer, JokeSerializer
from jokes.share_cards import (
    _downscale_raster, generate_share_card_png, get_badge_text, media_share_card_png,
)
from jokes.tests_media import _taxonomy, make_user

_MEDIA_ROOT = tempfile.mkdtemp()


def _real_raster_bytes(width=1200, height=900, fmt='JPEG', mode='RGB', color=(120, 40, 200)):
    """A real, Pillow-decodable raster (unlike tests_media.make_asset's
    placeholder `b'fake-webp-bytes'`, which _downscale_raster cannot open)."""
    img = Image.new(mode, (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def make_image_asset(owner, width=1200, height=900):
    """A MediaAsset(kind='image') whose .file is a real, decodable raster."""
    asset = MediaAsset(owner=owner, kind='image', width=width, height=height)
    asset.file.save(
        'image.webp', ContentFile(_real_raster_bytes(width, height)), save=False,
    )
    asset.save()
    return asset


def make_video_asset(owner, poster_width=1280, poster_height=720, is_gif=False, with_poster=True):
    """A MediaAsset(kind='video'); .file is a FAKE mp4 (never meant to be
    read for the share card — reading it is a test failure), .poster is a
    real, decodable JPEG (the SafeSearch-screened teaser frame)."""
    asset = MediaAsset(
        owner=owner, kind='video', width=poster_width, height=poster_height,
        is_gif=is_gif, duration_ms=4000,
    )
    asset.file.save('clip.mp4', ContentFile(b'not-a-real-mp4-do-not-read-me'), save=False)
    if with_poster:
        asset.poster.save(
            'poster.jpg',
            ContentFile(_real_raster_bytes(poster_width, poster_height)),
            save=False,
        )
    asset.save()
    return asset


def make_audio_asset(owner):
    asset = MediaAsset(owner=owner, kind='audio')
    asset.file.save('clip.mp3', ContentFile(b'fake-mp3-bytes'), save=False)
    asset.save()
    return asset


def make_joke(user, format_slug, text='caption text', **extra):
    fmt, _ = Format.objects.get_or_create(
        slug=format_slug, defaults={'name': format_slug.title()},
    )
    _, age, lang = _taxonomy()
    return Joke.objects.create(
        text=text, setup=text, format=fmt, age_rating=age, language=lang,
        creator=user, **extra,
    )


def _assert_valid_png_1200x630(test, buf):
    buf.seek(0)
    img = Image.open(buf)
    test.assertEqual(img.format, 'PNG')
    test.assertEqual(img.size, (1200, 630))
    buf.seek(0)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class MediaCardDispatchTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = make_user('sharecard@example.com')

    def test_image_joke_gets_media_card_that_differs_from_text_card(self):
        media_joke = make_joke(self.user, 'image', text='a captioned photo')
        JokeMedia.objects.create(
            joke=media_joke, asset=make_image_asset(self.user), position=0,
        )
        text_joke = make_joke(self.user, 'oneliner', text='a captioned photo')

        media_buf = generate_share_card_png(media_joke)
        text_buf = generate_share_card_png(text_joke)

        _assert_valid_png_1200x630(self, media_buf)
        self.assertNotEqual(media_buf.getvalue(), text_buf.getvalue())

    def test_video_joke_uses_poster_and_never_reads_the_video_file(self):
        video_asset = make_video_asset(self.user)
        video_file_name = video_asset.file.name
        media_joke = make_joke(self.user, 'video', text='watch this')
        JokeMedia.objects.create(joke=media_joke, asset=video_asset, position=0)
        text_joke = make_joke(self.user, 'oneliner', text='watch this')

        original_open = FieldFile.open

        def guarded_open(self, mode='rb'):
            if self.name == video_file_name:
                raise AssertionError(
                    'the raw video file must NEVER be read for the share '
                    'card — only the SafeSearch-screened poster frame.'
                )
            return original_open(self, mode)

        with mock.patch.object(FieldFile, 'open', guarded_open):
            media_buf = generate_share_card_png(media_joke)
        text_buf = generate_share_card_png(text_joke)

        _assert_valid_png_1200x630(self, media_buf)
        self.assertNotEqual(media_buf.getvalue(), text_buf.getvalue())

    def test_video_joke_without_poster_falls_back_to_text_card(self):
        # Poster not generated yet (still processing) -> no usable raster.
        video_asset = make_video_asset(self.user, with_poster=False)
        media_joke = make_joke(self.user, 'video', text='watch this')
        JokeMedia.objects.create(joke=media_joke, asset=video_asset, position=0)

        self.assertIsNone(media_share_card_png(media_joke))
        buf = generate_share_card_png(media_joke)
        _assert_valid_png_1200x630(self, buf)

    def test_audio_joke_returns_the_text_card(self):
        audio_asset = make_audio_asset(self.user)
        joke = make_joke(self.user, 'audio', text='listen to this')
        JokeMedia.objects.create(joke=joke, asset=audio_asset, position=0)

        # media_share_card_png must decline (no visual for audio).
        self.assertIsNone(media_share_card_png(joke))

        buf = generate_share_card_png(joke)
        _assert_valid_png_1200x630(self, buf)

    def test_text_joke_dispatch_is_unchanged(self):
        """Pin: a plain text joke (no media at all) must take the EXISTING
        text-card path, untouched by the new dispatch. cairosvg output isn't
        guaranteed byte-stable across environments/runs, so we pin on: valid
        1200x630 PNG, non-empty, and proof the media branch was never taken."""
        joke = make_joke(self.user, 'oneliner', text='why did the chicken cross the road')

        self.assertIsNone(media_share_card_png(joke))

        buf = generate_share_card_png(joke)
        _assert_valid_png_1200x630(self, buf)
        self.assertGreater(len(buf.getvalue()), 0)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class DownscaleRasterTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def test_large_raster_is_downscaled_to_1200_wide_valid_jpeg(self):
        raw = _real_raster_bytes(width=3000, height=2000, fmt='PNG')
        out = _downscale_raster(raw)
        img = Image.open(io.BytesIO(out))
        self.assertEqual(img.format, 'JPEG')
        self.assertLessEqual(img.width, 1200)

    def test_small_raster_is_not_upscaled(self):
        raw = _real_raster_bytes(width=400, height=300, fmt='JPEG')
        out = _downscale_raster(raw)
        img = Image.open(io.BytesIO(out))
        self.assertEqual(img.format, 'JPEG')
        self.assertEqual(img.size, (400, 300))

    def test_rgba_input_is_converted_to_rgb_jpeg(self):
        raw = _real_raster_bytes(width=800, height=600, fmt='PNG', mode='RGBA', color=(10, 20, 30, 128))
        out = _downscale_raster(raw)
        img = Image.open(io.BytesIO(out))
        self.assertEqual(img.format, 'JPEG')
        self.assertEqual(img.mode, 'RGB')


# =============================================================================
# Task 2: regeneration triggers -- ordering trap, takedown leak, reversal,
# audio badge, fail-open.
# =============================================================================

def _admin_request(user):
    req = RequestFactory().post('/')
    req.user = user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class OrderingTrapRegenerationTests(TestCase):
    """approve_and_publish creates the Joke (firing save() -> a text-only
    card, since JokeMedia doesn't exist yet) and only copies JokeMedia
    afterward. Without an explicit rebuild, a published media joke would be
    stuck with the text-only card forever (text never changes post-publish)."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = make_user('ordering-trap@example.com')
        self.mod = make_user('ordering-trap-mod@example.com')
        self.fmt, self.age, self.lang = _taxonomy()

    def _publish_media_submission(self, caption='a captioned photo'):
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt, age_rating=self.age, language=self.lang,
            setup=caption, text=caption, status='pending',
        )
        JokeSubmissionMedia.objects.create(
            submission=sub, asset=make_image_asset(self.user), position=0,
        )
        JokeSubmissionAdmin(JokeSubmission, AdminSite()).approve_and_publish(
            _admin_request(self.mod), JokeSubmission.objects.filter(pk=sub.pk),
        )
        sub.refresh_from_db()
        return sub.published_joke

    def test_published_media_joke_gets_media_card_not_text_card(self):
        caption = 'a captioned photo'
        joke = self._publish_media_submission(caption)
        self.assertIsNotNone(joke)

        # What the ordering-trap bug would have produced: the text-only card
        # for the same caption.
        text_joke = make_joke(self.user, 'oneliner', text=caption)
        text_card_bytes = generate_share_card_png(text_joke).getvalue()

        joke.refresh_from_db()
        self.assertTrue(joke.share_image)
        with joke.share_image.open('rb') as fh:
            published_bytes = fh.read()

        _assert_valid_png_1200x630(self, io.BytesIO(published_bytes))
        self.assertNotEqual(
            published_bytes, text_card_bytes,
            'published media joke got the text-only card -- the ordering trap regressed',
        )


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class TakedownShareImageLeakTests(TestCase):
    """The share card is a SEPARATELY generated PNG embedding a downscaled
    copy of the poster/image at a guessable share-cards/joke-<pk>.png path.
    take_down_joke must blank it, or the OG crawler (and anyone hitting the
    URL directly) keeps serving a removed joke's poster."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = make_user('takedown-share@example.com')
        self.mod = make_user('takedown-share-mod@example.com')
        self.fmt, self.age, self.lang = _taxonomy()

    def _publish_media_joke(self, caption='a takedown-bound photo'):
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt, age_rating=self.age, language=self.lang,
            setup=caption, text=caption, status='pending',
        )
        JokeSubmissionMedia.objects.create(
            submission=sub, asset=make_image_asset(self.user), position=0,
        )
        JokeSubmissionAdmin(JokeSubmission, AdminSite()).approve_and_publish(
            _admin_request(self.mod), JokeSubmission.objects.filter(pk=sub.pk),
        )
        sub.refresh_from_db()
        return sub.published_joke

    def _take_down(self, joke):
        report = ContentReport.objects.create(reporter=self.mod, joke=joke, reason='spam')
        ContentReportAdmin(ContentReport, AdminSite()).take_down_joke(
            _admin_request(self.mod), ContentReport.objects.filter(pk=report.pk),
        )

    def test_takedown_blanks_field_and_deletes_stored_file(self):
        joke = self._publish_media_joke()
        old_name = joke.share_image.name
        self.assertTrue(old_name)
        self.assertTrue(default_storage.exists(old_name))

        self._take_down(joke)

        removed = Joke.all_objects.get(pk=joke.pk)
        self.assertTrue(removed.is_removed)
        self.assertFalse(removed.share_image)
        self.assertFalse(default_storage.exists(old_name))

    def test_partial_share_image_delete_failure_continues_batch_and_warns(self):
        """One joke's share_image.delete() blowing up (transient GCS
        auth/quota/network) must not abort the takedown batch: the OTHER
        joke still gets taken down and its card blanked, and the admin sees
        a WARNING naming the failed joke. Mirrors
        test_partial_quarantine_failure_continues_batch_and_warns."""
        good = self._publish_media_joke(caption='good joke survives the batch')
        bad = self._publish_media_joke(caption='bad joke fails to delete')
        good_old_name = good.share_image.name
        bad_old_name = bad.share_image.name
        self.assertTrue(good_old_name)
        self.assertTrue(bad_old_name)

        report_good = ContentReport.objects.create(reporter=self.mod, joke=good, reason='spam')
        report_bad = ContentReport.objects.create(reporter=self.mod, joke=bad, reason='spam')

        real_delete = FieldFile.delete

        def flaky_delete(self, save=True):
            if self.instance.pk == bad.pk:
                raise RuntimeError('gcs delete failed')
            return real_delete(self, save=save)

        req = _admin_request(self.mod)
        with mock.patch.object(FieldFile, 'delete', flaky_delete):
            ContentReportAdmin(ContentReport, AdminSite()).take_down_joke(
                req, ContentReport.objects.filter(pk__in=[report_good.pk, report_bad.pk]),
            )

        # Batch not aborted -- both jokes still taken down.
        good_removed = Joke.all_objects.get(pk=good.pk)
        bad_removed = Joke.all_objects.get(pk=bad.pk)
        self.assertTrue(good_removed.is_removed)
        self.assertTrue(bad_removed.is_removed)

        # good: delete succeeded -- field cleared AND file gone.
        self.assertFalse(good_removed.share_image)
        self.assertFalse(default_storage.exists(good_old_name))

        # bad: delete failed -- field left pointing at a file that may
        # still exist (the delete raised before removing it) rather than a
        # cleared field pointing at nothing (the safe, consistent state).
        self.assertEqual(bad_removed.share_image.name, bad_old_name)
        self.assertTrue(default_storage.exists(bad_old_name))

        msgs = [str(m) for m in req._messages]
        self.assertTrue(
            any('share-card delete' in m.lower() and str(bad.pk) in m for m in msgs),
            f'expected a warning naming joke {bad.pk}, got: {msgs}',
        )


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class RemovedJokeSaveGuardTests(TestCase):
    """CRITICAL: a removed joke's blanked share card must never come back
    via Joke.save(). Pre-fix, save()'s `if not regenerate and not
    self.share_image: regenerate = True` branch fires for ANY removed joke
    (its card was blanked at takedown) -- a moderator opening the removed
    joke in the JokeAdmin change form (get_queryset=all_objects, editable
    fieldsets) and hitting Save runs _generate_share_image(), which reads
    the QUARANTINED asset (storage reads still work -- quarantine only
    moves the file within the bucket) and writes share-cards/joke-<pk>.png
    straight back to PUBLIC storage (GCS file_overwrite=True reclaims the
    exact cached URL). The follow-up Joke.objects.filter(pk=).update() then
    matches 0 rows (default manager hides removed jokes), so the DB field
    stays blank and NOTHING warns -- an invisible file-level leak.

    IMPORTANT: the takedown-by-change-form path -- flipping is_removed via
    a direct save() rather than ContentReportAdmin.take_down_joke -- must
    ALSO blank the card, or that path leaves it serving."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = make_user('save-guard@example.com')
        self.mod = make_user('save-guard-mod@example.com')
        self.fmt, self.age, self.lang = _taxonomy()

    def _publish_media_joke(self, caption='a save-guard photo'):
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt, age_rating=self.age, language=self.lang,
            setup=caption, text=caption, status='pending',
        )
        JokeSubmissionMedia.objects.create(
            submission=sub, asset=make_image_asset(self.user), position=0,
        )
        JokeSubmissionAdmin(JokeSubmission, AdminSite()).approve_and_publish(
            _admin_request(self.mod), JokeSubmission.objects.filter(pk=sub.pk),
        )
        sub.refresh_from_db()
        return sub.published_joke

    def _take_down(self, joke):
        report = ContentReport.objects.create(reporter=self.mod, joke=joke, reason='spam')
        ContentReportAdmin(ContentReport, AdminSite()).take_down_joke(
            _admin_request(self.mod), ContentReport.objects.filter(pk=report.pk),
        )

    def _share_card_files(self):
        try:
            _, files = default_storage.listdir('share-cards')
        except FileNotFoundError:
            return set()
        return set(files)

    def test_removed_joke_save_does_not_regenerate_card(self):
        """The headline regression, at the storage level: take_down_joke
        blanks the card; a change-form Save on the still-removed joke must
        not (re)create a share-card file anywhere."""
        joke = self._publish_media_joke()
        self._take_down(joke)
        removed = Joke.all_objects.get(pk=joke.pk)
        self.assertTrue(removed.is_removed)
        self.assertFalse(removed.share_image)
        before_files = self._share_card_files()

        removed.save()  # simulates the JokeAdmin change-form Save button

        after_files = self._share_card_files()
        self.assertEqual(
            after_files, before_files,
            'save() (re)created a share-card file for a removed joke',
        )
        removed.refresh_from_db()
        self.assertFalse(removed.share_image)

    def test_removed_joke_save_does_not_call_generate(self):
        """Precise unit-level pin on the guard itself, independent of
        storage-backend quirks (local FileSystemStorage's non-overwriting
        get_available_name could otherwise mask the regression above under
        some file-naming coincidences)."""
        joke = self._publish_media_joke()
        self._take_down(joke)
        removed = Joke.all_objects.get(pk=joke.pk)

        with mock.patch('jokes.models.Joke._generate_share_image') as mock_generate:
            removed.save()
        mock_generate.assert_not_called()

    def test_live_joke_save_still_regenerates_on_text_change(self):
        """Regression: the is_removed guard must not neuter regeneration
        for ordinary live jokes."""
        joke = make_joke(self.user, 'oneliner', text='still alive and well')
        old_name = joke.share_image.name
        self.assertTrue(old_name)

        joke.text = 'still alive and well, edited'
        joke.save()

        joke.refresh_from_db()
        self.assertTrue(joke.share_image)

    def test_direct_is_removed_transition_blanks_and_deletes_card(self):
        """The takedown-by-change-form path: flipping is_removed True via a
        direct save() (not going through
        ContentReportAdmin.take_down_joke) must ALSO blank the card."""
        joke = self._publish_media_joke()
        old_name = joke.share_image.name
        self.assertTrue(old_name)
        self.assertTrue(default_storage.exists(old_name))

        joke.is_removed = True
        joke.save()

        self.assertFalse(default_storage.exists(old_name))
        joke.refresh_from_db()
        self.assertFalse(joke.share_image)
        self.assertTrue(joke.is_removed)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class ReversalRegenerationTests(TestCase):
    """On appeal reversal (and on the JokeAdmin restore_jokes action), the
    share card must come back -- a media card if media is present."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = make_user('reversal-share@example.com')
        self.mod = make_user('reversal-share-mod@example.com')
        self.fmt, self.age, self.lang = _taxonomy()
        self.caption = 'a reversal-bound photo'

    def _publish_media_joke(self):
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt, age_rating=self.age, language=self.lang,
            setup=self.caption, text=self.caption, status='pending',
        )
        JokeSubmissionMedia.objects.create(
            submission=sub, asset=make_image_asset(self.user), position=0,
        )
        JokeSubmissionAdmin(JokeSubmission, AdminSite()).approve_and_publish(
            _admin_request(self.mod), JokeSubmission.objects.filter(pk=sub.pk),
        )
        sub.refresh_from_db()
        return sub.published_joke

    def _take_down(self, joke):
        report = ContentReport.objects.create(reporter=self.mod, joke=joke, reason='spam')
        ContentReportAdmin(ContentReport, AdminSite()).take_down_joke(
            _admin_request(self.mod), ContentReport.objects.filter(pk=report.pk),
        )

    def _assert_media_card_restored(self, restored_joke):
        text_joke = make_joke(self.user, 'oneliner', text=self.caption)
        text_card_bytes = generate_share_card_png(text_joke).getvalue()
        self.assertTrue(restored_joke.share_image)
        with restored_joke.share_image.open('rb') as fh:
            restored_bytes = fh.read()
        _assert_valid_png_1200x630(self, io.BytesIO(restored_bytes))
        self.assertNotEqual(restored_bytes, text_card_bytes)

    def test_reverse_appeals_regenerates_media_card(self):
        joke = self._publish_media_joke()
        self._take_down(joke)
        removed = Joke.all_objects.get(pk=joke.pk)
        self.assertFalse(removed.share_image)  # blanked at takedown

        appeal = Appeal.objects.create(
            user=self.user, joke=removed, action_type='takedown',
            reason_text='please review',
        )
        AppealAdmin(Appeal, AdminSite()).reverse_appeals(
            _admin_request(self.mod), Appeal.objects.filter(pk=appeal.pk),
        )

        appeal.refresh_from_db()
        self.assertEqual(appeal.status, 'reversed')
        restored = Joke.objects.get(pk=joke.pk)
        self.assertFalse(restored.is_removed)
        self._assert_media_card_restored(restored)

    def test_restore_jokes_admin_action_regenerates_media_card(self):
        joke = self._publish_media_joke()
        self._take_down(joke)
        removed = Joke.all_objects.get(pk=joke.pk)
        self.assertFalse(removed.share_image)  # blanked at takedown

        JokeAdmin(Joke, AdminSite()).restore_jokes(
            _admin_request(self.mod), Joke.all_objects.filter(pk=joke.pk),
        )

        restored = Joke.objects.get(pk=joke.pk)
        self.assertFalse(restored.is_removed)
        self._assert_media_card_restored(restored)

    def test_reverse_appeals_regen_failure_still_resolves_appeal_and_warns(self):
        """IMPORTANT: reverse_appeals' card regen must be isolated -- the
        joke is ALREADY live again by the time regen runs, so a regen blip
        must not abort status=reversed/notify/audit for the rest of this
        appeal's resolution (asymmetric otherwise with restore_jokes, which
        already isolates its own regen loop)."""
        joke = self._publish_media_joke()
        self._take_down(joke)
        removed = Joke.all_objects.get(pk=joke.pk)

        appeal = Appeal.objects.create(
            user=self.user, joke=removed, action_type='takedown',
            reason_text='please review',
        )
        req = _admin_request(self.mod)
        with mock.patch.object(
            Joke, 'regenerate_share_image', side_effect=RuntimeError('cairo blew up'),
        ):
            AppealAdmin(Appeal, AdminSite()).reverse_appeals(
                req, Appeal.objects.filter(pk=appeal.pk),
            )

        appeal.refresh_from_db()
        self.assertEqual(appeal.status, 'reversed')
        restored = Joke.objects.get(pk=joke.pk)
        self.assertFalse(restored.is_removed)

        notice = Notification.objects.get(recipient=self.user, verb='appeal_resolved')
        self.assertEqual(notice.data['outcome'], 'reversed')

        msgs = [str(m) for m in req._messages]
        self.assertTrue(
            any(
                'share-card regeneration' in m.lower() and str(joke.pk) in m
                for m in msgs
            ),
            f'expected a warning naming joke {joke.pk}, got: {msgs}',
        )

    def test_restore_jokes_regen_failure_does_not_abort_restore_and_warns(self):
        """Symmetric forced-failure coverage for restore_jokes' regen
        loop (already isolated per-item; this pins it with an actual
        induced failure rather than only the happy path)."""
        joke = self._publish_media_joke()
        self._take_down(joke)

        req = _admin_request(self.mod)
        with mock.patch.object(
            Joke, 'regenerate_share_image', side_effect=RuntimeError('cairo blew up'),
        ):
            JokeAdmin(Joke, AdminSite()).restore_jokes(
                req, Joke.all_objects.filter(pk=joke.pk),
            )

        restored = Joke.objects.get(pk=joke.pk)
        self.assertFalse(restored.is_removed)

        msgs = [str(m) for m in req._messages]
        self.assertTrue(
            any(
                'share-card regeneration failed' in m.lower() and str(joke.pk) in m
                for m in msgs
            ),
            f'expected a warning naming joke {joke.pk}, got: {msgs}',
        )


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class RemovedJokeShareImageUrlGuardTests(TestCase):
    """IMPORTANT #5: defense-in-depth in get_share_image_url. Simulates the
    partial-takedown-failure state directly (is_removed=True with
    share_image STILL populated -- exactly what a failed
    share_image.delete() in take_down_joke leaves behind) to prove the
    serializer guard does real work, not just trivially return None because
    the field happens to already be blank."""

    def setUp(self):
        self.user = make_user('share-url-guard@example.com')
        joke = make_joke(self.user, 'oneliner', text='removed but card field still set')
        # Bypass save()'s own takedown-blanking guard on purpose (a
        # queryset .update() has no model save side effects) so the field
        # stays populated on a removed joke -- the partial-failure state.
        Joke.all_objects.filter(pk=joke.pk).update(
            is_removed=True, share_image='share-cards/joke-leaked.png',
        )
        self.joke = Joke.all_objects.get(pk=joke.pk)
        self.request = APIRequestFactory().get('/api/v1/jokes/')

    def test_detail_serializer_share_image_url_is_none_for_removed_joke(self):
        data = JokeSerializer(self.joke, context={'request': self.request}).data
        self.assertIsNone(data['share_image_url'])

    def test_list_serializer_share_image_url_is_none_for_removed_joke(self):
        data = JokeListSerializer(self.joke, context={'request': self.request}).data
        self.assertIsNone(data['share_image_url'])


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class AudioBadgeTests(TestCase):
    """Audio jokes have no visual to embed (media_share_card_png declines),
    so they render via the text-card path -- but with the tone badge
    REPLACED by an 'Audio' badge."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = make_user('audio-badge@example.com')

    def test_audio_joke_gets_audio_badge_even_with_a_tone_set(self):
        joke = make_joke(self.user, 'audio', text='knock knock, who is there')
        JokeMedia.objects.create(joke=joke, asset=make_audio_asset(self.user), position=0)
        tone, _ = Tone.objects.get_or_create(
            slug='dad-jokes', defaults={'name': 'Dad Jokes'},
        )
        joke.tones.add(tone)

        # The tone badge would otherwise win -- Audio must replace it.
        self.assertEqual(get_badge_text(joke), 'Audio')

        # media_share_card_png must still decline (no visual for audio).
        self.assertIsNone(media_share_card_png(joke))

        buf = generate_share_card_png(joke)
        _assert_valid_png_1200x630(self, buf)

    def test_non_audio_joke_badge_is_unaffected(self):
        joke = make_joke(self.user, 'oneliner', text='why did the chicken cross the road')
        tone, _ = Tone.objects.get_or_create(
            slug='puns', defaults={'name': 'Puns'},
        )
        joke.tones.add(tone)
        self.assertEqual(get_badge_text(joke), 'Puns')


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class MediaCardFailOpenTests(TestCase):
    """A corrupt/unreadable raster must never propagate out of
    media_share_card_png -- it must fail open to the text card, exactly
    like the SafeSearch fail-open precedent (commit 77e995a)."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = make_user('failopen@example.com')

    def _corrupt_image_asset(self):
        asset = MediaAsset(owner=self.user, kind='image')
        asset.file.save(
            'image.webp', ContentFile(b'not a real image, corrupt bytes'), save=False,
        )
        asset.save()
        return asset

    def test_corrupt_raster_returns_none_and_falls_back_to_text_card(self):
        joke = make_joke(self.user, 'image', text='corrupt raster joke')
        JokeMedia.objects.create(joke=joke, asset=self._corrupt_image_asset(), position=0)

        self.assertIsNone(media_share_card_png(joke))

        buf = generate_share_card_png(joke)
        _assert_valid_png_1200x630(self, buf)

    def test_joke_save_with_broken_raster_does_not_raise(self):
        joke = make_joke(self.user, 'image', text='another corrupt raster joke')
        JokeMedia.objects.create(joke=joke, asset=self._corrupt_image_asset(), position=0)

        # Forces regeneration (text changed) -- must not 500.
        joke.text = 'another corrupt raster joke, edited'
        joke.save()

        joke.refresh_from_db()
        self.assertTrue(joke.share_image)
