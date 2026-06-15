from unittest.mock import patch

from django.conf import settings
from django.core.files.base import ContentFile
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from jokes.models import AgeRating, Format, Joke, Language
from jokes.serializers import JokeSerializer
from JokesForProject.settings import build_default_storage


def _get_or_create_fixtures():
    """Return (format, age_rating, language) fixtures, creating them if absent."""
    fmt, _ = Format.objects.get_or_create(
        slug='oneliner', defaults={'name': 'One-liner'}
    )
    age, _ = AgeRating.objects.get_or_create(
        slug='all-ages', defaults={'name': 'All Ages'}
    )
    lang, _ = Language.objects.get_or_create(
        code='en', defaults={'name': 'English'}
    )
    return fmt, age, lang


class StorageBackendSelectionTests(TestCase):
    """STORAGES['default'] switches by GS_BUCKET_NAME env."""

    def test_local_default_is_filesystem(self):
        cfg = build_default_storage(bucket_name='')
        self.assertEqual(
            cfg['BACKEND'],
            'django.core.files.storage.FileSystemStorage',
        )

    def test_gcs_default_when_bucket_set(self):
        cfg = build_default_storage(bucket_name='jokesfor-media-prod')
        self.assertEqual(
            cfg['BACKEND'],
            'storages.backends.gcloud.GoogleCloudStorage',
        )
        opts = cfg['OPTIONS']
        self.assertEqual(opts['bucket_name'], 'jokesfor-media-prod')
        # Public, uniform-access bucket -> stable non-expiring URLs.
        self.assertIsNone(opts['default_acl'])
        self.assertFalse(opts['querystring_auth'])

    def test_media_url_defined(self):
        self.assertTrue(settings.MEDIA_URL)


class ShareImageUrlAbsoluteTests(TestCase):
    """share_image_url is always an absolute URL (local FS mode)."""

    @patch('jokes.models.Joke._generate_share_image')
    def _make_joke_with_image(self, _mock_img):
        fmt, age, lang = _get_or_create_fixtures()
        joke = Joke.objects.create(
            text='Absolute url test joke.', format=fmt, age_rating=age, language=lang
        )
        # Attach a fake file through the *default* storage (FS in tests).
        joke.share_image.save(
            f'joke-{joke.pk}.png', ContentFile(b'PNGDATA'), save=True
        )
        return joke

    def test_share_image_url_is_absolute(self):
        joke = self._make_joke_with_image()
        request = APIRequestFactory().get('/api/v1/jokes/')
        data = JokeSerializer(joke, context={'request': request}).data
        url = data['share_image_url']
        self.assertIsNotNone(url)
        self.assertTrue(
            url.startswith('http://') or url.startswith('https://'),
            f'expected absolute URL, got {url!r}',
        )
        self.assertIn('joke-%d.png' % joke.pk, url)


class ShareCardRegenerationTests(TestCase):
    """Joke.save() still routes the generated PNG through default storage."""

    def test_regeneration_saves_via_storage(self):
        fmt, age, lang = _get_or_create_fixtures()

        # Patch _generate_share_image to write deterministic bytes into the
        # share_image field via the real default storage, without calling cairosvg
        # (which requires system Cairo libs not present in CI/local dev).
        def fake_generate(self_joke):
            filename = f'joke-{self_joke.pk}.png'
            self_joke.share_image.save(
                filename, ContentFile(b'PNGDATA'), save=False
            )

        with patch('jokes.models.Joke._generate_share_image', fake_generate):
            joke = Joke.objects.create(
                text='Regen path joke.', format=fmt, age_rating=age, language=lang
            )
        joke.refresh_from_db()
        self.assertTrue(joke.share_image)
        self.assertTrue(joke.share_image.name.endswith(f'joke-{joke.pk}.png'))
        self.assertEqual(joke.share_image.read(), b'PNGDATA')
