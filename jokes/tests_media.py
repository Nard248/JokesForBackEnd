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


from unittest.mock import MagicMock, patch

from jokes.media_screening import NullMatcher, get_matcher, screen_image


def _mock_annotation(adult='VERY_UNLIKELY', violence='VERY_UNLIKELY',
                     racy='VERY_UNLIKELY'):
    ann = MagicMock()
    for cat, value in (('adult', adult), ('violence', violence), ('racy', racy),
                       ('medical', 'VERY_UNLIKELY'), ('spoof', 'VERY_UNLIKELY')):
        getattr(ann, cat).name = value
    resp = MagicMock()
    resp.safe_search_annotation = ann
    resp.error.message = ''
    return resp


class ScreeningTests(TestCase):
    def test_disabled_returns_skipped(self):
        with override_settings(SAFESEARCH_ENABLED=False):
            self.assertEqual(screen_image(b'bytes'), {'status': 'skipped'})

    @override_settings(SAFESEARCH_ENABLED=True)
    def test_clean_image_ok(self):
        client = MagicMock()
        client.safe_search_detection.return_value = _mock_annotation()
        with patch('jokes.media_screening._client', return_value=client):
            verdict = screen_image(b'bytes')
        self.assertEqual(verdict['status'], 'ok')
        self.assertEqual(verdict['adult'], 'VERY_UNLIKELY')

    @override_settings(SAFESEARCH_ENABLED=True)
    def test_likely_adult_blocked(self):
        client = MagicMock()
        client.safe_search_detection.return_value = _mock_annotation(adult='LIKELY')
        with patch('jokes.media_screening._client', return_value=client):
            self.assertEqual(screen_image(b'bytes')['status'], 'blocked')

    @override_settings(SAFESEARCH_ENABLED=True)
    def test_racy_alone_does_not_block(self):
        client = MagicMock()
        client.safe_search_detection.return_value = _mock_annotation(racy='VERY_LIKELY')
        with patch('jokes.media_screening._client', return_value=client):
            self.assertEqual(screen_image(b'bytes')['status'], 'ok')

    def test_null_matcher_never_matches(self):
        matcher = get_matcher()
        self.assertIsInstance(matcher, NullMatcher)
        self.assertIsNone(matcher.match('0000000000000000'))


from datetime import timedelta

from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class MediaUploadEndpointTests(TestCase):
    def setUp(self):
        self.user = make_user('uploader@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _upload(self, buf=None, kind='image'):
        buf = buf or make_image_bytes()
        return self.client.post(
            '/api/v1/media/uploads/', {'file': buf, 'kind': kind},
            format='multipart',
        )

    def test_upload_creates_asset_with_metadata(self):
        response = self._upload()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['kind'], 'image')
        self.assertEqual(body['width'], 1200)
        self.assertEqual(body['height'], 900)
        self.assertTrue(body['url'].startswith('http'))
        asset = MediaAsset.objects.get(pk=body['id'])
        self.assertEqual(asset.owner, self.user)
        self.assertEqual(len(asset.phash), 16)

    def test_anon_rejected(self):
        self.client.force_authenticate(None)
        self.assertEqual(self._upload().status_code, 401)

    def test_invalid_file_rejected_400(self):
        buf = io.BytesIO(b'not an image')
        buf.name = 'x.jpg'
        self.assertEqual(self._upload(buf).status_code, 400)

    def test_video_kind_rejected_wave_1(self):
        self.assertEqual(self._upload(kind='video').status_code, 400)

    def test_screening_block_returns_422_and_no_asset(self):
        with patch(
            'jokes.views.screen_image',
            return_value={'status': 'blocked', 'adult': 'LIKELY'},
        ):
            response = self._upload()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(MediaAsset.objects.count(), 0)

    def test_orphan_sweep_deletes_stale_unattached_assets(self):
        with freeze_time('2026-07-18 12:00:00'):
            stale = make_asset(self.user)
            stale_name = stale.file.name
        with freeze_time('2026-07-20 12:00:00'):
            response = self._upload()
        self.assertEqual(response.status_code, 201)
        self.assertFalse(MediaAsset.objects.filter(pk=stale.pk).exists())
        self.assertFalse(default_storage.exists(stale_name))
