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
    JokeSubmission,
    Language,
    UserBlock,
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
