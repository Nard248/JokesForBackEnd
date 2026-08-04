"""
Tests for the public joke share page (jokes.views.joke_share_page,
GET /jokes/<pk>/share/).

Scope: the decoupled social-share shell -- real per-joke OG/Twitter/JSON-LD
metadata for scrapers, plus a redirect (meta-refresh + JS) that bounces a
human visitor straight to the SPA's own joke page. Tier-gating behavior
(anon/minor tier_2 -> 200 content-free redirect shell, opted-in adult
tier_2 -> 200 full preview) is already covered by
jokes.tests_compliance.ServingLockTests and is untouched here -- all jokes
in this file are tier_1 (always accessible), so full metadata always renders.
"""
import json
import re

from django.test import TestCase, override_settings

from jokes.models import AgeRating, Format, Joke, Language

_FRONTEND_URL = 'https://jokesforfront.web.app'


def _taxonomy():
    fmt, _ = Format.objects.get_or_create(slug='oneliner', defaults={'name': 'One-liner'})
    age, _ = AgeRating.objects.get_or_create(slug='all-ages', defaults={'name': 'All Ages'})
    lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
    return fmt, age, lang


def _extract_meta_content(html, *, property_=None, name=None):
    """Pull the content="..." value off a <meta property=... /> or
    <meta name=... /> tag. Returns None if the tag isn't present."""
    attr, value = ('property', property_) if property_ else ('name', name)
    pattern = rf'<meta {attr}="{re.escape(value)}" content="([^"]*)"'
    match = re.search(pattern, html)
    return match.group(1) if match else None


def _extract_json_ld(html):
    match = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL,
    )
    assert match, 'no JSON-LD <script> block found in share page HTML'
    return json.loads(match.group(1))


@override_settings(FRONTEND_URL=_FRONTEND_URL)
class SharePageMetadataTests(TestCase):
    """Real per-joke metadata: og:image, og:url/canonical, description
    teaser (no punchline spoiler), redirect targets, JSON-LD."""

    @classmethod
    def setUpTestData(cls):
        fmt, age, lang = _taxonomy()

        # Two-part joke: description must come from `setup` and must never
        # leak `punchline`. Real card generation runs (not mocked) so
        # `share_image` is actually populated -- this test asserts on it.
        cls.joke = Joke.objects.create(
            text='Why did the chicken cross the road? To get to the other side, obviously.',
            setup='Why did the chicken cross the road?',
            punchline='To get to the other side, obviously.',
            format=fmt,
            age_rating=age,
            language=lang,
            content_tier='tier_1',
        )

        # Text-only joke (no setup): description must fall back to `text`.
        cls.text_only_joke = Joke.objects.create(
            text='I told a chemistry joke. No reaction.',
            format=fmt,
            age_rating=age,
            language=lang,
            content_tier='tier_1',
        )

    def _get(self, joke):
        resp = self.client.get(f'/jokes/{joke.id}/share/')
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode('utf-8')

    def test_og_image_is_share_image(self):
        html = self._get(self.joke)
        self.joke.refresh_from_db()
        self.assertTrue(self.joke.share_image, 'expected share_image to be generated')
        og_image = _extract_meta_content(html, property_='og:image')
        self.assertIsNotNone(og_image)
        self.assertIn(self.joke.share_image.name.rsplit('/', 1)[-1], og_image)
        twitter_image = _extract_meta_content(html, name='twitter:image')
        self.assertEqual(og_image, twitter_image)

    def test_og_url_and_canonical_point_at_frontend_not_backend(self):
        html = self._get(self.joke)
        expected = f'{_FRONTEND_URL}/jokes/{self.joke.id}'

        og_url = _extract_meta_content(html, property_='og:url')
        self.assertEqual(og_url, expected)

        canonical_match = re.search(r'<link rel="canonical" href="([^"]*)"', html)
        self.assertIsNotNone(canonical_match, 'expected a <link rel="canonical"> tag')
        self.assertEqual(canonical_match.group(1), expected)

        # Must NOT be the backend's own share URL.
        self.assertNotIn(f'/jokes/{self.joke.id}/share/', og_url)

    def test_title_uses_setup_teaser_and_never_punchline(self):
        html = self._get(self.joke)
        og_title = _extract_meta_content(html, property_='og:title')
        twitter_title = _extract_meta_content(html, name='twitter:title')

        self.assertEqual(og_title, self.joke.setup)
        self.assertEqual(twitter_title, self.joke.setup)
        self.assertNotIn(self.joke.punchline, og_title)
        self.assertNotIn(self.joke.punchline, twitter_title)

        data = _extract_json_ld(html)
        self.assertEqual(data['name'], self.joke.setup)
        self.assertEqual(data['headline'], self.joke.setup)
        self.assertNotIn(self.joke.punchline, data['name'])

    def test_title_falls_back_to_text_when_no_setup(self):
        html = self._get(self.text_only_joke)
        og_title = _extract_meta_content(html, property_='og:title')
        self.assertEqual(og_title, self.text_only_joke.text)

    def test_description_uses_setup_teaser_and_never_punchline(self):
        html = self._get(self.joke)
        og_description = _extract_meta_content(html, property_='og:description')
        twitter_description = _extract_meta_content(html, name='twitter:description')

        self.assertEqual(og_description, self.joke.setup)
        self.assertEqual(twitter_description, self.joke.setup)
        self.assertNotIn(self.joke.punchline, og_description)
        self.assertNotIn(self.joke.punchline, twitter_description)
        self.assertNotIn('JokesFor.com', html)

    def test_description_falls_back_to_text_when_no_setup(self):
        html = self._get(self.text_only_joke)
        og_description = _extract_meta_content(html, property_='og:description')
        self.assertEqual(og_description, self.text_only_joke.text)

    def test_redirect_meta_refresh_and_script_target_frontend(self):
        html = self._get(self.joke)
        expected = f'{_FRONTEND_URL}/jokes/{self.joke.id}'

        refresh_match = re.search(
            r'<meta http-equiv="refresh" content="0; url=([^"]*)"', html,
        )
        self.assertIsNotNone(refresh_match, 'expected a meta-refresh redirect tag')
        self.assertEqual(refresh_match.group(1), expected)

        self.assertIn('location.replace(', html)
        self.assertIn(expected, html)

    def test_json_ld_present_and_valid(self):
        html = self._get(self.joke)
        data = _extract_json_ld(html)

        self.assertEqual(data['@context'], 'https://schema.org')
        self.assertEqual(data['@type'], 'CreativeWork')
        self.assertEqual(data['url'], f'{_FRONTEND_URL}/jokes/{self.joke.id}')
        self.assertEqual(data['author'], {'@type': 'Organization', 'name': 'JokesFor'})
        # No fabricated individual creator identity.
        self.assertNotEqual(data['author'].get('@type'), 'Person')
        self.joke.refresh_from_db()
        self.assertIn(self.joke.share_image.name.rsplit('/', 1)[-1], data['image'])

    def test_json_ld_escapes_special_characters_safely(self):
        """A joke containing `</script>`/`&`/quotes must not break out of the
        JSON-LD <script> tag."""
        fmt, age, lang = _taxonomy()
        joke = Joke.objects.create(
            text='A "tricky" joke with </script> & <b>tags</b> in it',
            setup='A "tricky" setup with </script> & <b>tags</b>',
            punchline='harmless punchline',
            format=fmt, age_rating=age, language=lang, content_tier='tier_1',
        )
        html = self._get(joke)
        data = _extract_json_ld(html)  # json.loads succeeding is the main proof
        self.assertIn('tricky', data['name'])
