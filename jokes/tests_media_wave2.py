"""Wave 2 media tests: probe, video/audio/GIF pipeline, formats, watch telemetry."""
import io
import shutil
import subprocess
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
