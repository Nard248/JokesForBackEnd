"""Test the backfill_share_cards management command."""
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import TestCase, override_settings

from jokes.models import AgeRating, Format, Joke, Language

_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class BackfillShareCardsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.fmt, _ = Format.objects.get_or_create(slug='oneliner', defaults={'name': 'One-liner'})
        self.age, _ = AgeRating.objects.get_or_create(slug='all-ages', defaults={'name': 'All Ages'})
        self.lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})

    def _cardless_joke(self, text='a backfill joke', removed=False):
        # Bypass save()'s card generation the way bulk seed does, to create a
        # genuinely card-less row.
        with patch('jokes.models.Joke._generate_share_image'):
            joke = Joke.objects.create(
                text=text, format=self.fmt, age_rating=self.age, language=self.lang,
            )
        Joke.all_objects.filter(pk=joke.pk).update(
            share_image='', is_removed=removed,
        )
        joke.refresh_from_db()
        return joke

    def test_dry_run_reports_but_does_not_write(self):
        joke = self._cardless_joke()
        out = StringIO()
        call_command('backfill_share_cards', stdout=out)
        self.assertIn('missing a share card', out.getvalue())
        self.assertIn('Dry run', out.getvalue())
        joke.refresh_from_db()
        self.assertFalse(joke.share_image)  # unchanged

    def test_apply_regenerates_live_cardless_jokes(self):
        joke = self._cardless_joke()
        out = StringIO()
        call_command('backfill_share_cards', '--apply', stdout=out)
        joke.refresh_from_db()
        self.assertTrue(joke.share_image)
        self.assertTrue(default_storage.exists(joke.share_image.name))

    def test_never_touches_removed_jokes(self):
        removed = self._cardless_joke(text='removed one', removed=True)
        call_command('backfill_share_cards', '--apply', stdout=StringIO())
        removed.refresh_from_db()
        # Joke.objects (the command's queryset) excludes removed jokes, so a
        # taken-down joke is never given a card — mirrors the share-cards
        # wave's is_removed guard.
        self.assertFalse(removed.share_image)

    def test_apply_is_idempotent(self):
        self._cardless_joke()
        call_command('backfill_share_cards', '--apply', stdout=StringIO())
        out = StringIO()
        call_command('backfill_share_cards', stdout=out)  # dry run again
        self.assertIn('0 live joke(s) missing', out.getvalue())
