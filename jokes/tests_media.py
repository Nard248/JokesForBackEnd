"""Tests for media jokes (Wave 1): assets, pipeline, formats, locking, anon paywall."""
import io
import shutil
import tempfile
import uuid

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from jokes.models import (
    AgeRating, Format, Joke, JokeMedia, JokeSubmission, JokeSubmissionMedia,
    Language, MediaAsset,
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
