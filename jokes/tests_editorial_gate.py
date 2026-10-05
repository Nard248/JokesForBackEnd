"""Editorial publication gate: a held joke ('generated') is invisible on every surface.

Also covers the human-first ordering of AI-screened content, the share-page
SEO rules for AI-authored jokes and the origin_country contract.
"""
import io
import json
import zipfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from jokes.models import (
    AgeRating,
    Collection,
    ContextTag,
    Country,
    CultureTag,
    DailyJoke,
    Favorite,
    Format,
    Joke,
    JokePack,
    JokePackEntry,
    JokeRating,
    JokeView,
    Language,
    SavedJoke,
    Tone,
)

User = get_user_model()


def _rows(response):
    data = response.data
    return data['results'] if isinstance(data, dict) and 'results' in data else data


def _ids(response):
    return {row['id'] for row in _rows(response)}


def _nested_ids(response):
    return {row['joke']['id'] for row in _rows(response)}


class GateFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fmt = Format.objects.get(slug='oneliner')
        cls.age = AgeRating.objects.order_by('min_age').first()
        cls.en = Language.objects.get(code='en')
        cls.de = Language.objects.get(code='de')
        cls.germany = Country.objects.get(code='DE')
        cls.reader = User.objects.create_user(username='reader@t.com', email='reader@t.com', password='x')
        cls.creator = User.objects.create_user(username='maker@t.com', email='maker@t.com', password='x')
        cls.human = cls.make('Zebracrossing human joke', status='legacy')
        cls.screened = cls.make('Zebracrossing screened joke', status='ai_screened', origin=cls.germany)
        cls.held = cls.make('Zebracrossing held joke', status='generated', origin=cls.germany)

    @classmethod
    def make(cls, text, status='legacy', language=None, origin=None, creator=None, tier='tier_1'):
        with patch('jokes.models.Joke._generate_share_image'):
            return Joke.all_objects.create(
                text=text, format=cls.fmt, age_rating=cls.age, language=language or cls.en,
                content_tier=tier, editorial_status=status, origin_country=origin, creator=creator,
            )

    def client_for(self, user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client


class ManagerGateTests(GateFixture):
    def test_default_manager_hides_held_and_unknown_statuses(self):
        self.assertFalse(Joke.objects.filter(pk=self.held.pk).exists())
        self.assertTrue(Joke.all_objects.filter(pk=self.held.pk).exists())
        self.assertTrue(Joke.objects.filter(pk=self.screened.pk).exists())
        # Fail-closed: a status nobody added to the published allow-list is held.
        Joke.all_objects.filter(pk=self.human.pk).update(editorial_status='future_status')
        self.assertFalse(Joke.objects.filter(pk=self.human.pk).exists())

    def test_reverse_relations_inherit_the_gate(self):
        tag = ContextTag.objects.create(name='Gatetag', slug='gatetag')
        tag.jokes.add(self.human, self.held)
        self.assertEqual(set(tag.jokes.values_list('pk', flat=True)), {self.human.pk})

    def test_held_joke_save_never_renders_a_public_share_card(self):
        held = Joke.all_objects.get(pk=self.held.pk)
        with patch('jokes.models.Joke._generate_share_image') as render:
            held.text = 'Edited held text'
            held.save()
            held.regenerate_share_image()
        render.assert_not_called()


class ReadSurfaceTests(GateFixture):
    def test_list_search_and_retrieve(self):
        tag = ContextTag.objects.create(name='Listtag', slug='listtag')
        tag.jokes.through.objects.bulk_create([
            tag.jokes.through(joke_id=j.pk, contexttag_id=tag.pk)
            for j in (self.human, self.screened, self.held)
        ])
        client = self.client_for()
        listed = _ids(client.get('/api/v1/jokes/', {'language': 'all', 'themes': 'listtag'}))
        self.assertEqual(listed, {self.human.pk, self.screened.pk})
        found = _ids(client.get('/api/v1/jokes/', {'q': 'zebracrossing'}))
        self.assertEqual(found, {self.human.pk, self.screened.pk})
        self.assertEqual(client.get(f'/api/v1/jokes/{self.held.pk}/').status_code, 404)
        self.assertEqual(client.get(f'/api/v1/jokes/{self.screened.pk}/').status_code, 200)

    def test_random_and_anonymous_daily_never_serve_held(self):
        Joke.all_objects.exclude(pk=self.held.pk).update(is_removed=True)
        client = self.client_for()
        self.assertEqual(client.get('/api/v1/jokes/random/', {'language': 'all'}).status_code, 404)
        self.assertEqual(client.get('/api/v1/daily-jokes/today/', {'language': 'all'}).status_code, 404)

    def test_authenticated_daily_never_serves_held(self):
        Joke.all_objects.exclude(pk=self.held.pk).update(is_removed=True)
        response = self.client_for(self.reader).get('/api/v1/daily-jokes/today/', {'language': 'all'})
        self.assertEqual(response.status_code, 404)

    def test_trending_ignores_engagement_on_held_jokes(self):
        JokeRating.objects.create(user=self.reader, joke=self.held, rating=1)
        JokeRating.objects.create(user=self.reader, joke=self.human, rating=1)
        response = self.client_for().get('/api/v1/jokes/trending/', {'language': 'all'})
        ids = {row['joke']['id'] for row in _rows(response)}
        self.assertEqual(ids, {self.human.pk})

    def test_discovery_locale_counts_exclude_held(self):
        culture = CultureTag.objects.get(slug='germany-everyday')
        for joke in (self.screened, self.held):
            Joke.all_objects.filter(pk=joke.pk).update(language=self.de)
            joke.countries.add(self.germany)
            joke.culture_tags.add(culture)
        response = self.client_for().get('/api/v1/discovery-locales/')
        collection = next(c for c in response.data['collections'] if c['locale'] == 'de-DE')
        self.assertEqual(collection['joke_count'], 1)

    def test_personal_libraries_and_histories_drop_a_held_joke(self):
        collection = Collection.objects.create(user=self.reader, name='Mine')
        for joke in (self.human, self.held):
            SavedJoke.objects.create(user=self.reader, joke=joke, collection=collection)
            Favorite.objects.create(user=self.reader, joke=joke)
            JokeView.objects.create(user=self.reader, joke=joke)
        DailyJoke.objects.create(user=self.reader, joke=self.human, date=timezone.now().date())
        DailyJoke.objects.create(user=self.reader, joke=self.held,
                                 date=timezone.now().date() - timedelta(days=1))
        client = self.client_for(self.reader)
        self.assertEqual(_nested_ids(client.get('/api/v1/saved-jokes/')), {self.human.pk})
        self.assertEqual(_nested_ids(client.get(f'/api/v1/collections/{collection.pk}/jokes/')),
                         {self.human.pk})
        self.assertEqual(_nested_ids(client.get('/api/v1/favorites/')), {self.human.pk})
        self.assertEqual(_nested_ids(client.get('/api/v1/users/me/recently-viewed/')), {self.human.pk})
        history = client.get('/api/v1/daily-jokes/history/', {'language': 'all'})
        self.assertEqual({row['joke']['id'] for row in history.data}, {self.human.pk})
        self.assertEqual(client.get('/api/v1/favorites/stats/').data['total_count'], 1)
        activity = client.get('/api/v1/users/me/activity/', {'limit': 50}).data['results']
        self.assertFalse(any('held joke' in row['description'] for row in activity))

    def test_pack_detail_and_count_drop_a_held_joke(self):
        pack = JokePack.objects.create(slug='gate-pack', title='Gate', is_published=True)
        JokePackEntry.objects.create(pack=pack, joke=self.human, order=0)
        JokePackEntry.objects.create(pack=pack, joke=self.held, order=1)
        client = self.client_for()
        detail = client.get('/api/v1/packs/gate-pack/')
        self.assertEqual([row['joke']['id'] for row in detail.data['jokes']], [self.human.pk])
        self.assertEqual(detail.data['joke_count'], 1)

    def test_tag_aggregates_ignore_held_jokes(self):
        tone = Tone.objects.create(name='Heldtone', slug='heldtone')
        self.held.tones.add(tone)
        JokeRating.objects.create(user=self.reader, joke=self.held, rating=1)
        trending = self.client_for().get('/api/v1/tags/trending/').data['results']
        self.assertNotIn('heldtone', {row['slug'] for row in trending})
        tag = ContextTag.objects.create(name='Heldtheme', slug='heldtheme')
        held_rows = Joke.all_objects.bulk_create([
            Joke(text=f'held theme {i}', format=self.fmt, age_rating=self.age, language=self.en,
                 editorial_status='generated') for i in range(60)
        ])
        tag.jokes.through.objects.bulk_create(
            [tag.jokes.through(joke_id=j.pk, contexttag_id=tag.pk) for j in held_rows])
        self.assertNotIn('Heldtheme', self.client_for().get('/api/v1/themes/popular/').data['results'])

    def test_recommendation_helpers(self):
        from jokes.recommendations import get_daily_editorial_joke, get_personalized_joke
        DailyJoke.objects.create(user=self.reader, joke=self.held, date=timezone.now().date())
        self.assertIsNone(get_daily_editorial_joke())
        Joke.all_objects.exclude(pk=self.held.pk).update(is_removed=True)
        self.assertIsNone(get_personalized_joke(self.creator))

    def test_creator_insights_scope_excludes_held(self):
        from creator_insights.services import resolve_creator_jokes
        Joke.all_objects.filter(pk__in=[self.human.pk, self.held.pk]).update(creator=self.creator)
        self.assertEqual(set(resolve_creator_jokes(self.creator).values_list('pk', flat=True)),
                         {self.human.pk})

    def test_data_export_omits_held_saved_jokes(self):
        SavedJoke.objects.create(user=self.reader, joke=self.human)
        SavedJoke.objects.create(user=self.reader, joke=self.held)
        response = self.client_for(self.reader).get('/api/v1/users/me/data-export/')
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            body = json.loads(archive.read('jokes-for-data-export.json'))
        self.assertEqual({row['joke_id'] for row in body['saved_jokes']}, {self.human.pk})


@override_settings(COMMUNITIES_MIN_REFRESH_SECONDS=0, COMMUNITIES_NOISE_EPSILON=0)
class CommunityGateTests(GateFixture):
    def test_community_joke_count_and_signals_ignore_held(self):
        from communities import services
        from communities.models import Community
        cache.clear()
        tag = ContextTag.objects.create(name='Gate theme', slug='gate-theme')
        self.human.context_tags.add(tag)
        self.held.context_tags.add(tag)
        community = Community.objects.get(tag=tag)
        rows = services.compute_aggregate(timezone.now())['rows']
        self.assertEqual(rows[community.pk]['joke_count'], 1)
        Favorite.objects.create(user=self.reader, joke=self.held)
        signals = services.signal_rows(timezone.now() - timedelta(days=1))
        self.assertFalse(signals.filter(joke=self.held).exists())


@override_settings(FRONTEND_URL='https://front.example')
class ShareAndSitemapTests(GateFixture):
    def test_share_page_held_404_screened_noindex_with_language(self):
        Joke.all_objects.filter(pk=self.screened.pk).update(language=self.de)
        self.assertEqual(self.client.get(f'/jokes/{self.held.pk}/share/').status_code, 404)
        screened = self.client.get(f'/jokes/{self.screened.pk}/share/').content.decode()
        self.assertIn('<html lang="de">', screened)
        self.assertIn('<meta name="robots" content="noindex">', screened)
        self.assertIn('"inLanguage": "de"', screened)
        human = self.client.get(f'/jokes/{self.human.pk}/share/').content.decode()
        self.assertNotIn('noindex', human)
        self.assertIn('<html lang="en">', human)

    def test_sitemap_lists_only_human_editorial_statuses(self):
        Joke.all_objects.filter(pk=self.human.pk).update(editorial_status='native_reviewed')
        body = self.client.get('/sitemap.xml').content.decode()
        self.assertIn(f'/jokes/{self.human.pk}<', body)
        self.assertNotIn(f'/jokes/{self.screened.pk}<', body)
        self.assertNotIn(f'/jokes/{self.held.pk}<', body)


class HumanFirstOrderingTests(GateFixture):
    def setUp(self):
        # The screened joke is the newest; human content must still lead.
        now = timezone.now()
        Joke.all_objects.filter(pk=self.human.pk).update(created_at=now - timedelta(days=3))
        Joke.all_objects.filter(pk=self.screened.pk).update(created_at=now)
        tag = ContextTag.objects.create(name='Ordertag', slug='ordertag')
        tag.jokes.through.objects.bulk_create([
            tag.jokes.through(joke_id=j.pk, contexttag_id=tag.pk) for j in (self.human, self.screened)
        ])

    def ordered(self, **params):
        params = {'language': 'all', **params}
        if 'q' not in params:
            params['themes'] = 'ordertag'
        rows = _rows(self.client_for().get('/api/v1/jokes/', params))
        return [row['id'] for row in rows if row['id'] in (self.human.pk, self.screened.pk)]

    def test_default_browse_and_search_rank_human_first(self):
        self.assertEqual(self.ordered(), [self.human.pk, self.screened.pk])
        self.assertEqual(self.ordered(q='zebracrossing joke'), [self.human.pk, self.screened.pk])
        self.assertEqual(self.ordered(ordering='popularity'), [self.human.pk, self.screened.pk])

    def test_explicit_newest_is_pure_recency(self):
        self.assertEqual(self.ordered(ordering='-created_at'), [self.screened.pk, self.human.pk])

    def test_random_and_daily_prefer_human(self):
        Joke.all_objects.exclude(pk__in=[self.human.pk, self.screened.pk]).update(is_removed=True)
        client = self.client_for()
        for _ in range(5):
            self.assertEqual(client.get('/api/v1/jokes/random/', {'language': 'all'}).data['id'],
                             self.human.pk)
        daily = client.get('/api/v1/daily-jokes/today/', {'language': 'all'})
        self.assertEqual(daily.data['joke']['id'], self.human.pk)
        personal = self.client_for(self.reader).get('/api/v1/daily-jokes/today/', {'language': 'all'})
        self.assertEqual(personal.data['joke']['id'], self.human.pk)

    def test_ai_screened_is_served_when_no_human_joke_qualifies(self):
        Joke.all_objects.exclude(pk=self.screened.pk).update(is_removed=True)
        response = self.client_for().get('/api/v1/jokes/random/', {'language': 'all'})
        self.assertEqual(response.data['id'], self.screened.pk)


class OriginCountryContractTests(GateFixture):
    def test_origin_country_shape_and_null(self):
        client = self.client_for()
        screened = client.get(f'/api/v1/jokes/{self.screened.pk}/').data
        self.assertEqual(dict(screened['origin_country']),
                         {'code': 'DE', 'name': self.germany.name, 'native_name': self.germany.native_name})
        self.assertEqual(screened['editorial_status'], 'ai_screened')
        self.assertIsNone(client.get(f'/api/v1/jokes/{self.human.pk}/').data['origin_country'])

    def test_list_card_serializer_carries_badges_without_n_plus_one(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        Joke.all_objects.filter(pk__in=[self.human.pk, self.screened.pk]).update(creator=self.creator)
        client = self.client_for()

        def profile():
            with CaptureQueriesContext(connection) as queries:
                response = client.get(f'/api/v1/creators/{self.creator.pk}/profile/')
            self.assertEqual(response.status_code, 200)
            return response.data['jokes'], len(queries)

        cards, few = profile()
        card = next(row for row in cards if row['id'] == self.screened.pk)
        self.assertEqual(card['editorial_status'], 'ai_screened')
        self.assertEqual(dict(card['origin_country']),
                         {'code': 'DE', 'name': self.germany.name, 'native_name': self.germany.native_name})
        self.assertEqual(card['language']['code'], 'en')
        self.assertIsNone(next(row for row in cards if row['id'] == self.human.pk)['origin_country'])
        for i in range(6):
            self.make(f'More screened {i}', status='ai_screened', origin=self.germany, creator=self.creator)
        cards, many = profile()
        self.assertEqual(len(cards), 8)
        self.assertEqual(many, few)
