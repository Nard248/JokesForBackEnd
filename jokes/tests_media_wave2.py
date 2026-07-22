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
