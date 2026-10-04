"""International discovery keeps language, geography and culture independent."""
from datetime import timedelta
from unittest.mock import patch

from django.apps import apps
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APITestCase

from jokes.models import (
    AgeRating,
    CulturalCollection,
    CultureTag,
    DailyJoke,
    Format,
    Joke,
    JokeRating,
    JokeSubmission,
    JokeView,
    Language,
    UserBlock,
    UserPreference,
)


class InternationalDiscoveryTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.es, _ = Language.objects.get_or_create(code='es', defaults={'name': 'Spanish'})
        cls.fr, _ = Language.objects.get_or_create(code='fr', defaults={'name': 'French'})
        with patch('jokes.models.Joke._generate_share_image'):
            cls.spanish = Joke.objects.create(
                text='El café tiene más reuniones que la oficina.',
                language=cls.es, format=Format.objects.get(slug='oneliner'),
                age_rating=AgeRating.objects.get(slug='family-friendly'),
            )
            cls.french = Joke.objects.create(
                text='Mon croissant demande des vacances.',
                language=cls.fr, format=cls.spanish.format, age_rating=cls.spanish.age_rating,
            )
        cls.user = get_user_model().objects.create_user(username='locale-reader', password='pw')

    def test_catalog_has_five_initial_collections_even_when_empty(self):
        response = self.client.get('/api/v1/discovery-locales/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {c['locale'] for c in response.data['collections']},
            {'es-ES', 'fr-FR', 'de-DE', 'hy-AM', 'it-IT'},
        )
        self.assertTrue(all(c['joke_count'] == 0 for c in response.data['collections']))

    def test_random_and_anonymous_daily_honor_language_without_fallback(self):
        for path in ['/api/v1/jokes/random/', '/api/v1/daily-jokes/today/']:
            with self.subTest(path=path):
                result = self.client.get(path, {'language': 'es'})
                self.assertEqual(result.status_code, 200)
                joke = result.data.get('joke', result.data)
                self.assertEqual(joke['id'], self.spanish.pk)
                self.assertEqual(self.client.get(path, {'language': 'xx'}).status_code, 404)

    def test_today_revalidates_cached_pick_when_language_changes(self):
        self.client.force_authenticate(self.user)
        DailyJoke.objects.create(user=self.user, date=timezone.now().date(), joke=self.french)
        result = self.client.get('/api/v1/daily-jokes/today/', {'language': 'es'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data['joke']['id'], self.spanish.pk)

    def test_tomorrow_revalidates_cached_pick_when_language_changes(self):
        self.client.force_authenticate(self.user)
        DailyJoke.objects.create(
            user=self.user, date=timezone.now().date() + timedelta(days=1), joke=self.french,
        )
        result = self.client.get('/api/v1/daily-jokes/tomorrow/', {'language': 'es'})
        self.assertEqual(result.status_code, 200)
        self.assertIn('café', result.data['preview'])

    def test_mystery_never_falls_back_to_unselected_language(self):
        self.client.force_authenticate(self.user)
        result = self.client.post('/api/v1/mystery-box/roll/?language=xx')
        self.assertEqual(result.status_code, 404)

    def test_country_and_culture_compose_with_language_and_search(self):
        Country = apps.get_model('jokes', 'Country')
        spain = Country.objects.get(code='ES')
        culture = CultureTag.objects.get(slug='spain-everyday')
        self.spanish.countries.add(spain)
        self.spanish.culture_tags.add(culture)
        result = self.client.get('/api/v1/jokes/', {
            'language': 'ES', 'country': 'es', 'culture_tags': culture.slug, 'q': 'café',
        })
        self.assertEqual(result.status_code, 200)
        self.assertEqual([j['id'] for j in result.data['results']], [self.spanish.pk])
        result = self.client.get('/api/v1/jokes/', {'language': 'es', 'country': 'FR'})
        self.assertEqual(result.data['count'], 0)

    def test_armenian_unicode_search_and_existing_english_stemming(self):
        hy, _ = Language.objects.get_or_create(code='hy', defaults={'name': 'Armenian'})
        with patch('jokes.models.Joke._generate_share_image'):
            armenian = Joke.objects.create(
                text='Սուրճը ժողովից ուշացավ։', language=hy,
                format=self.spanish.format, age_rating=self.spanish.age_rating,
            )
            english = Joke.objects.create(
                text='The cats are running.', language=Language.objects.get(code='en'),
                format=self.spanish.format, age_rating=self.spanish.age_rating,
            )
        for query, expected in [('Սուրճը', armenian), ('run', english)]:
            result = self.client.get('/api/v1/jokes/', {'q': query})
            self.assertIn(expected.pk, [j['id'] for j in result.data['results']])

    def test_catalog_counts_only_visible_matching_content(self):
        Country = apps.get_model('jokes', 'Country')
        self.spanish.countries.add(Country.objects.get(code='ES'))
        self.spanish.culture_tags.add(CultureTag.objects.get(slug='spain-everyday'))
        self.french.countries.add(Country.objects.get(code='ES'))
        self.french.culture_tags.add(CultureTag.objects.get(slug='spain-everyday'))
        body = self.client.get('/api/v1/discovery-locales/').data
        spanish = next(c for c in body['collections'] if c['locale'] == 'es-ES')
        self.assertEqual(spanish['joke_count'], 1)
        Joke.objects.filter(pk=self.spanish.pk).update(content_tier='tier_3')
        body = self.client.get('/api/v1/discovery-locales/').data
        self.assertEqual(next(c for c in body['collections'] if c['locale'] == 'es-ES')['joke_count'], 0)

    def test_cached_daily_does_not_leak_blocked_creators(self):
        creator = get_user_model().objects.create_user(username='blocked-locale-author')
        Joke.objects.filter(pk=self.french.pk).update(creator=creator)
        UserBlock.objects.create(blocker=self.user, blocked=creator)
        DailyJoke.objects.create(user=self.user, date=timezone.now().date(), joke=self.french)
        self.client.force_authenticate(self.user)
        response = self.client.get('/api/v1/daily-jokes/today/', {'language': 'fr'})
        self.assertEqual(response.status_code, 404)


    def test_catalog_discovers_new_country_culture_associations(self):
        Country = apps.get_model('jokes', 'Country')
        country = Country.objects.create(code='MX', name='Mexico', native_name='México')
        culture = CultureTag.objects.create(slug='mexico-everyday', name='Everyday Mexico')
        culture.languages.add(self.es)
        culture.countries.add(country)
        CulturalCollection.objects.create(
            slug='es-mx-everyday', language=self.es, country=country, culture=culture,
        )
        body = self.client.get('/api/v1/discovery-locales/').data
        mexico = next(c for c in body['collections'] if c['locale'] == 'es-MX')
        self.assertEqual(mexico['culture'], 'mexico-everyday')
        self.assertEqual(mexico['joke_count'], 0)

    def test_country_and_language_survive_partial_edit_and_publish(self):
        from jokes.admin import JokeSubmissionAdmin
        from jokes.serializers import JokeSubmissionCreateSerializer, JokeSubmissionListSerializer

        serializer = JokeSubmissionCreateSerializer(data={
            'text': 'El ascensor pidió trabajar desde casa.', 'format': 'oneliner',
            'age_rating': 'family-friendly', 'language': 'es', 'countries': ['ES'],
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        submission = serializer.save(user=self.user, status='pending')
        update = JokeSubmissionCreateSerializer(
            submission, data={'text': 'El ascensor pidió teletrabajo.'}, partial=True,
        )
        self.assertTrue(update.is_valid(), update.errors)
        update.save()
        self.assertEqual(JokeSubmissionListSerializer(submission).data['language'], 'es')
        self.assertEqual(JokeSubmissionListSerializer(submission).data['countries'], ['ES'])
        request = RequestFactory().post('/admin/')
        request.user = self.user
        model_admin = JokeSubmissionAdmin(JokeSubmission, AdminSite())
        with patch.object(model_admin, 'message_user'), patch('jokes.models.Joke._generate_share_image'):
            model_admin.approve_and_publish(request, JokeSubmission.objects.filter(pk=submission.pk))
        submission.refresh_from_db()
        self.assertEqual(submission.published_joke.language.code, 'es')
        self.assertEqual(list(submission.published_joke.countries.values_list('code', flat=True)), ['ES'])

    def test_pack_catalog_featured_and_entries_honor_selection(self):
        from jokes.models import JokePack, JokePackEntry, JokePackProgress

        pack = JokePack.objects.create(slug='mixed-locales', title='Mixed', is_published=True, is_featured=True)
        JokePackEntry.objects.create(pack=pack, joke=self.spanish, order=1)
        JokePackEntry.objects.create(pack=pack, joke=self.french, order=2)
        for path in ['/api/v1/packs/mixed-locales/', '/api/v1/packs/featured/']:
            response = self.client.get(path, {'language': 'es'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['joke_count'], 1)
            self.assertEqual([e['joke']['id'] for e in response.data['jokes']], [self.spanish.pk])
        self.assertEqual(self.client.get('/api/v1/packs/', {'language': 'xx'}).data['count'], 0)
        JokePackProgress.objects.create(user=self.user, pack=pack, last_read_entry=1)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get('/api/v1/users/me/packs/in-progress/', {'language': 'xx'}).data, [])

    def test_cultural_explanation_is_hidden_when_joke_locked(self):
        from jokes.serializers import JokeSerializer

        self.spanish.cultural_note = 'Explanation includes the punchline.'
        with patch.object(JokeSerializer, '_is_locked', return_value=True):
            self.assertIsNone(JokeSerializer(self.spanish).data['cultural_note'])


    def test_shared_culture_advertises_only_declared_language_country_triples(self):
        Country = apps.get_model('jokes', 'Country')
        spain = Country.objects.get(code='ES')
        france = Country.objects.get(code='FR')
        culture = CultureTag.objects.create(slug='shared-everyday', name='Shared everyday settings')
        culture.languages.add(self.es, self.fr)
        culture.countries.add(spain, france)
        CulturalCollection.objects.create(
            slug='shared-es-es', language=self.es, country=spain, culture=culture,
        )
        CulturalCollection.objects.create(
            slug='shared-fr-fr', language=self.fr, country=france, culture=culture,
        )
        body = self.client.get('/api/v1/discovery-locales/').data
        shared = [row for row in body['collections'] if row['culture'] == culture.slug]
        self.assertEqual({(row['language'], row['country']) for row in shared}, {('es', 'ES'), ('fr', 'FR')})
        self.assertEqual(len(shared), 2)
        self.assertTrue(all(row['joke_count'] == 0 for row in shared))
        country_languages = {row['code']: row['language_codes'] for row in body['countries']}
        self.assertEqual(country_languages['ES'], ['es'])
        self.assertEqual(country_languages['FR'], ['fr'])


class DiscoveryLanguageDefaultTests(APITestCase):
    """Clients that send no language selector are served the viewer's language."""

    @classmethod
    def setUpTestData(cls):
        cls.en = Language.objects.get(code='en')
        cls.es, _ = Language.objects.get_or_create(code='es', defaults={'name': 'Spanish'})
        cls.fr, _ = Language.objects.get_or_create(code='fr', defaults={'name': 'French'})
        fmt = Format.objects.get(slug='oneliner')
        age = AgeRating.objects.get(slug='family-friendly')
        with patch('jokes.models.Joke._generate_share_image'):
            cls.english = Joke.objects.create(text='My coffee called in sick.', language=cls.en,
                                              format=fmt, age_rating=age)
            cls.spanish = Joke.objects.create(text='Mi café pidió vacaciones.', language=cls.es,
                                              format=fmt, age_rating=age)
            cls.french = Joke.objects.create(text='Mon café a pris un congé.', language=cls.fr,
                                             format=fmt, age_rating=age)
        cls.user = get_user_model().objects.create_user(username='default-reader', password='pw')

    def ids(self, path, params=None):
        body = self.client.get(path, params or {}).data
        rows = body['results'] if isinstance(body, dict) and 'results' in body else body
        return {row.get('joke', row)['id'] for row in rows}

    def foreign_ids(self):
        return {self.spanish.pk, self.french.pk}

    def test_browse_without_language_is_english_for_anonymous(self):
        ids = self.ids('/api/v1/jokes/')
        self.assertIn(self.english.pk, ids)
        self.assertFalse(ids & self.foreign_ids())
        for _ in range(5):
            joke = self.client.get('/api/v1/jokes/random/').data
            self.assertEqual(joke['language']['code'], 'en')
        self.assertEqual(self.client.get('/api/v1/daily-jokes/today/').data['joke']['language']['code'], 'en')

    def test_explicit_all_or_blank_language_spans_every_language(self):
        for value in ['all', 'ALL', '']:
            with self.subTest(language=value):
                ids = self.ids('/api/v1/jokes/', {'language': value})
                self.assertTrue({self.english.pk, self.spanish.pk, self.french.pk} <= ids)
        self.assertEqual(self.ids('/api/v1/jokes/', {'language': 'fr'}), {self.french.pk})

    def test_text_search_without_language_spans_every_language(self):
        self.assertIn(self.spanish.pk, self.ids('/api/v1/jokes/', {'q': 'vacaciones'}))

    def test_signed_in_viewer_defaults_to_preferred_language(self):
        UserPreference.objects.update_or_create(user=self.user, defaults={'preferred_language': self.fr})
        self.client.force_authenticate(self.user)
        self.assertEqual(self.ids('/api/v1/jokes/'), {self.french.pk})
        self.assertEqual(self.client.get('/api/v1/jokes/random/').data['id'], self.french.pk)
        today = self.client.get('/api/v1/daily-jokes/today/').data
        self.assertEqual(today['joke']['id'], self.french.pk)

    def test_trending_scores_are_not_multiplied_by_culture_matches(self):
        first = CultureTag.objects.create(slug='trend-a', name='Trend A')
        second = CultureTag.objects.create(slug='trend-b', name='Trend B')
        fmt, age = self.english.format, self.english.age_rating
        with patch('jokes.models.Joke._generate_share_image'):
            both = Joke.objects.create(text='Matches two cultures.', language=self.en, format=fmt, age_rating=age)
            one = Joke.objects.create(text='Matches one culture.', language=self.en, format=fmt, age_rating=age)
        both.culture_tags.add(first, second)
        one.culture_tags.add(first)
        fans = [get_user_model().objects.create_user(username=f'trend-fan-{i}') for i in range(2)]
        JokeRating.objects.create(user=fans[0], joke=both, rating=1)
        for fan in fans:
            JokeRating.objects.create(user=fan, joke=one, rating=1)
        body = self.client.get('/api/v1/jokes/trending/', {'culture_tags': 'trend-a,trend-b'}).data
        rows = [(row['joke']['id'], row['likes']) for row in body['results']]
        self.assertEqual(rows, [(one.pk, 2), (both.pk, 1)])

    def test_selector_request_never_rerolls_the_stored_daily_pick(self):
        self.client.force_authenticate(self.user)
        today = timezone.now().date()
        tomorrow = today + timedelta(days=1)
        DailyJoke.objects.create(user=self.user, date=today, joke=self.english)
        DailyJoke.objects.create(user=self.user, date=tomorrow, joke=self.english)
        first = self.client.get('/api/v1/daily-jokes/today/').data
        self.assertEqual(first['joke']['id'], self.english.pk)
        delivered_at = DailyJoke.objects.get(user=self.user, date=today).delivered_at
        self.assertIsNotNone(delivered_at)

        for language, joke in [('fr', self.french), ('es', self.spanish)]:
            response = self.client.get('/api/v1/daily-jokes/today/', {'language': language})
            self.assertEqual(response.data['joke']['id'], joke.pk)
            self.assertIsNone(response.data['id'])
            again = self.client.get('/api/v1/daily-jokes/today/', {'language': language})
            self.assertEqual(again.data['joke']['id'], joke.pk)
            self.assertIn('café', self.client.get(
                '/api/v1/daily-jokes/tomorrow/', {'language': language}).data['preview'])

        stored = DailyJoke.objects.get(user=self.user, date=today)
        self.assertEqual((stored.joke_id, stored.delivered_at), (self.english.pk, delivered_at))
        self.assertEqual(DailyJoke.objects.get(user=self.user, date=tomorrow).joke_id, self.english.pk)
        self.assertEqual(self.client.get('/api/v1/daily-jokes/today/').data['joke']['id'], self.english.pk)
        self.assertEqual(DailyJoke.objects.filter(user=self.user).count(), 2)

    def test_unservable_stored_daily_pick_is_still_replaced(self):
        self.client.force_authenticate(self.user)
        today = timezone.now().date()
        DailyJoke.objects.create(user=self.user, date=today, joke=self.spanish)
        Joke.all_objects.filter(pk=self.spanish.pk).update(is_removed=True)
        response = self.client.get('/api/v1/daily-jokes/today/', {'language': 'all'})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data['joke']['id'], self.spanish.pk)
        self.assertEqual(DailyJoke.objects.get(user=self.user, date=today).joke_id, response.data['joke']['id'])

    def test_history_is_not_narrowed_by_the_default_language(self):
        self.client.force_authenticate(self.user)
        DailyJoke.objects.create(user=self.user, date=timezone.now().date() - timedelta(days=1), joke=self.french)
        response = self.client.get('/api/v1/daily-jokes/history/')
        rows = response.data['results'] if isinstance(response.data, dict) else response.data
        self.assertEqual([row['joke']['id'] for row in rows], [self.french.pk])

    def test_recently_viewed_query_count_is_constant(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.force_authenticate(self.user)
        spain = apps.get_model('jokes', 'Country').objects.get(code='ES')
        culture = CultureTag.objects.create(slug='viewed-culture', name='Viewed')

        def view(joke):
            joke.countries.add(spain)
            joke.culture_tags.add(culture)
            JokeView.objects.create(user=self.user, joke=joke, source=JokeView.SOURCE_OTHER)

        def count():
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get('/api/v1/users/me/recently-viewed/')
            self.assertEqual(response.status_code, 200)
            return len(ctx.captured_queries), len(response.data)

        view(self.english)
        few, rows = count()
        self.assertEqual(rows, 1)
        view(self.spanish)
        view(self.french)
        many, rows = count()
        self.assertEqual(rows, 3)
        self.assertEqual(few, many)
