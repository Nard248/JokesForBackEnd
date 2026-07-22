"""Wave 2 media tests: probe, video/audio/GIF pipeline, formats, watch telemetry."""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from django.test import TestCase

FFMPEG = shutil.which('ffmpeg')

_MEDIA_ROOT = tempfile.mkdtemp()


def make_clip(path, seconds=2, size='320x240', fmt='mp4', audio=True, vcodec=None):
    """Generate a tiny real test clip with the local ffmpeg."""
    cmd = ['ffmpeg', '-y', '-loglevel', 'error',
           '-f', 'lavfi', '-i', f'testsrc2=size={size}:rate=10']
    if audio:
        cmd += ['-f', 'lavfi', '-i', 'sine=frequency=440']
    cmd += ['-t', str(seconds)]
    if vcodec:
        cmd += ['-c:v', vcodec]
    if audio:
        cmd += ['-c:a', 'aac', '-shortest']
    cmd += [path]
    subprocess.run(cmd, check=True, timeout=60)
    return path


def make_audio(path, seconds=2, codec='libmp3lame'):
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', 'sine=frequency=440',
                    '-t', str(seconds), '-c:a', codec, path],
                   check=True, timeout=60)
    return path


def make_gif(path, seconds=1):
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', f'testsrc2=size=160x120:rate=5',
                    '-t', str(seconds), path], check=True, timeout=60)
    return path


def make_audio_with_cover(path, seconds=1):
    """MP3 with an embedded cover-art stream (disposition attached_pic=1) —
    the iTunes/ID3 cover-art shape reported by ffprobe as an mjpeg/png
    "video" stream. Built in three steps (plain audio, then a single-frame
    PNG, then muxed together) because generating both lavfi streams in one
    ffmpeg invocation stalls indefinitely — the image source never signals
    EOF against the audio source without an explicit frame count."""
    with tempfile.TemporaryDirectory() as d:
        audio = f'{d}/audio.mp3'
        cover = f'{d}/cover.png'
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'sine=frequency=440',
                        '-t', str(seconds), '-c:a', 'libmp3lame', audio],
                       check=True, timeout=60)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'color=size=64x64:color=blue',
                        '-frames:v', '1', cover],
                       check=True, timeout=60)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error',
                        '-i', audio, '-i', cover,
                        '-map', '0:a', '-map', '1:v',
                        '-c:a', 'copy', '-c:v', 'png',
                        '-disposition:v', 'attached_pic', path],
                       check=True, timeout=60)
    return path


@unittest.skipUnless(FFMPEG, 'ffmpeg not installed')
class ProbeTests(TestCase):
    def test_probe_mp4_reports_codecs_dims_duration(self):
        from jokes.media_probe import probe_media
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4')
            info = probe_media(clip)
        self.assertEqual(info.video_codec, 'h264')
        self.assertEqual(info.audio_codec, 'aac')
        self.assertEqual((info.width, info.height), (320, 240))
        self.assertTrue(1500 <= info.duration_ms <= 2600)

    def test_probe_audio_only(self):
        from jokes.media_probe import probe_media
        with tempfile.TemporaryDirectory() as d:
            clip = make_audio(f'{d}/in.mp3')
            info = probe_media(clip)
        self.assertIsNone(info.video_codec)
        self.assertEqual(info.audio_codec, 'mp3')

    def test_probe_garbage_raises_validation_error(self):
        from jokes.media_probe import probe_media
        from jokes.media_processing import MediaValidationError
        with tempfile.NamedTemporaryFile(suffix='.mp4') as f:
            f.write(b'this is not a video')
            f.flush()
            with self.assertRaises(MediaValidationError):
                probe_media(f.name)


@unittest.skipUnless(FFMPEG, 'ffmpeg not installed')
class FfmpegDiagnosticsLoggingTests(TestCase):
    """FIX 4: ffmpeg/ffprobe stderr must be logged before raising, so a
    generic 'Could not process this media file' report is debuggable in prod
    without needing a repro."""

    def test_run_ffmpeg_logs_stderr_on_nonzero_exit(self):
        from jokes.media_processing import MediaValidationError, _run_ffmpeg
        with self.assertLogs('jokes.media_processing', level='WARNING') as logs:
            with self.assertRaises(MediaValidationError):
                _run_ffmpeg(['-i', '/no/such/file.mp4', '/tmp/wont-be-created.mp4'])
        self.assertTrue(any('ffmpeg failed' in m for m in logs.output))

    def test_probe_media_logs_stderr_on_nonzero_exit(self):
        from jokes.media_probe import probe_media
        from jokes.media_processing import MediaValidationError
        with tempfile.NamedTemporaryFile(suffix='.mp4') as f:
            f.write(b'this is not a video')
            f.flush()
            with self.assertLogs('jokes.media_probe', level='WARNING') as logs:
                with self.assertRaises(MediaValidationError):
                    probe_media(f.name)
        self.assertTrue(any('ffprobe failed' in m for m in logs.output))


from PIL import Image


@unittest.skipUnless(FFMPEG, 'ffmpeg not installed')
class VideoPipelineTests(TestCase):
    def _upload_from(self, path):
        with open(path, 'rb') as f:
            buf = io.BytesIO(f.read())
        buf.name = path.rsplit('/', 1)[-1]
        return buf

    def test_mp4_normalized_with_poster_and_samples(self):
        from jokes.media_probe import probe_media
        from jokes.media_processing import process_video
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', seconds=3)
            result = process_video(self._upload_from(clip))
            out_path = f'{d}/out.mp4'
            with open(out_path, 'wb') as f:
                f.write(result.data)
            info = probe_media(out_path)
        self.assertEqual(info.video_codec, 'h264')
        self.assertEqual(info.audio_codec, 'aac')
        self.assertEqual(len(result.sample_frames), 2)
        self.assertEqual(len(result.phash), 16)
        poster = Image.open(io.BytesIO(result.poster))
        self.assertEqual(poster.format, 'JPEG')
        self.assertTrue(2500 <= result.duration_ms <= 3600)

    def test_downscales_above_720p(self):
        from jokes.media_processing import process_video
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', seconds=2, size='1920x1080')
            result = process_video(self._upload_from(clip))
        self.assertEqual(result.height, 720)
        self.assertEqual(result.width, 1280)

    def test_overlong_rejected_before_transcode(self):
        from jokes.media_processing import MAX_MEDIA_DURATION_MS, MediaValidationError, process_video
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', seconds=2)
            # Fake an overlong probe so we don't generate a >60s fixture.
            from jokes.media_probe import MediaProbe
            long_probe = MediaProbe('mov', 'h264', 'aac', 320, 240,
                                    MAX_MEDIA_DURATION_MS + 5000)
            with patch('jokes.media_processing.probe_media', return_value=long_probe), \
                 patch('jokes.media_processing._run_ffmpeg') as encode:
                with self.assertRaises(MediaValidationError):
                    process_video(self._upload_from(clip))
                encode.assert_not_called()

    def test_above_1080p_rejected_before_transcode(self):
        from jokes.media_probe import MediaProbe
        from jokes.media_processing import MediaValidationError, process_video
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', seconds=2)
            # Fake a 4K probe so we don't have to encode/ship a real 4K fixture.
            uhd_probe = MediaProbe('mov', 'h264', 'aac', 3840, 2160, 2000)
            with patch('jokes.media_processing.probe_media', return_value=uhd_probe), \
                 patch('jokes.media_processing._run_ffmpeg') as encode:
                with self.assertRaises(MediaValidationError) as ctx:
                    process_video(self._upload_from(clip))
                encode.assert_not_called()
        self.assertIn('1080p', ctx.exception.errors['file'])

    def test_oversize_video_rejected(self):
        from jokes.media_processing import MAX_VIDEO_BYTES, MediaValidationError, process_video
        buf = io.BytesIO(b'x')
        buf.size = MAX_VIDEO_BYTES + 1
        buf.name = 'big.mp4'
        with self.assertRaises(MediaValidationError):
            process_video(buf)

    def test_gif_becomes_silent_mp4(self):
        from jokes.media_probe import probe_media
        from jokes.media_processing import process_video
        with tempfile.TemporaryDirectory() as d:
            gif = make_gif(f'{d}/in.gif')
            result = process_video(self._upload_from(gif), is_gif=True)
            out_path = f'{d}/out.mp4'
            with open(out_path, 'wb') as f:
                f.write(result.data)
            info = probe_media(out_path)
        self.assertEqual(info.video_codec, 'h264')
        self.assertIsNone(info.audio_codec)

    def test_garbage_rejected(self):
        from jokes.media_processing import MediaValidationError, process_video
        buf = io.BytesIO(b'not a video at all')
        buf.name = 'x.mp4'
        with self.assertRaises(MediaValidationError):
            process_video(buf)

    def test_post_encode_duration_lie_rejected_and_workdir_cleaned(self):
        """ffprobe metadata can lie (forged/malformed duration atoms) — the
        pre-encode probe passed, but what ffmpeg actually produced is
        overlong. Patch ONLY the post-encode probe call (the one against the
        ffmpeg output path) to report 70s; the pre-encode probe still runs
        for real against the short fixture clip."""
        from jokes.media_probe import MediaProbe
        from jokes.media_probe import probe_media as real_probe_media
        from jokes.media_processing import MediaValidationError, process_video

        def fake_probe(path):
            info = real_probe_media(path)
            if path.endswith('out.mp4'):
                return MediaProbe(
                    info.container, info.video_codec, info.audio_codec,
                    info.width, info.height, 70_000,
                )
            return info

        workdirs_before = {
            p for p in os.listdir(tempfile.gettempdir())
            if p.startswith('media-video-')
        }
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', seconds=2)
            with patch('jokes.media_processing.probe_media', side_effect=fake_probe):
                with self.assertRaises(MediaValidationError) as ctx:
                    process_video(self._upload_from(clip))
        self.assertIn('60 seconds', ctx.exception.errors['file'])
        workdirs_after = {
            p for p in os.listdir(tempfile.gettempdir())
            if p.startswith('media-video-')
        }
        self.assertEqual(workdirs_after, workdirs_before)


class _TempPathUpload:
    """Duck-typed stand-in for Django's TemporaryUploadedFile: exposes
    `.size` and `temporary_file_path()` without the full file-like read
    interface _spool_to_disk would need."""

    def __init__(self, path):
        self._path = path
        self.name = os.path.basename(path)
        self.size = os.path.getsize(path)

    def temporary_file_path(self):
        return self._path


@unittest.skipUnless(FFMPEG, 'ffmpeg not installed')
class SpoolReuseTests(TestCase):
    """FIX 3: an uploaded object exposing temporary_file_path() (Django's own
    on-disk spool) must be used directly — no second copy — and process_video
    must not delete Django's temp file itself (Django cleans it up)."""

    def test_temporary_file_path_used_directly_no_copy(self):
        from jokes.media_processing import process_video
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', seconds=2)
            uploaded = _TempPathUpload(clip)
            with patch('jokes.media_processing._spool_to_disk') as spool:
                result = process_video(uploaded)
            spool.assert_not_called()
            # Django's own temp file must still be there — process_video must
            # not have unlinked a file it doesn't own.
            self.assertTrue(os.path.exists(clip))
        self.assertTrue(result.duration_ms > 0)

    def test_in_memory_upload_still_spools_a_copy(self):
        """The BytesIO fallback path (no temporary_file_path) must still work
        — this is the pre-existing behavior for in-memory uploads."""
        import jokes.media_processing as media_processing
        from jokes.media_processing import process_video
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', seconds=2)
            with open(clip, 'rb') as f:
                buf = io.BytesIO(f.read())
            buf.name = 'in.mp4'
            with patch.object(
                media_processing, '_spool_to_disk',
                wraps=media_processing._spool_to_disk,
            ) as spool:
                result = process_video(buf)
            spool.assert_called_once()
        self.assertTrue(result.duration_ms > 0)


@unittest.skipUnless(FFMPEG, 'ffmpeg not installed')
class AudioPipelineTests(TestCase):
    def test_mp3_remuxed_to_m4a_aac(self):
        from jokes.media_probe import probe_media
        from jokes.media_processing import process_audio
        with tempfile.TemporaryDirectory() as d:
            src = make_audio(f'{d}/in.mp3')
            with open(src, 'rb') as f:
                buf = io.BytesIO(f.read())
            buf.name = 'in.mp3'
            result = process_audio(buf)
            out = f'{d}/out.m4a'
            with open(out, 'wb') as f:
                f.write(result.data)
            info = probe_media(out)
        self.assertEqual(info.audio_codec, 'aac')
        self.assertIsNone(info.video_codec)
        self.assertTrue(1500 <= result.duration_ms <= 2600)

    def test_video_container_rejected_as_audio(self):
        from jokes.media_processing import MediaValidationError, process_audio
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', seconds=2)
            with open(clip, 'rb') as f:
                buf = io.BytesIO(f.read())
            buf.name = 'in.mp4'
            with self.assertRaises(MediaValidationError):
                process_audio(buf)


# =============================================================================
# Task 2 review follow-ups: circular-import fix + cover-art probe fix
# =============================================================================

class ImportCycleRegressionTests(TestCase):
    """jokes.media_probe imported MediaValidationError from jokes.media_processing
    at module level, while jokes.media_processing imports probe_media from
    jokes.media_probe at module level — a fresh interpreter importing
    media_probe FIRST hit an ImportError (partially-initialized module).
    Guard the fix by actually importing media_probe first, in a fresh
    subprocess (this process has already imported both modules in whatever
    order the test runner happened to load them, so re-importing here would
    prove nothing)."""

    def test_media_probe_importable_first_in_a_fresh_interpreter(self):
        env = dict(os.environ, DJANGO_SETTINGS_MODULE='JokesForProject.settings')
        result = subprocess.run(
            [sys.executable, '-c',
             'import django; django.setup(); import jokes.media_probe'],
            env=env, capture_output=True, timeout=30,
        )
        self.assertEqual(
            result.returncode, 0,
            f'stdout={result.stdout.decode()!r} stderr={result.stderr.decode()!r}',
        )


@unittest.skipUnless(FFMPEG, 'ffmpeg not installed')
class CoverArtProbeTests(TestCase):
    """iTunes-style MP3 cover art reports as an attached_pic mjpeg/png
    "video" stream — it must not make probe_media/process_audio think the
    file is a video."""

    def test_probe_ignores_attached_pic_stream(self):
        from jokes.media_probe import probe_media
        with tempfile.TemporaryDirectory() as d:
            clip = make_audio_with_cover(f'{d}/in.mp3')
            info = probe_media(clip)
        self.assertIsNone(info.video_codec)
        self.assertEqual(info.audio_codec, 'mp3')

    def test_process_audio_accepts_mp3_with_cover_art(self):
        from jokes.media_processing import process_audio
        with tempfile.TemporaryDirectory() as d:
            clip = make_audio_with_cover(f'{d}/in.mp3')
            with open(clip, 'rb') as f:
                buf = io.BytesIO(f.read())
            buf.name = 'in.mp3'
            result = process_audio(buf)
        self.assertTrue(result.duration_ms > 0)


# =============================================================================
# Task 3: upload endpoint dispatcher (video / audio / GIF)
# =============================================================================

from unittest.mock import patch

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from jokes.models import MediaAsset
from jokes.tests_media import make_user


class _FakeRequest:
    """Minimal duck-typed stand-in for exercising `MediaUploadView.post`
    directly. Real HTTP round-tripping (APIClient) recomputes an uploaded
    file's `.size` from the actual bytes sent, so a real multipart POST
    can't exercise the "fake .size attribute" oversize path without
    actually uploading an oversize payload — this bypasses DRF's request
    parsing so a manually-faked `.size` survives untouched."""

    def __init__(self, data, files, user):
        self.data = data
        self.FILES = files
        self.user = user


@unittest.skipUnless(FFMPEG, 'ffmpeg not installed')
@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class MediaUploadWave2Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = make_user('wave2-uploader@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _upload(self, buf, kind):
        return self.client.post(
            '/api/v1/media/uploads/', {'file': buf, 'kind': kind},
            format='multipart',
        )

    def _clip_buf(self, name='in.mp4', **kwargs):
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', **kwargs)
            with open(clip, 'rb') as f:
                buf = io.BytesIO(f.read())
        buf.name = name
        return buf

    def _gif_buf(self, name='in.gif', **kwargs):
        with tempfile.TemporaryDirectory() as d:
            gif = make_gif(f'{d}/in.gif', **kwargs)
            with open(gif, 'rb') as f:
                buf = io.BytesIO(f.read())
        buf.name = name
        return buf

    def _audio_buf(self, name='in.mp3', **kwargs):
        with tempfile.TemporaryDirectory() as d:
            src = make_audio(f'{d}/in.mp3', **kwargs)
            with open(src, 'rb') as f:
                buf = io.BytesIO(f.read())
        buf.name = name
        return buf

    def _media_files_on_disk(self):
        return {
            os.path.join(root, name)
            for root, _, files in os.walk(_MEDIA_ROOT)
            for name in files
        }

    def _probe_stored(self, field_file):
        from jokes.media_probe import probe_media
        with tempfile.NamedTemporaryFile(suffix='.mp4') as tmp:
            with field_file.open('rb') as fh:
                tmp.write(fh.read())
            tmp.flush()
            return probe_media(tmp.name)

    # -- 1. video upload --------------------------------------------------
    def test_video_upload_creates_asset_with_poster(self):
        response = self._upload(self._clip_buf(seconds=2), 'video')
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['kind'], 'video')
        self.assertFalse(body['is_gif'])
        self.assertIsNotNone(body['duration_ms'])
        self.assertTrue(body['poster_url'])
        asset = MediaAsset.objects.get(pk=body['id'])
        self.assertTrue(asset.poster.name)
        self.assertTrue(default_storage.exists(asset.poster.name))
        poster_bytes = asset.poster.open('rb').read()
        self.assertEqual(Image.open(io.BytesIO(poster_bytes)).format, 'JPEG')

    # -- 2. GIF under kind=video --------------------------------------------
    def test_gif_under_video_kind_is_silent_and_flagged(self):
        response = self._upload(self._gif_buf(), 'video')
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['kind'], 'video')
        self.assertTrue(body['is_gif'])
        asset = MediaAsset.objects.get(pk=body['id'])
        info = self._probe_stored(asset.file)
        self.assertIsNone(info.audio_codec)

    # -- 3. GIF under kind=image (backwards-friendly routing) --------------
    def test_gif_under_image_kind_routes_as_video(self):
        response = self._upload(self._gif_buf(), 'image')
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['kind'], 'video')
        self.assertTrue(body['is_gif'])
        asset = MediaAsset.objects.get(pk=body['id'])
        info = self._probe_stored(asset.file)
        self.assertIsNone(info.audio_codec)

    # -- 4. audio upload -----------------------------------------------------
    def test_audio_upload_creates_asset_without_poster(self):
        response = self._upload(self._audio_buf(seconds=2), 'audio')
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['kind'], 'audio')
        self.assertIsNone(body['poster_url'])
        self.assertIsNotNone(body['duration_ms'])
        asset = MediaAsset.objects.get(pk=body['id'])
        self.assertFalse(asset.poster)

    # -- 5. any blocked frame blocks the whole clip -------------------------
    def test_video_screening_blocks_on_any_frame_and_stores_no_asset(self):
        verdicts = [{'status': 'ok'}, {'status': 'blocked', 'adult': 'LIKELY'},
                    {'status': 'ok'}]
        with patch('jokes.views.screen_image', side_effect=verdicts) as mock_screen:
            response = self._upload(self._clip_buf(seconds=3), 'video')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(mock_screen.call_count, 3)
        self.assertEqual(MediaAsset.objects.count(), 0)

    # -- 6. invalid file rejected --------------------------------------------
    def test_video_kind_rejects_non_media_file_400(self):
        buf = io.BytesIO(b'not a video at all')
        buf.name = 'evil.mp4'
        response = self._upload(buf, 'video')
        self.assertEqual(response.status_code, 400)
        # Must be a real process_video rejection (probe/container failure),
        # not a stale "only image uploads supported" gate.
        self.assertNotIn('kind', response.json())
        self.assertEqual(MediaAsset.objects.count(), 0)

    # -- 7. oversize rejected before any ffmpeg call -------------------------
    def test_oversize_video_rejected_before_ffmpeg_call(self):
        from jokes.media_processing import MAX_VIDEO_BYTES
        from jokes.views import MediaUploadView

        uploaded = SimpleUploadedFile('big.mp4', b'x', content_type='video/mp4')
        uploaded.size = MAX_VIDEO_BYTES + 1
        request = _FakeRequest({'kind': 'video'}, {'file': uploaded}, self.user)
        with patch('jokes.media_processing._run_ffmpeg') as run:
            response = MediaUploadView().post(request)
        self.assertEqual(response.status_code, 400)
        # Must be the size-cap rejection specifically, not some other 400 —
        # this is what proves the cap ran before any ffmpeg subprocess.
        self.assertIn('exceeds', str(response.data.get('file', '')))
        run.assert_not_called()
        self.assertEqual(MediaAsset.objects.count(), 0)

    # -- self-review: DB-failure cleanup must cover the poster too ----------
    def test_db_failure_cleans_up_video_file_and_poster(self):
        before = self._media_files_on_disk()
        with patch.object(MediaAsset, 'save', side_effect=RuntimeError('db down')):
            with self.assertRaises(RuntimeError):
                self._upload(self._clip_buf(seconds=2), 'video')
        self.assertEqual(MediaAsset.objects.count(), 0)
        self.assertEqual(self._media_files_on_disk(), before)


@unittest.skipUnless(FFMPEG, 'ffmpeg not installed')
@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class EncodeConcurrencyGuardTests(TestCase):
    """FIX 5: _ENCODE_SLOTS is a per-worker BoundedSemaphore(1) (gunicorn
    --workers 2 ⇒ 2 concurrent encodes per instance) — exhausting it must
    surface as a 429 with a Retry-After header, not a 500 or a hang."""

    def setUp(self):
        self.user = make_user('busy-uploader@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _upload(self, buf, kind):
        return self.client.post(
            '/api/v1/media/uploads/', {'file': buf, 'kind': kind},
            format='multipart',
        )

    def _clip_buf(self, name='in.mp4', **kwargs):
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', **kwargs)
            with open(clip, 'rb') as f:
                buf = io.BytesIO(f.read())
        buf.name = name
        return buf

    def test_upload_429s_while_slots_exhausted_then_succeeds_after_release(self):
        from jokes.media_processing import _ENCODE_SLOTS

        self.assertTrue(_ENCODE_SLOTS.acquire(blocking=False))
        try:
            response = self._upload(self._clip_buf(seconds=2), 'video')
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json()['detail'],
                              'Media processing is busy — try again in a moment.')
            self.assertEqual(response.headers['Retry-After'], '30')
            self.assertEqual(MediaAsset.objects.count(), 0)
        finally:
            _ENCODE_SLOTS.release()

        response = self._upload(self._clip_buf(seconds=2), 'video')
        self.assertEqual(response.status_code, 201)


# =============================================================================
# Task 4: video / audio formats — registry, seed, wave-1 machinery
# verification
#
# The wave-1 media machinery (publish copy, locking, account-delete via
# FORMAT_RULES-derived media_slugs, draft attach, submit gate) is
# format-agnostic BY DESIGN. These tests register `video`/`audio` in
# FORMAT_RULES and prove the existing machinery picks them up untouched.
# =============================================================================
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory

from jokes.admin import JokeSubmissionAdmin
from jokes.models import (
    AgeRating, Format, Joke, JokeSubmission, JokeSubmissionMedia, Language,
)
from jokes.serializers import JokeSerializer
from jokes.submission_rules import validate_per_format
from jokes.tests_media import locked_state, make_asset

Wave2User = get_user_model()


def _format_taxonomy(slug, name):
    fmt, _ = Format.objects.get_or_create(slug=slug, defaults={'name': name})
    age, _ = AgeRating.objects.get_or_create(
        slug='all-ages', defaults={'name': 'All Ages'},
    )
    lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
    return fmt, age, lang


class VideoFormatRuleTests(TestCase):
    """Mirrors Wave 1's ImageFormatRuleTests for the new `video` slug."""

    def test_video_requires_setup_and_media(self):
        errors = validate_per_format('video', {'setup': '', 'media': []})
        self.assertIn('setup', errors)
        self.assertIn('media', errors)

    def test_video_happy_path(self):
        errors = validate_per_format(
            'video',
            {'setup': 'watch this', 'media': [{'kind': 'video', 'duration_ms': 5000}]},
        )
        self.assertEqual(errors, {})

    def test_video_rejects_punchline(self):
        errors = validate_per_format(
            'video',
            {
                'setup': 'watch this', 'punchline': 'nope',
                'media': [{'kind': 'video', 'duration_ms': 5000}],
            },
        )
        self.assertIn('punchline', errors)

    def test_video_max_one_attachment(self):
        errors = validate_per_format(
            'video',
            {
                'setup': 'watch this',
                'media': [{'kind': 'video', 'duration_ms': 5000}] * 2,
            },
        )
        self.assertIn('media', errors)

    def test_video_rejects_wrong_kind(self):
        errors = validate_per_format(
            'video',
            {'setup': 'watch this', 'media': [{'kind': 'image', 'duration_ms': None}]},
        )
        self.assertIn('media', errors)

    def test_video_rejects_over_duration_cap(self):
        errors = validate_per_format(
            'video',
            {
                'setup': 'watch this',
                'media': [{'kind': 'video', 'duration_ms': 60001}],
            },
        )
        self.assertIn('media', errors)
        self.assertIn('60 seconds', errors['media'])

    def test_video_allows_duration_at_cap(self):
        errors = validate_per_format(
            'video',
            {
                'setup': 'watch this',
                'media': [{'kind': 'video', 'duration_ms': 60000}],
            },
        )
        self.assertEqual(errors, {})


class AudioFormatRuleTests(TestCase):
    """Mirrors VideoFormatRuleTests for the new `audio` slug."""

    def test_audio_requires_setup_and_media(self):
        errors = validate_per_format('audio', {'setup': '', 'media': []})
        self.assertIn('setup', errors)
        self.assertIn('media', errors)

    def test_audio_happy_path(self):
        errors = validate_per_format(
            'audio',
            {'setup': 'listen up', 'media': [{'kind': 'audio', 'duration_ms': 5000}]},
        )
        self.assertEqual(errors, {})

    def test_audio_rejects_punchline(self):
        errors = validate_per_format(
            'audio',
            {
                'setup': 'listen up', 'punchline': 'nope',
                'media': [{'kind': 'audio', 'duration_ms': 5000}],
            },
        )
        self.assertIn('punchline', errors)

    def test_audio_max_one_attachment(self):
        errors = validate_per_format(
            'audio',
            {
                'setup': 'listen up',
                'media': [{'kind': 'audio', 'duration_ms': 5000}] * 2,
            },
        )
        self.assertIn('media', errors)

    def test_audio_rejects_wrong_kind(self):
        errors = validate_per_format(
            'audio',
            {'setup': 'listen up', 'media': [{'kind': 'video', 'duration_ms': None}]},
        )
        self.assertIn('media', errors)

    def test_audio_rejects_over_duration_cap(self):
        errors = validate_per_format(
            'audio',
            {
                'setup': 'listen up',
                'media': [{'kind': 'audio', 'duration_ms': 90000}],
            },
        )
        self.assertIn('media', errors)
        self.assertIn('60 seconds', errors['media'])


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class VideoDraftFlowTests(TestCase):
    """API flow: draft attach + submit gate, for the video format."""

    def setUp(self):
        self.video_fmt, self.age, self.lang = _format_taxonomy('video', 'Video')
        self.image_fmt, _, _ = _format_taxonomy('image', 'Image')
        self.user = make_user('videocreator@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _make_draft(self, fmt_slug):
        response = self.client.post('/api/v1/jokes/my-drafts/', {'format': fmt_slug})
        self.assertEqual(response.status_code, 201)
        return response.json()['id']

    def test_submit_happy_path_with_video_asset(self):
        draft_id = self._make_draft('video')
        asset = make_asset(self.user, kind='video', duration_ms=5000)
        patch_response = self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'setup': 'watch this', 'media_asset_ids': [str(asset.pk)]},
            format='json',
        )
        self.assertEqual(patch_response.status_code, 200)
        response = self.client.post(f'/api/v1/jokes/my-drafts/{draft_id}/submit/')
        self.assertEqual(response.status_code, 200)
        draft = JokeSubmission.objects.get(pk=draft_id)
        self.assertEqual(draft.status, 'pending')

    def test_video_asset_on_image_draft_rejected_at_submit(self):
        draft_id = self._make_draft('image')
        asset = make_asset(self.user, kind='video', duration_ms=5000)
        # Draft autosave (PATCH) skips per-format validation, so the kind
        # mismatch isn't caught yet — it's a submit-time gate.
        patch_response = self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'setup': 'watch this', 'media_asset_ids': [str(asset.pk)]},
            format='json',
        )
        self.assertEqual(patch_response.status_code, 200)
        response = self.client.post(f'/api/v1/jokes/my-drafts/{draft_id}/submit/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('media', response.json())


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class VideoPublishLockingAndAccountDeleteTests(TestCase):
    """Publish copy, locking (poster_url stripped), and account-delete
    media_slugs auto-derivation — all wave-1 machinery, proven for video."""

    def setUp(self):
        self.fmt, self.age, self.lang = _format_taxonomy('video', 'Video')
        self.user = make_user('videopublisher@example.com')
        self.admin_user = Wave2User.objects.create_superuser(
            username='videoadmin@example.com', email='videoadmin@example.com',
            password='x',
        )
        self.factory = APIRequestFactory()

    def _admin_request(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.middleware import SessionMiddleware
        request = self.factory.post('/admin/')
        request.user = self.admin_user
        SessionMiddleware(lambda r: None).process_request(request)
        request._messages = FallbackStorage(request)
        return request

    def _publish_video_joke(self, setup='watch this'):
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt, age_rating=self.age,
            language=self.lang, setup=setup, text=setup, status='pending',
        )
        asset = make_asset(self.user, kind='video', duration_ms=5000)
        JokeSubmissionMedia.objects.create(submission=sub, asset=asset, position=0)
        admin_obj = JokeSubmissionAdmin(JokeSubmission, AdminSite())
        with patch('jokes.models.Joke._generate_share_image'):
            admin_obj.approve_and_publish(
                self._admin_request(), JokeSubmission.objects.filter(pk=sub.pk),
            )
        sub.refresh_from_db()
        return sub.published_joke

    def test_approve_and_publish_copies_video_media(self):
        joke = self._publish_video_joke()
        self.assertIsNotNone(joke)
        self.assertEqual(joke.media.count(), 1)
        self.assertEqual(joke.media.first().asset.kind, 'video')

    def test_locked_video_joke_serves_dims_only_no_poster_url(self):
        joke = self._publish_video_joke()
        request = APIRequestFactory().get('/api/v1/jokes/')
        data = JokeSerializer(
            joke, context={'request': request, 'paywall_state': locked_state()},
        ).data
        self.assertTrue(data['is_locked'])
        item = data['media'][0]
        self.assertEqual(set(item.keys()), {'kind', 'width', 'height'})
        self.assertNotIn('poster_url', item)
        self.assertNotIn('url', item)
        self.assertNotIn('duration_ms', item)

    def test_unlocked_video_joke_serves_poster_url(self):
        joke = self._publish_video_joke()
        request = APIRequestFactory().get('/api/v1/jokes/')
        data = JokeSerializer(joke, context={'request': request}).data
        self.assertFalse(data['is_locked'])
        item = data['media'][0]
        self.assertIn('poster_url', item)
        self.assertIn('url', item)

    def test_account_delete_removes_emptied_video_joke(self):
        # media_slugs auto-derivation (jokes/views.py DataDeleteView) reads
        # FORMAT_RULES for every slug requiring 'media' — video now qualifies
        # automatically, with no production edit beyond FORMAT_RULES itself.
        joke = self._publish_video_joke()
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.delete(
            '/api/v1/users/me/', {'password': 'x'}, format='json',
        )
        self.assertIn(response.status_code, (200, 204))
        joke = Joke.all_objects.get(pk=joke.pk)
        self.assertTrue(joke.is_removed)


from django.core.files.base import ContentFile


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class AdminMediaPreviewTests(TestCase):
    """FIX 6: media_preview must render something useful for video (poster
    thumbnail + play badge) and audio (a link with duration) — previously it
    unconditionally rendered `<img src=asset.file.url>`, which for
    audio/video assets points at a non-image file."""

    def setUp(self):
        self.fmt_video, self.age, self.lang = _format_taxonomy('video', 'Video')
        self.fmt_audio, _, _ = _format_taxonomy('audio', 'Audio')
        self.user = make_user('adminpreview@example.com')
        self.admin_obj = JokeSubmissionAdmin(JokeSubmission, AdminSite())

    def _submission(self, fmt, asset):
        sub = JokeSubmission.objects.create(
            user=self.user, format=fmt, age_rating=self.age, language=self.lang,
            setup='x', text='x', status='pending',
        )
        JokeSubmissionMedia.objects.create(submission=sub, asset=asset, position=0)
        return sub

    def test_video_preview_renders_poster_with_play_badge(self):
        asset = MediaAsset(owner=self.user, kind='video', width=1280, height=720,
                            duration_ms=5000)
        asset.file.save('video.mp4', ContentFile(b'fake-mp4-bytes'), save=False)
        asset.poster.save('poster.jpg', ContentFile(b'fake-jpg-bytes'), save=False)
        asset.save()
        sub = self._submission(self.fmt_video, asset)
        html = str(self.admin_obj.media_preview(sub))
        self.assertIn(asset.poster.url, html)
        self.assertIn('▶', html)

    def test_video_preview_without_poster_falls_back_to_dash(self):
        asset = MediaAsset(owner=self.user, kind='video', width=1280, height=720,
                            duration_ms=5000)
        asset.file.save('video.mp4', ContentFile(b'fake-mp4-bytes'), save=False)
        asset.save()
        sub = self._submission(self.fmt_video, asset)
        self.assertEqual(self.admin_obj.media_preview(sub), '—')

    def test_audio_preview_renders_link_with_duration(self):
        asset = MediaAsset(owner=self.user, kind='audio', duration_ms=45000)
        asset.file.save('audio.m4a', ContentFile(b'fake-m4a-bytes'), save=False)
        asset.save()
        sub = self._submission(self.fmt_audio, asset)
        html = str(self.admin_obj.media_preview(sub))
        self.assertIn(asset.file.url, html)
        self.assertIn('45', html)


class AdminSafesearchFlagsTests(TestCase):
    """FIX 7: safesearch_flags must also descend into verdict['frames'] —
    the per-sampled-frame screening results attached to video assets — not
    just the top-level verdict keys."""

    def setUp(self):
        self.fmt, self.age, self.lang = _format_taxonomy('video', 'Video')
        self.user = make_user('adminflags@example.com')
        self.admin_obj = JokeSubmissionAdmin(JokeSubmission, AdminSite())

    def test_flags_include_nested_frame_verdicts(self):
        verdict = {
            'status': 'ok',
            'frames': [
                {'status': 'ok'},
                {'status': 'ok', 'adult': 'POSSIBLE'},
            ],
        }
        asset = make_asset(self.user, kind='video', duration_ms=5000, safesearch=verdict)
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt, age_rating=self.age, language=self.lang,
            setup='x', text='x', status='pending',
        )
        JokeSubmissionMedia.objects.create(submission=sub, asset=asset, position=0)
        flags = self.admin_obj.safesearch_flags(sub)
        self.assertIn('adult:POSSIBLE', flags)


# =============================================================================
# Task 5: Watch telemetry — JokeWatch ingest.
#
# `watch` is a new etype alongside impression/reveal/dwell on the same
# POST /api/v1/telemetry/events endpoint (see TelemetryIngestView in
# jokes/views.py). Validation/clamping mirrors the dwell branch exactly:
# drop watch_ms < 500, clamp both fields, silently skip bad joke ids, and
# count toward the 202 accepted total. Append-only — no dedupe.
# =============================================================================

from jokes.models import JokeWatch

WATCH_INGEST_URL = '/api/v1/telemetry/events'


def _make_watch_joke(fmt, age, lang, text='Watch joke'):
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(text=text, format=fmt, age_rating=age, language=lang)


class WatchTelemetryIngestTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.first()
        cls.lang = Language.objects.get(code='en')
        cls.user = Wave2User.objects.create_user(
            username='watchtele@test.com', email='watchtele@test.com', password='x',
        )
        cls.joke = _make_watch_joke(cls.fmt, cls.age, cls.lang, text='W1')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_watch_creates_row_and_counts_accepted(self):
        resp = self.client.post(
            WATCH_INGEST_URL,
            {'events': [
                {'joke': self.joke.id, 'type': 'watch', 'watch_ms': 5000,
                 'watch_pct': 80, 'source': 'feed'},
            ]},
            format='json',
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()['accepted'], 1)
        w = JokeWatch.objects.get(user=self.user, joke=self.joke)
        self.assertEqual(w.watch_ms, 5000)
        self.assertEqual(w.watch_pct, 80)
        self.assertEqual(w.source, 'feed')

    def test_watch_ms_clamped_to_max(self):
        resp = self.client.post(
            WATCH_INGEST_URL,
            {'events': [{'joke': self.joke.id, 'type': 'watch', 'watch_ms': 999999999}]},
            format='json',
        )
        self.assertEqual(resp.json()['accepted'], 1)
        self.assertEqual(JokeWatch.objects.get().watch_ms, 600000)

    def test_watch_below_min_dropped(self):
        resp = self.client.post(
            WATCH_INGEST_URL,
            {'events': [{'joke': self.joke.id, 'type': 'watch', 'watch_ms': 300}]},
            format='json',
        )
        self.assertEqual(resp.json()['accepted'], 0)
        self.assertEqual(JokeWatch.objects.count(), 0)

    def test_watch_pct_clamped(self):
        joke2 = _make_watch_joke(self.fmt, self.age, self.lang, text='W2')
        resp = self.client.post(
            WATCH_INGEST_URL,
            {'events': [
                {'joke': self.joke.id, 'type': 'watch', 'watch_ms': 5000, 'watch_pct': 250},
                {'joke': joke2.id, 'type': 'watch', 'watch_ms': 5000, 'watch_pct': -10},
            ]},
            format='json',
        )
        self.assertEqual(resp.json()['accepted'], 2)
        self.assertEqual(JokeWatch.objects.get(joke=self.joke).watch_pct, 100)
        self.assertEqual(JokeWatch.objects.get(joke=joke2).watch_pct, 0)

    def test_watch_pct_optional(self):
        resp = self.client.post(
            WATCH_INGEST_URL,
            {'events': [{'joke': self.joke.id, 'type': 'watch', 'watch_ms': 5000}]},
            format='json',
        )
        self.assertEqual(resp.json()['accepted'], 1)
        self.assertIsNone(JokeWatch.objects.get().watch_pct)

    def test_watch_bad_value_skipped(self):
        resp = self.client.post(
            WATCH_INGEST_URL,
            {'events': [
                {'joke': self.joke.id, 'type': 'watch'},                     # missing watch_ms
                {'joke': self.joke.id, 'type': 'watch', 'watch_ms': 'abc'},  # non-int
                {'joke': self.joke.id, 'type': 'watch', 'watch_ms': True},   # bool, not int
            ]},
            format='json',
        )
        self.assertEqual(resp.json()['accepted'], 0)
        self.assertEqual(JokeWatch.objects.count(), 0)

    def test_watch_bad_joke_id_skipped_silently(self):
        resp = self.client.post(
            WATCH_INGEST_URL,
            {'events': [
                {'joke': 999999, 'type': 'watch', 'watch_ms': 5000},        # unknown joke
                {'joke': self.joke.id, 'type': 'watch', 'watch_ms': 5000},  # valid
            ]},
            format='json',
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()['accepted'], 1)
        self.assertEqual(JokeWatch.objects.count(), 1)

    def test_watch_appends_multiple_rows_no_dedupe(self):
        # Unlike impressions, watch is NOT deduped — every sample is a row.
        events = [{'joke': self.joke.id, 'type': 'watch', 'watch_ms': 5000}] * 3
        resp = self.client.post(WATCH_INGEST_URL, {'events': events}, format='json')
        self.assertEqual(resp.json()['accepted'], 3)
        self.assertEqual(
            JokeWatch.objects.filter(user=self.user, joke=self.joke).count(), 3
        )

    def test_watch_mixed_with_other_etypes_all_counted(self):
        events = [
            {'joke': self.joke.id, 'type': 'impression'},
            {'joke': self.joke.id, 'type': 'watch', 'watch_ms': 5000},
        ]
        resp = self.client.post(WATCH_INGEST_URL, {'events': events}, format='json')
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()['accepted'], 2)
