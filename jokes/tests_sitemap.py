"""Tests for the public /sitemap.xml endpoint (jokes/sitemap.py).

Covers: response shape (200/content-type/well-formed XML against the
sitemap 0.9 namespace), every <loc> being an absolute frontend URL (never
this backend's own host), static routes, and -- the leakage guard -- that
a removed joke, a tier_2/tier_3 joke, and a creator with no public tier_1
joke never make it into the sitemap.
"""
from unittest.mock import patch

import defusedxml.ElementTree as ET
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from jokes.models import AgeRating, Format, Joke, JokePack, Language

User = get_user_model()

_NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
_FRONTEND_URL = 'https://jokesforfront.web.app'


def _taxonomy():
    fmt, _ = Format.objects.get_or_create(slug='oneliner', defaults={'name': 'One-liner'})
    age, _ = AgeRating.objects.get_or_create(slug='all-ages', defaults={'name': 'All Ages'})
    lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
    return fmt, age, lang


def _make_user(email):
    return User.objects.create_user(username=email, email=email, password='x')


def _make_joke(fmt, age, lang, text='Test joke', content_tier='tier_1',
               creator=None, is_removed=False):
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text=text, format=fmt, age_rating=age, language=lang,
            content_tier=content_tier, creator=creator, is_removed=is_removed,
        )


@override_settings(FRONTEND_URL=_FRONTEND_URL)
class SitemapViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fmt, cls.age, cls.lang = _taxonomy()
        cls.creator = _make_user('sitemap_creator@test.com')

        # Publicly-visible joke: tier_1, not removed, attributed creator.
        cls.public_joke = _make_joke(
            cls.fmt, cls.age, cls.lang, text='Public joke',
            content_tier='tier_1', creator=cls.creator,
        )

        # Leakage guards: none of these three should ever appear.
        cls.removed_joke = _make_joke(
            cls.fmt, cls.age, cls.lang, text='Removed joke',
            content_tier='tier_1', creator=cls.creator, is_removed=True,
        )
        cls.tier2_joke = _make_joke(
            cls.fmt, cls.age, cls.lang, text='Tier2 joke',
            content_tier='tier_2', creator=cls.creator,
        )
        cls.tier3_joke = _make_joke(
            cls.fmt, cls.age, cls.lang, text='Tier3 joke',
            content_tier='tier_3', creator=cls.creator,
        )

        # A user with zero public jokes -- not a "creator" for sitemap purposes.
        cls.bare_user = _make_user('bare_user@test.com')

        cls.pack = JokePack.objects.create(
            slug='public-pack', title='Public Pack', is_published=True,
        )
        cls.unpublished_pack = JokePack.objects.create(
            slug='draft-pack', title='Draft Pack', is_published=False,
        )
        cls.future_pack = JokePack.objects.create(
            slug='future-pack', title='Future Pack', is_published=True,
            publish_at=timezone.now() + timezone.timedelta(days=7),
        )
        cls.expired_pack = JokePack.objects.create(
            slug='expired-pack', title='Expired Pack', is_published=True,
            expires_at=timezone.now() - timezone.timedelta(days=1),
        )

    def setUp(self):
        self.response = self.client.get(reverse('sitemap'))
        self.root = ET.fromstring(self.response.content)
        self.locs = {
            el.text for el in self.root.findall('sm:url/sm:loc', _NS)
        }

    # -- response shape ------------------------------------------------------

    def test_status_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_content_type_is_xml(self):
        self.assertEqual(self.response['Content-Type'], 'application/xml')

    def test_well_formed_urlset_namespace(self):
        self.assertEqual(self.root.tag, '{http://www.sitemaps.org/schemas/sitemap/0.9}urlset')

    def test_every_loc_is_absolute_frontend_url(self):
        self.assertTrue(self.locs, 'expected at least one <loc>')
        for loc in self.locs:
            self.assertTrue(
                loc.startswith(_FRONTEND_URL + '/') or loc == _FRONTEND_URL,
                f'{loc!r} is not an absolute {_FRONTEND_URL} URL',
            )
            self.assertNotIn('localhost', loc)
            self.assertNotIn('run.app', loc)

    # -- static routes --------------------------------------------------------

    def test_static_routes_present(self):
        expected = {
            f'{_FRONTEND_URL}{path}' for path in (
                '/', '/daily', '/trending', '/privacy', '/terms',
                '/cookie-policy', '/childrens-privacy',
            )
        }
        self.assertTrue(expected.issubset(self.locs))

    # -- jokes ------------------------------------------------------------

    def test_public_joke_included(self):
        self.assertIn(f'{_FRONTEND_URL}/jokes/{self.public_joke.id}', self.locs)

    def test_public_joke_has_lastmod(self):
        url_el = next(
            el for el in self.root.findall('sm:url', _NS)
            if el.find('sm:loc', _NS).text == f'{_FRONTEND_URL}/jokes/{self.public_joke.id}'
        )
        lastmod = url_el.find('sm:lastmod', _NS)
        self.assertIsNotNone(lastmod)
        self.assertEqual(lastmod.text, self.public_joke.updated_at.date().isoformat())

    def test_removed_joke_excluded(self):
        self.assertNotIn(f'{_FRONTEND_URL}/jokes/{self.removed_joke.id}', self.locs)

    def test_tier2_joke_excluded(self):
        self.assertNotIn(f'{_FRONTEND_URL}/jokes/{self.tier2_joke.id}', self.locs)

    def test_tier3_joke_excluded(self):
        self.assertNotIn(f'{_FRONTEND_URL}/jokes/{self.tier3_joke.id}', self.locs)

    # -- creators --------------------------------------------------------

    def test_public_creator_included(self):
        self.assertIn(f'{_FRONTEND_URL}/creators/{self.creator.id}', self.locs)

    def test_creator_with_no_public_jokes_excluded(self):
        self.assertNotIn(f'{_FRONTEND_URL}/creators/{self.bare_user.id}', self.locs)

    def test_creator_appears_only_once(self):
        """The creator has 4 jokes (1 tier_1 + removed + tier_2 + tier_3);
        their profile URL must still appear exactly once (distinct())."""
        count = sum(
            1 for loc in self.locs if loc == f'{_FRONTEND_URL}/creators/{self.creator.id}'
        )
        self.assertEqual(count, 1)

    # -- packs -------------------------------------------------------------

    def test_published_pack_included(self):
        self.assertIn(f'{_FRONTEND_URL}/packs/{self.pack.slug}', self.locs)

    def test_published_pack_has_lastmod(self):
        url_el = next(
            el for el in self.root.findall('sm:url', _NS)
            if el.find('sm:loc', _NS).text == f'{_FRONTEND_URL}/packs/{self.pack.slug}'
        )
        lastmod = url_el.find('sm:lastmod', _NS)
        self.assertIsNotNone(lastmod)

    def test_unpublished_pack_excluded(self):
        self.assertNotIn(f'{_FRONTEND_URL}/packs/{self.unpublished_pack.slug}', self.locs)

    def test_future_publish_at_pack_excluded(self):
        self.assertNotIn(f'{_FRONTEND_URL}/packs/{self.future_pack.slug}', self.locs)

    def test_expired_pack_excluded(self):
        self.assertNotIn(f'{_FRONTEND_URL}/packs/{self.expired_pack.slug}', self.locs)
