"""Public and saved search keep the same access boundaries as joke discovery."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from jokes.models import AgeRating, ContextTag, Format, Joke, Language, SavedJoke, Tone, UserBlock


@override_settings(REST_FRAMEWORK={
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
})
class UnifiedSearchAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.viewer = get_user_model().objects.create_user(username='search-viewer')
        cls.creator = get_user_model().objects.create_user(username='search-creator')
        cls.viewer.profile.date_of_birth = date(1990, 1, 1)
        cls.viewer.profile.save(update_fields=['date_of_birth'])
        cls.category = Tone.objects.create(name='Quasar comedy', slug='quasar-comedy')
        cls.base = {
            'format': Format.objects.get(slug='oneliner'),
            'age_rating': AgeRating.objects.first(),
            'language': Language.objects.get(code='en'),
        }
        with patch('jokes.models.Joke._generate_share_image'):
            cls.public = Joke.objects.create(text='A small cosmic misunderstanding.', **cls.base)
            cls.mature = Joke.objects.create(
                text='An adult cosmic misunderstanding.', content_tier='tier_2', **cls.base,
            )
            cls.prohibited = Joke.objects.create(
                text='A prohibited cosmic misunderstanding.', content_tier='tier_3', **cls.base,
            )
            cls.removed = Joke.objects.create(
                text='A removed cosmic misunderstanding.', is_removed=True, **cls.base,
            )
            cls.attributed = Joke.objects.create(
                text='An attributed cosmic misunderstanding.', creator=cls.creator, **cls.base,
            )
        for joke in (cls.public, cls.mature, cls.prohibited, cls.removed, cls.attributed):
            joke.tones.add(cls.category)
            SavedJoke.objects.create(user=cls.viewer, joke=joke)

    def search_ids(self, *, saved=False, query='quasar'):
        url = '/api/v1/saved-jokes/search/' if saved else '/api/v1/jokes/'
        response = self.client.get(url, {'q': query})
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.data['results']
        ids = {row['joke']['id'] if saved else row['id'] for row in rows}
        self.assertEqual(response.data['count'], len(ids))
        return ids

    def test_anonymous_metadata_search_hides_mature_prohibited_and_removed(self):
        self.assertEqual(self.search_ids(), {self.public.pk, self.attributed.pk})

    def test_adult_opt_in_can_search_mature_metadata(self):
        self.viewer.preference.show_mature = True
        self.viewer.preference.save(update_fields=['show_mature'])
        self.client.force_authenticate(self.viewer)
        self.assertEqual(
            self.search_ids(), {self.public.pk, self.attributed.pk, self.mature.pk},
        )

    def test_minor_opt_in_cannot_search_mature_metadata(self):
        self.viewer.profile.date_of_birth = date.today().replace(year=date.today().year - 15)
        self.viewer.profile.save(update_fields=['date_of_birth'])
        self.viewer.preference.show_mature = True
        self.viewer.preference.save(update_fields=['show_mature'])
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.search_ids(), {self.public.pk, self.attributed.pk})

    def test_blocking_either_direction_applies_to_public_and_saved_search(self):
        self.client.force_authenticate(self.viewer)
        for blocker, blocked in ((self.viewer, self.creator), (self.creator, self.viewer)):
            with self.subTest(blocker=blocker.pk):
                block = UserBlock.objects.create(blocker=blocker, blocked=blocked)
                self.assertEqual(self.search_ids(), {self.public.pk})
                self.assertEqual(self.search_ids(saved=True), {self.public.pk})
                block.delete()

    def test_saved_search_only_contains_callers_saved_visible_jokes(self):
        SavedJoke.objects.filter(user=self.viewer, joke=self.attributed).delete()
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.search_ids(saved=True), {self.public.pk})

    def test_search_validation_is_consistent_across_endpoints(self):
        self.client.force_authenticate(self.viewer)
        for url in ('/api/v1/jokes/', '/api/v1/saved-jokes/search/'):
            for query in ('a' * 201, ' '.join(['word'] * 33), 'hello\x00world'):
                with self.subTest(url=url, query_length=len(query)):
                    response = self.client.get(url, {'q': query})
                    self.assertEqual(response.status_code, 400, response.content)
                    self.assertIn('q', response.data)

    def test_metadata_search_composes_with_existing_filters(self):
        response = self.client.get('/api/v1/jokes/', {
            'q': 'quasar', 'joke_format': 'setup',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

    def test_category_and_theme_aliases_filter_results(self):
        theme = ContextTag.objects.create(name='Observatory', slug='observatory-search')
        self.public.context_tags.add(theme)
        for params in (
            {'categories': 'unknown-search-category'},
            {'themes': 'unknown-search-theme'},
        ):
            response = self.client.get('/api/v1/jokes/', {'q': 'quasar', **params})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], 0)
        response = self.client.get('/api/v1/jokes/', {
            'q': 'quasar', 'categories': self.category.slug, 'themes': theme.slug,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.data['results']], [self.public.pk])

    def test_pagination_has_no_duplicates_for_equal_rank(self):
        with patch('jokes.models.Joke._generate_share_image'):
            jokes = [Joke.objects.create(text='Pagination nebula.', **self.base) for _ in range(21)]
        expected = [j.pk for j in reversed(jokes)]
        actual = []
        for page in (1, 2, 3):
            response = self.client.get('/api/v1/jokes/', {'q': 'nebula', 'page': page})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], 21)
            actual.extend(row['id'] for row in response.data['results'])
        self.assertEqual(actual, expected)
