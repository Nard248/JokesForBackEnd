"""Tests for media jokes (Wave 1): assets, pipeline, formats, locking, anon paywall."""
import io
import shutil
import tempfile
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from PIL import Image

from jokes.models import (
    AgeRating, Format, Joke, JokeMedia, JokeSubmission, JokeSubmissionMedia,
    Language, MediaAsset,
)
from jokes.media_processing import (
    MAX_IMAGE_BYTES, MediaValidationError, process_image,
)

User = get_user_model()

_MEDIA_ROOT = tempfile.mkdtemp()


def make_user(email='creator@example.com'):
    return User.objects.create_user(username=email, email=email, password='x')


def make_asset(owner, kind='image', **kwargs):
    asset = MediaAsset(owner=owner, kind=kind, width=800, height=600, **kwargs)
    asset.file.save('image.webp', ContentFile(b'fake-webp-bytes'), save=False)
    asset.save()
    return asset


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class MediaAssetModelTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def test_asset_has_uuid_pk_and_pathed_file(self):
        asset = make_asset(make_user())
        self.assertIsInstance(asset.pk, uuid.UUID)
        self.assertIn(f'media-assets/{asset.pk}/', asset.file.name)

    def test_delete_with_files_removes_storage_objects_and_row(self):
        asset = make_asset(make_user())
        name = asset.file.name
        self.assertTrue(default_storage.exists(name))
        asset.delete_with_files()
        self.assertFalse(default_storage.exists(name))
        self.assertFalse(MediaAsset.objects.filter(pk=asset.pk).exists())

    def test_asset_delete_cascades_through_links(self):
        user = make_user()
        asset = make_asset(user)
        fmt, _ = Format.objects.get_or_create(slug='image', defaults={'name': 'Image'})
        age, _ = AgeRating.objects.get_or_create(slug='all-ages', defaults={'name': 'All Ages'})
        lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
        sub = JokeSubmission.objects.create(
            user=user, format=fmt, age_rating=age, language=lang, setup='caption'
        )
        JokeSubmissionMedia.objects.create(submission=sub, asset=asset, position=0)
        asset.delete_with_files()
        self.assertEqual(sub.media.count(), 0)


def make_image_bytes(width=1200, height=900, fmt='JPEG', exif=None):
    img = Image.new('RGB', (width, height), color=(120, 40, 200))
    buf = io.BytesIO()
    kwargs = {'format': fmt}
    if exif is not None:
        kwargs['exif'] = exif
    img.save(buf, **kwargs)
    buf.seek(0)
    buf.name = f'test.{fmt.lower()}'
    return buf


class ImageProcessingTests(TestCase):
    def test_valid_jpeg_is_reencoded_to_webp_with_dims_and_phash(self):
        result = process_image(make_image_bytes(1200, 900))
        self.assertEqual((result.width, result.height), (1200, 900))
        self.assertEqual(len(result.phash), 16)
        out = Image.open(io.BytesIO(result.data))
        self.assertEqual(out.format, 'WEBP')

    def test_oversize_dimensions_rejected(self):
        with self.assertRaises(MediaValidationError) as ctx:
            process_image(make_image_bytes(5000, 100))
        self.assertIn('file', ctx.exception.errors)

    def test_downscales_to_1600_longest_edge(self):
        result = process_image(make_image_bytes(3200, 1600))
        self.assertEqual((result.width, result.height), (1600, 800))

    def test_non_image_rejected(self):
        buf = io.BytesIO(b'this is not an image at all')
        buf.name = 'evil.jpg'
        with self.assertRaises(MediaValidationError):
            process_image(buf)

    def test_gif_rejected_in_wave_1(self):
        with self.assertRaises(MediaValidationError):
            process_image(make_image_bytes(fmt='GIF'))

    def test_exif_is_stripped(self):
        exif = Image.Exif()
        exif[0x010F] = 'TestCam Make'          # Make tag
        src = make_image_bytes(exif=exif.tobytes())
        result = process_image(src)
        out = Image.open(io.BytesIO(result.data))
        self.assertEqual(dict(out.getexif()), {})

    def test_phash_is_deterministic(self):
        a = process_image(make_image_bytes())
        b = process_image(make_image_bytes())
        self.assertEqual(a.phash, b.phash)

    def test_oversize_bytes_rejected_via_size_attribute(self):
        buf = make_image_bytes()               # valid small image
        buf.size = MAX_IMAGE_BYTES + 1         # Django-File-style size attr
        with self.assertRaises(MediaValidationError) as ctx:
            process_image(buf)
        self.assertIn('limit', ctx.exception.errors['file'])

    def test_oversize_bytes_rejected_without_size_attribute(self):
        buf = io.BytesIO(b'x' * (MAX_IMAGE_BYTES + 1))   # no .size attr
        buf.name = 'big.jpg'
        with self.assertRaises(MediaValidationError) as ctx:
            process_image(buf)
        # Must be the size error, not 'Not a valid image': the byte cap has
        # to run BEFORE Pillow ever parses the stream.
        self.assertIn('limit', ctx.exception.errors['file'])

    def test_truncated_image_raises_validation_error_not_oserror(self):
        good = make_image_bytes().getvalue()
        bad = io.BytesIO(good[: int(len(good) * 0.6)])
        bad.name = 'trunc.jpg'
        with self.assertRaises(MediaValidationError):
            process_image(bad)

    def test_decompression_bomb_raises_validation_error(self):
        buf = make_image_bytes(1200, 900)      # 1.08M px > 2 * patched cap
        with mock.patch.object(Image, 'MAX_IMAGE_PIXELS', 1000):
            with self.assertRaises(MediaValidationError):
                process_image(buf)
