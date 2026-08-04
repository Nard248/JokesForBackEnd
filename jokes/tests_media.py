"""Tests for media jokes (Wave 1): assets, pipeline, formats, locking, anon paywall."""
import io
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from PIL import Image

from jokes.media_processing import (
    MAX_IMAGE_BYTES,
    MediaValidationError,
    process_image,
)
from jokes.models import (
    AgeRating,
    Format,
    Joke,
    JokeMedia,
    JokeSubmission,
    JokeSubmissionMedia,
    Language,
    MediaAsset,
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

    @override_settings(SAFESEARCH_ENABLED=True)
    def test_thrown_client_failure_fails_open_as_error(self):
        """A raised client error (grpc PERMISSION_DENIED, quota, network) must
        fail open like an in-response error — never a 500 (found by prod E2E)."""
        with patch('jokes.media_screening._client',
                   side_effect=RuntimeError('grpc PERMISSION_DENIED')):
            verdict = screen_image(b'bytes')
        self.assertEqual(verdict['status'], 'error')
        self.assertIn('PERMISSION_DENIED', verdict['detail'])

    def test_null_matcher_never_matches(self):
        matcher = get_matcher()
        self.assertIsInstance(matcher, NullMatcher)
        self.assertIsNone(matcher.match('0000000000000000'))



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

    def _media_files_on_disk(self):
        return {
            os.path.join(root, name)
            for root, _, files in os.walk(_MEDIA_ROOT)
            for name in files
        }

    def test_db_failure_after_storage_write_cleans_up_file(self):
        """A DB failure in asset.save() must not strand the just-written
        storage object: with no MediaAsset row, the orphan sweep can never
        reclaim the file (and no cron exists)."""
        before = self._media_files_on_disk()
        with patch.object(MediaAsset, 'save', side_effect=RuntimeError('db down')):
            with self.assertRaises(RuntimeError):
                self._upload()
        self.assertEqual(MediaAsset.objects.count(), 0)
        self.assertEqual(self._media_files_on_disk(), before)


from jokes.submission_rules import validate_per_format


def _taxonomy():
    fmt, _ = Format.objects.get_or_create(slug='image', defaults={'name': 'Image'})
    age, _ = AgeRating.objects.get_or_create(slug='all-ages', defaults={'name': 'All Ages'})
    lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
    return fmt, age, lang


class ImageFormatRuleTests(TestCase):
    def test_image_requires_setup_and_media(self):
        errors = validate_per_format('image', {'setup': '', 'media': []})
        self.assertIn('setup', errors)
        self.assertIn('media', errors)

    def test_image_happy_path(self):
        errors = validate_per_format(
            'image',
            {'setup': 'caption', 'media': [{'kind': 'image', 'duration_ms': None}]},
        )
        self.assertEqual(errors, {})

    def test_image_rejects_punchline(self):
        errors = validate_per_format(
            'image',
            {
                'setup': 'caption', 'punchline': 'nope',
                'media': [{'kind': 'image', 'duration_ms': None}],
            },
        )
        self.assertIn('punchline', errors)

    def test_image_max_six_attachments(self):
        errors = validate_per_format(
            'image',
            {
                'setup': 'caption',
                'media': [{'kind': 'image', 'duration_ms': None}] * 7,
            },
        )
        self.assertIn('media', errors)

    def test_image_rejects_wrong_kind(self):
        errors = validate_per_format(
            'image',
            {'setup': 'caption', 'media': [{'kind': 'video', 'duration_ms': None}]},
        )
        self.assertIn('media', errors)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class ImageDraftFlowTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('imagecreator@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _make_draft(self):
        response = self.client.post('/api/v1/jokes/my-drafts/', {'format': 'image'})
        self.assertEqual(response.status_code, 201)
        return response.json()['id']

    def test_draft_patch_attaches_media_in_order(self):
        draft_id = self._make_draft()
        a1 = make_asset(self.user)
        a2 = make_asset(self.user)
        response = self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'setup': 'caption here', 'media_asset_ids': [str(a2.pk), str(a1.pk)]},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        draft = JokeSubmission.objects.get(pk=draft_id)
        self.assertEqual(
            [m.asset_id for m in draft.media.all()], [a2.pk, a1.pk]
        )

    def test_cannot_attach_someone_elses_asset(self):
        draft_id = self._make_draft()
        other = make_asset(make_user('other@example.com'))
        response = self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'media_asset_ids': [str(other.pk)]}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_submit_without_media_400(self):
        draft_id = self._make_draft()
        self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'setup': 'caption'}, format='json',
        )
        response = self.client.post(f'/api/v1/jokes/my-drafts/{draft_id}/submit/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('media', response.json())

    def test_submit_happy_path_backfills_text_from_setup(self):
        draft_id = self._make_draft()
        asset = make_asset(self.user)
        self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'setup': 'the caption', 'media_asset_ids': [str(asset.pk)]},
            format='json',
        )
        response = self.client.post(f'/api/v1/jokes/my-drafts/{draft_id}/submit/')
        self.assertEqual(response.status_code, 200)
        draft = JokeSubmission.objects.get(pk=draft_id)
        self.assertEqual(draft.status, 'pending')
        self.assertEqual(draft.text, 'the caption')

    def test_draft_list_includes_media(self):
        draft_id = self._make_draft()
        asset = make_asset(self.user)
        self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'media_asset_ids': [str(asset.pk)]}, format='json',
        )
        response = self.client.get('/api/v1/jokes/my-drafts/')
        rows = response.json()['results'] if 'results' in response.json() else response.json()
        row = next(r for r in rows if r['id'] == draft_id)
        self.assertEqual(len(row['media']), 1)
        self.assertEqual(row['media'][0]['kind'], 'image')

    def test_draft_delete_removes_solely_referenced_assets(self):
        draft_id = self._make_draft()
        asset = make_asset(self.user)
        self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'media_asset_ids': [str(asset.pk)]}, format='json',
        )
        name = asset.file.name
        response = self.client.delete(f'/api/v1/jokes/my-drafts/{draft_id}/')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(MediaAsset.objects.filter(pk=asset.pk).exists())
        self.assertFalse(default_storage.exists(name))


class TextBackfillScopeTests(TestCase):
    """Regression: the media-format setup-only text backfill must NOT fire
    for text formats. For a `setup`-format draft under autosave, a PATCH of
    just {setup} would set text = setup; the next PATCH of {punchline} then
    sees non-blank instance text and skips the backfill, freezing text at
    setup-only forever (corrupting search/share text after publish)."""

    def setUp(self):
        _taxonomy()
        Format.objects.get_or_create(
            slug='setup', defaults={'name': 'Setup-Punchline'},
        )
        self.user = make_user('backfill@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _make_draft(self, fmt):
        response = self.client.post('/api/v1/jokes/my-drafts/', {'format': fmt})
        self.assertEqual(response.status_code, 201)
        return response.json()['id']

    def test_setup_format_autosave_still_backfills_full_text(self):
        draft_id = self._make_draft('setup')
        response = self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'setup': 'Why?'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'punchline': 'Because.'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        draft = JokeSubmission.objects.get(pk=draft_id)
        self.assertEqual(draft.text, 'Why? Because.')

    def test_image_format_setup_patch_backfills_text(self):
        draft_id = self._make_draft('image')
        response = self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'setup': 'caption'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        draft = JokeSubmission.objects.get(pk=draft_id)
        self.assertEqual(draft.text, 'caption')


from rest_framework.test import APIRequestFactory

from jokes.paywall import PaywallState
from jokes.serializers import JokeListSerializer, JokeSerializer


def make_image_joke(user, setup='the caption'):
    fmt, age, lang = _taxonomy()
    with mock.patch('jokes.models.Joke._generate_share_image'):
        joke = Joke.objects.create(
            text=setup, setup=setup, format=fmt, age_rating=age, language=lang,
            creator=user,
        )
    asset = make_asset(user)
    JokeMedia.objects.create(joke=joke, asset=asset, position=0)
    return joke


def locked_state(consumed=frozenset()):
    return PaywallState(
        over=True, used=10, limit=10, remaining=0,
        consumed_ids=consumed, reset_at='2026-07-21T00:00:00+00:00',
    )


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class MediaLockingContractTests(TestCase):
    def setUp(self):
        self.user = make_user('lockme@example.com')
        self.joke = make_image_joke(self.user)
        self.request = APIRequestFactory().get('/api/v1/jokes/')

    def test_unlocked_serves_full_media(self):
        data = JokeSerializer(
            self.joke, context={'request': self.request}
        ).data
        self.assertEqual(len(data['media']), 1)
        item = data['media'][0]
        self.assertIn('url', item)
        self.assertTrue(item['url'])
        self.assertFalse(data['is_locked'])

    def test_locked_serves_dimensions_only(self):
        data = JokeSerializer(
            self.joke,
            context={'request': self.request, 'paywall_state': locked_state()},
        ).data
        self.assertTrue(data['is_locked'])
        item = data['media'][0]
        self.assertEqual(
            set(item.keys()), {'kind', 'width', 'height'}
        )
        self.assertEqual(data['setup'], 'the caption')  # teaser survives

    def test_consumed_joke_keeps_media(self):
        state = locked_state(consumed=frozenset({self.joke.id}))
        data = JokeSerializer(
            self.joke,
            context={'request': self.request, 'paywall_state': state},
        ).data
        self.assertFalse(data['is_locked'])
        self.assertIn('url', data['media'][0])

    def test_list_serializer_never_serves_urls(self):
        data = JokeListSerializer(
            self.joke, context={'request': self.request}
        ).data
        self.assertEqual(
            set(data['media'][0].keys()), {'kind', 'width', 'height'}
        )


# =============================================================================
# Task 6b: paywall_state context coverage across serving paths
#
# JokeSerializer._is_locked() silently returns False when `paywall_state` is
# absent from context. These tests prove that four serving paths inject it
# (mirroring CollectionViewSet.jokes / JokeViewSet.get_serializer_context /
# JokePackViewSet.get_serializer_context) so an over-cap free user gets a
# locked, stripped joke (and dims-only media) through EVERY surface — not
# just JokeViewSet.retrieve. DailyJokeViewSet is intentionally exempt and is
# untouched here.
# =============================================================================
from jokes.models import JokeView, SavedJoke
from jokes.paywall import FREE_READS_DEFAULT as FREE_CAP


def _filler_joke(n):
    """A distinct joke used purely to occupy the free-read ledger."""
    fmt, age, lang = _taxonomy()
    with mock.patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text=f'filler {n}', setup=f'filler {n}',
            format=fmt, age_rating=age, language=lang,
        )


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class PaywallContextCoverageTests(TestCase):
    def setUp(self):
        self.user = make_user('paywallcov@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _consume_cap(self, start=9000):
        """Seed FREE_CAP distinct JokeView rows for TODAY -> user is over cap."""
        for i in range(FREE_CAP):
            JokeView.objects.create(user=self.user, joke=_filler_joke(start + i))

    def _assert_locked_media_joke(self, joke_data):
        self.assertTrue(joke_data['is_locked'])
        self.assertIsNone(joke_data['punchline'])
        self.assertEqual(len(joke_data['media']), 1)
        self.assertNotIn('url', joke_data['media'][0])

    def test_favorites_list_and_create_lock_over_cap_joke(self):
        self._consume_cap()
        joke = make_image_joke(self.user, setup='fav target')

        create_resp = self.client.post('/api/v1/favorites/', {'joke': joke.id})
        self.assertEqual(create_resp.status_code, 201, create_resp.content)
        self._assert_locked_media_joke(create_resp.data['joke'])

        list_resp = self.client.get('/api/v1/favorites/')
        self.assertEqual(list_resp.status_code, 200, list_resp.content)
        results = list_resp.data.get('results', list_resp.data) if isinstance(list_resp.data, dict) else list_resp.data
        row = next(r for r in results if r['joke']['id'] == joke.id)
        self._assert_locked_media_joke(row['joke'])

    def test_saved_jokes_search_locks_over_cap_joke(self):
        self._consume_cap()
        joke = make_image_joke(self.user, setup='searchable unique caption zzzflarp')
        SavedJoke.objects.create(user=self.user, joke=joke)

        resp = self.client.get('/api/v1/saved-jokes/search/', {'q': 'zzzflarp'})
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.data.get('results', resp.data) if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(results), 1)
        self._assert_locked_media_joke(results[0]['joke'])

    def test_mystery_box_roll_locks_over_cap_joke(self):
        self._consume_cap()
        target = make_image_joke(self.user, setup='roll target')

        # Force the roll to pick `target` deterministically — the real pool
        # also contains unrelated seed/demo jokes from migrations, and which
        # one gets randomly picked is not what this test is about.
        with mock.patch(
            'jokes.views._mystery_pool_for_user',
            return_value=(Joke.objects.filter(pk=target.pk), None),
        ):
            resp = self.client.post('/api/v1/mystery-box/roll/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self._assert_locked_media_joke(resp.data['joke'])

    def test_recently_viewed_locks_over_cap_joke(self):
        self._consume_cap()
        target = make_image_joke(self.user, setup='recently viewed target')
        with freeze_time('2020-01-01 12:00:00'):
            # Viewed on a PAST day: shows up in recently-viewed history but is
            # not part of TODAY's consumed_ids ledger, so it stays lockable.
            JokeView.objects.create(user=self.user, joke=target)

        resp = self.client.get('/api/v1/users/me/recently-viewed/')
        self.assertEqual(resp.status_code, 200, resp.content)
        row = next(r for r in resp.data if r['joke']['id'] == target.id)
        self._assert_locked_media_joke(row['joke'])


from django.contrib.admin.sites import AdminSite

from jokes.admin import ContentReportAdmin, JokeSubmissionAdmin
from jokes.models import ContentReport


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class MediaPublishAndLifecycleTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('publisher@example.com')
        self.admin_user = User.objects.create_superuser(
            username='admin@example.com', email='admin@example.com', password='x',
        )
        self.factory = APIRequestFactory()

    def _pending_submission(self):
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt, age_rating=self.age,
            language=self.lang, setup='caption', text='caption', status='pending',
        )
        a1, a2 = make_asset(self.user), make_asset(self.user)
        JokeSubmissionMedia.objects.create(submission=sub, asset=a1, position=0)
        JokeSubmissionMedia.objects.create(submission=sub, asset=a2, position=1)
        return sub

    def _admin_request(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.middleware import SessionMiddleware
        request = self.factory.post('/admin/')
        request.user = self.admin_user
        SessionMiddleware(lambda r: None).process_request(request)
        request._messages = FallbackStorage(request)   # message_user() needs this
        return request

    def test_approve_and_publish_copies_media_in_order(self):
        sub = self._pending_submission()
        admin_obj = JokeSubmissionAdmin(JokeSubmission, AdminSite())
        # local machine lacks libcairo; share-image generation is out of scope here.
        with mock.patch('jokes.models.Joke._generate_share_image'):
            admin_obj.approve_and_publish(
                self._admin_request(), JokeSubmission.objects.filter(pk=sub.pk),
            )
        sub.refresh_from_db()
        joke = sub.published_joke
        self.assertIsNotNone(joke)
        self.assertEqual(
            [m.position for m in joke.media.all()], [0, 1]
        )
        self.assertEqual(
            [m.asset_id for m in joke.media.all()],
            [m.asset_id for m in sub.media.all()],
        )

    def test_takedown_quarantines_storage_files(self):
        # Appeals-wave Task 2 REWORK: takedown no longer hard-deletes media.
        # It quarantines it (reversible on appeal) — links are KEPT, rows
        # survive, and the files move to the quarantine/ path rather than
        # being deleted outright. (Was: test_takedown_deletes_storage_files,
        # which asserted files+rows gone; that contract no longer holds.)
        sub = self._pending_submission()
        admin_obj = JokeSubmissionAdmin(JokeSubmission, AdminSite())
        with mock.patch('jokes.models.Joke._generate_share_image'):
            admin_obj.approve_and_publish(
                self._admin_request(), JokeSubmission.objects.filter(pk=sub.pk),
            )
        sub.refresh_from_db()
        joke = sub.published_joke
        asset_ids = [m.asset_id for m in joke.media.all()]
        names = [m.asset.file.name for m in joke.media.all()]
        report = ContentReport.objects.create(
            reporter=self.admin_user, joke=joke, reason='inappropriate',
        )
        report_admin = ContentReportAdmin(ContentReport, AdminSite())
        report_admin.take_down_joke(
            self._admin_request(), ContentReport.objects.filter(pk=report.pk),
        )
        joke.refresh_from_db()
        self.assertTrue(joke.is_removed)
        # JokeMedia links are KEPT (needed to reverse on appeal).
        self.assertEqual(
            sorted(joke.media.values_list('asset_id', flat=True)), sorted(asset_ids),
        )
        # Old paths are gone, but the rows survive, quarantined.
        for name in names:
            self.assertFalse(default_storage.exists(name))
        self.assertEqual(MediaAsset.objects.filter(owner=self.user).count(), 2)
        for asset in MediaAsset.objects.filter(pk__in=asset_ids):
            self.assertIsNotNone(asset.quarantined_at)
            self.assertTrue(asset.file.name.startswith(f'quarantine/{asset.pk}/'))
            self.assertTrue(default_storage.exists(asset.file.name))

    def test_takedown_spares_assets_shared_with_live_jokes(self):
        # Cross-joke asset reuse is designed-for: taking down joke A must not
        # quarantine the shared image off unrelated live joke B. (Appeals-wave
        # Task 2 REWORK: the unshared asset is now quarantined, not deleted,
        # and A's JokeMedia links are KEPT rather than detached — was:
        # asserted link-detach + hard-delete of the unshared asset.)
        shared = make_asset(self.user)
        only_a = make_asset(self.user)
        with mock.patch('jokes.models.Joke._generate_share_image'):
            joke_a = Joke.objects.create(
                text='joke a', setup='joke a', format=self.fmt,
                age_rating=self.age, language=self.lang, creator=self.user,
            )
            joke_b = Joke.objects.create(
                text='joke b', setup='joke b', format=self.fmt,
                age_rating=self.age, language=self.lang, creator=self.user,
            )
        JokeMedia.objects.create(joke=joke_a, asset=shared, position=0)
        JokeMedia.objects.create(joke=joke_a, asset=only_a, position=1)
        JokeMedia.objects.create(joke=joke_b, asset=shared, position=0)
        shared_name = shared.file.name
        only_a_name = only_a.file.name

        report = ContentReport.objects.create(
            reporter=self.admin_user, joke=joke_a, reason='inappropriate',
        )
        report_admin = ContentReportAdmin(ContentReport, AdminSite())
        report_admin.take_down_joke(
            self._admin_request(), ContentReport.objects.filter(pk=report.pk),
        )

        # A's media rows are KEPT (needed to reverse on appeal); B's intact.
        self.assertEqual(
            list(JokeMedia.objects.filter(joke=joke_a).values_list('asset_id', flat=True)),
            [shared.pk, only_a.pk],
        )
        self.assertEqual(
            list(JokeMedia.objects.filter(joke=joke_b).values_list('asset_id', flat=True)),
            [shared.pk],
        )
        # Shared asset survives untouched — row, storage object, AND not
        # quarantined (still shared with live joke B).
        shared.refresh_from_db()
        self.assertTrue(MediaAsset.objects.filter(pk=shared.pk).exists())
        self.assertTrue(default_storage.exists(shared_name))
        self.assertIsNone(shared.quarantined_at)
        # A-only asset is quarantined — row survives, old path gone, new
        # quarantine path exists.
        only_a.refresh_from_db()
        self.assertTrue(MediaAsset.objects.filter(pk=only_a.pk).exists())
        self.assertIsNotNone(only_a.quarantined_at)
        self.assertFalse(default_storage.exists(only_a_name))
        self.assertTrue(default_storage.exists(only_a.file.name))

    def test_account_delete_removes_assets(self):
        asset = make_asset(self.user)
        name = asset.file.name
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.delete(
            '/api/v1/users/me/', {'password': 'x'}, format='json',
        )
        self.assertIn(response.status_code, (200, 204))
        self.assertFalse(MediaAsset.objects.filter(pk=asset.pk).exists())
        self.assertFalse(default_storage.exists(name))

    def test_account_delete_takes_down_emptied_media_jokes_but_spares_text(self):
        # Image joke: account delete strips the owner's MediaAsset rows, so a
        # published image-format joke would otherwise survive anonymized with
        # media: [] forever (caption over an empty box). It must be taken down.
        oneliner_fmt, _ = Format.objects.get_or_create(
            slug='oneliner', defaults={'name': 'One-liners'},
        )
        with mock.patch('jokes.models.Joke._generate_share_image'):
            image_joke = Joke.objects.create(
                text='img joke', setup='img joke', format=self.fmt,
                age_rating=self.age, language=self.lang, creator=self.user,
            )
            # Plain text joke: existing anonymized-survival policy is unchanged.
            text_joke = Joke.objects.create(
                text='plain text joke', format=oneliner_fmt,
                age_rating=self.age, language=self.lang, creator=self.user,
            )
        asset = make_asset(self.user)
        JokeMedia.objects.create(joke=image_joke, asset=asset, position=0)

        client = APIClient()
        client.force_authenticate(self.user)
        response = client.delete(
            '/api/v1/users/me/', {'password': 'x'}, format='json',
        )
        self.assertIn(response.status_code, (200, 204))

        image_joke = Joke.all_objects.get(pk=image_joke.pk)
        self.assertTrue(image_joke.is_removed)

        text_joke = Joke.all_objects.get(pk=text_joke.pk)
        self.assertFalse(text_joke.is_removed)
        self.assertIsNone(text_joke.creator_id)

    def test_data_export_lists_media_assets(self):
        make_asset(self.user)
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get('/api/v1/users/me/data-export/')
        self.assertEqual(response.status_code, 200)
        # ADAPTATION: DataExportView returns a zipped JSON attachment
        # (application/zip), not a raw JSON body — response.json() would
        # fail against the real contract. Unzip and parse the payload inside.
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        payload = json.loads(zf.read('jokes-for-data-export.json'))
        self.assertEqual(len(payload['media_assets']), 1)


# =============================================================================
# Task 8: Anonymous paywall — signed-cookie ledger + reveal endpoint
# =============================================================================

from jokes.paywall import (
    ANON_COOKIE_NAME,
    FREE_READS_DEFAULT,
)


def _seed_text_jokes(n):
    fmt, _ = Format.objects.get_or_create(slug='oneliner', defaults={'name': 'One-liner'})
    age, _ = AgeRating.objects.get_or_create(slug='all-ages', defaults={'name': 'All Ages'})
    lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
    # local machine lacks libcairo; share-image generation is out of scope here
    # (same workaround as make_image_joke / _filler_joke above).
    with mock.patch('jokes.models.Joke._generate_share_image'):
        return [
            Joke.objects.create(
                text=f'joke {i}', format=fmt, age_rating=age, language=lang,
            )
            for i in range(n)
        ]


class AnonPaywallTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.jokes = _seed_text_jokes(12)

    def _reveal(self, joke):
        return self.client.post(f'/api/v1/jokes/{joke.pk}/reveal/')

    def test_reveal_consumes_and_reports_state(self):
        response = self._reveal(self.jokes[0])
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['used'], 1)
        self.assertEqual(body['limit'], FREE_READS_DEFAULT)
        self.assertFalse(body['over'])
        self.assertIn(ANON_COOKIE_NAME, response.cookies)

    def test_over_cap_locks_new_jokes_but_not_consumed_ones(self):
        for joke in self.jokes[:10]:
            self._reveal(joke)
        listing = self.client.get('/api/v1/jokes/')
        rows = listing.json()['results']
        by_id = {row['id']: row for row in rows}
        consumed_id = self.jokes[0].pk
        fresh_id = self.jokes[11].pk
        if consumed_id in by_id:
            self.assertFalse(by_id[consumed_id]['is_locked'])
        if fresh_id in by_id:
            self.assertTrue(by_id[fresh_id]['is_locked'])

    def test_reveal_when_over_does_not_extend(self):
        for joke in self.jokes[:10]:
            self._reveal(joke)
        response = self._reveal(self.jokes[11])
        body = response.json()
        self.assertTrue(body['over'])
        self.assertEqual(body['used'], 10)

    def test_tampered_cookie_resets_ledger(self):
        self._reveal(self.jokes[0])
        self.client.cookies[ANON_COOKIE_NAME] = 'tampered-garbage'
        response = self._reveal(self.jokes[1])
        self.assertEqual(response.json()['used'], 1)

    def test_midnight_utc_reset(self):
        with freeze_time('2026-07-20 23:30:00'):
            for joke in self.jokes[:10]:
                self._reveal(joke)
            self.assertTrue(self._reveal(self.jokes[10]).json()['over'])
        with freeze_time('2026-07-21 00:30:00'):
            response = self._reveal(self.jokes[10])
            self.assertEqual(response.json()['used'], 1)
            self.assertFalse(response.json()['over'])

    def test_authenticated_caller_gets_204_noop(self):
        user = make_user('authed@example.com')
        self.client.force_authenticate(user)
        response = self._reveal(self.jokes[0])
        self.assertEqual(response.status_code, 204)

    def test_anon_detail_get_consumes(self):
        response = self.client.get(f'/api/v1/jokes/{self.jokes[0].pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(ANON_COOKIE_NAME, response.cookies)

    def test_daily_reads_reports_anon_state(self):
        self._reveal(self.jokes[0])
        response = self.client.get('/api/v1/jokes/daily-reads/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['used'], 1)
        self.assertEqual(response.json()['limit'], FREE_READS_DEFAULT)
