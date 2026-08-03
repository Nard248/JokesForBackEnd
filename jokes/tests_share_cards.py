"""Tests for Share-Cards-Wave Task 1: media-card generator + dispatch.

Deliberately does NOT patch Joke._generate_share_image / cairosvg — card
generation is the code under test here (unlike jokes/tests_media.py, which
stubs it out because it's irrelevant to what those tests cover). Requires a
working libcairo (see run notes in the task report).
"""
import io
import shutil
import tempfile
from unittest import mock

from django.core.files.base import ContentFile
from django.db.models.fields.files import FieldFile
from django.test import TestCase, override_settings
from PIL import Image

from jokes.models import Format, Joke, JokeMedia, MediaAsset
from jokes.share_cards import _downscale_raster, generate_share_card_png, media_share_card_png
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
