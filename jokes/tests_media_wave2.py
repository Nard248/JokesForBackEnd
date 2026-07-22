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
