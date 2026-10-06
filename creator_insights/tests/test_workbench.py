"""Creator workbench tests exercise ownership, analytics population and exports."""
import csv
import io
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from billing.models import Plan, Subscription
from creator_insights.tests.consent import record_opt_in
from jokes.models import AgeRating, ContextTag, Format, Joke, JokeView, Language

User = get_user_model()
URL = '/api/v1/creators/me/content/'


class CreatorWorkbenchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.creator = User.objects.create_user(username='workbench-owner')
        cls.other = User.objects.create_user(username='workbench-other')
        cls.viewer = User.objects.create_user(username='workbench-viewer')
        cls.viewer.profile.date_of_birth = date(1990, 1, 1)
        cls.viewer.profile.share_analytics = True
        cls.viewer.profile.save()
        record_opt_in(cls.viewer)
        cls.plan = Plan.objects.get(slug='creator_pro')
        Subscription.objects.create(user=cls.creator, plan=cls.plan, status='active')
        with patch('jokes.models.Joke._generate_share_image'):
            cls.joke = Joke.objects.create(
                text='=A creator formula', creator=cls.creator,
                format=Format.objects.get(slug='oneliner'),
                age_rating=AgeRating.objects.first(), language=Language.objects.get(code='en'),
            )
            cls.foreign = Joke.objects.create(
                text='Private other creator content', creator=cls.other,
                format=cls.joke.format, age_rating=cls.joke.age_rating, language=cls.joke.language,
            )
        cls.theme = ContextTag.objects.create(slug='creator-test-theme', name='Creator test theme')
        cls.joke.context_tags.add(cls.theme)
        JokeView.objects.create(user=cls.viewer, joke=cls.joke)
        # Operational history without consent must not become creator analytics.
        JokeView.objects.create(user=cls.other, joke=cls.joke)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.creator)

    def test_owner_only_content_and_consented_population(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        row = response.data['results'][0]
        self.assertEqual(row['id'], self.joke.id)
        self.assertEqual(row['views'], 1)
        self.assertEqual(row['themes'][0]['slug'], self.theme.slug)
        self.assertNotIn(self.foreign.text, str(response.data))
        self.assertNotIn('email', str(response.data))

    def test_free_creator_keeps_basic_insights_but_workbench_requires_pro(self):
        Subscription.objects.filter(user=self.creator).update(status='canceled')
        # Cookie/Bearer auth loads a fresh user per request. Force-authenticated
        # test users otherwise retain the reverse OneToOne subscription cache.
        self.creator.refresh_from_db()
        self.assertEqual(self.client.get(URL).status_code, 403)
        from billing.entitlements import has_feature
        self.assertTrue(has_feature(self.creator, 'creator_analytics'))

    def test_anonymous_cannot_read_creator_content(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(URL).status_code, 401)

    def test_filter_by_theme_and_format(self):
        response = self.client.get(URL, {'theme': self.theme.slug, 'joke_format': 'oneliner'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(self.client.get(URL, {'theme': 'missing'}).data['count'], 0)

    def test_invalid_date_range_and_sort_are_rejected(self):
        for query in [
            {'start': '2026-03-02', 'end': '2026-03-01'},
            {'start': 'bad-date'}, {'sort': 'user__email'}, {'page_size': 100000},
        ]:
            with self.subTest(query=query):
                self.assertEqual(self.client.get(URL, query).status_code, 400)

    def test_early_iso_dates_do_not_overflow(self):
        self.assertEqual(self.client.get(URL, {'end': '0001-01-01'}).status_code, 400)
        self.assertEqual(self.client.get(URL, {'start': '0001-01-01', 'end': '0001-01-01'}).status_code, 200)

    def test_metadata_recommendation_works_without_a_large_audience(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        row = response.data['results'][0]
        self.assertIn('categories', row['metadata_missing'])
        self.assertEqual(row['recommendation']['kind'], 'complete_metadata')
        self.assertEqual(row['recommendation']['sample_size'], 1)

    def test_consent_withdrawal_excludes_prior_history(self):
        self.viewer.profile.share_analytics = False
        self.viewer.profile.save(update_fields=['share_analytics'])
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'][0]['views'], 0)

    def test_views_before_the_latest_opt_in_are_not_counted(self):
        from datetime import timedelta

        from django.utils import timezone

        from creator_insights.tests.consent import record_opt_in
        now = timezone.now()
        JokeView.objects.filter(user=self.viewer).update(viewed_at=now - timedelta(days=2))
        record_opt_in(self.viewer, at=now - timedelta(days=1))
        self.assertEqual(self.client.get(URL).data['results'][0]['views'], 0)
        JokeView.objects.create(user=self.viewer, joke=self.joke)
        self.assertEqual(self.client.get(URL).data['results'][0]['views'], 1)
        self.assertIn('latest opt-in', ' '.join(self.client.get(URL).data['measurement_notes']))

    def test_minor_and_creator_self_views_do_not_inflate_audience_metrics(self):
        for person, birthday in [(self.creator, date(1990, 1, 1)), (self.other, date(2012, 1, 1))]:
            person.profile.share_analytics = True
            person.profile.date_of_birth = birthday
            person.profile.save()
        JokeView.objects.create(user=self.creator, joke=self.joke)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'][0]['views'], 1)

    def test_moderation_removed_content_is_absent_even_for_owner(self):
        Joke.objects.filter(pk=self.joke.pk).update(is_removed=True)
        self.assertEqual(self.client.get(URL).data['count'], 0)

    def test_owner_content_and_exports_still_enforce_maturity_preferences(self):
        Joke.objects.filter(pk=self.joke.pk).update(content_tier='tier_2')
        for birthday, show_mature, expected_count in [
            (None, True, 0), (date(2012, 1, 1), True, 0),
            (date(1990, 1, 1), False, 0), (date(1990, 1, 1), True, 1),
        ]:
            with self.subTest(birthday=birthday, show_mature=show_mature):
                self.creator.profile.date_of_birth = birthday
                self.creator.profile.save(update_fields=['date_of_birth'])
                self.creator.preference.show_mature = show_mature
                self.creator.preference.save(update_fields=['show_mature'])
                self.assertEqual(self.client.get(URL).data['count'], expected_count)
                rows = list(csv.DictReader(io.StringIO(self.client.get(URL + 'export/').content.decode())))
                self.assertEqual(len(rows), expected_count)

    def test_selected_window_filters_activity_not_the_inventory(self):
        JokeView.objects.filter(joke=self.joke).update(viewed_date=date(2020, 1, 1))
        response = self.client.get(URL)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['views'], 0)

    def test_csv_denies_export_entitlement_even_with_explorer(self):
        self.plan.features = {**self.plan.features, 'creator_exports': False}
        self.plan.save(update_fields=['features'])
        self.creator.refresh_from_db()
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.assertEqual(self.client.get(URL + 'export/').status_code, 403)

    def test_csv_oversized_inventory_requests_narrower_filters(self):
        with patch('creator_insights.workbench_views.CreatorContentExportView.MAX_ROWS', 0):
            response = self.client.get(URL + 'export/')
        self.assertEqual(response.status_code, 422)

    def test_csv_protects_whitespace_prefixed_formulas(self):
        from creator_insights.workbench_views import csv_value
        for text in ['=SUM(A1:A2)', '+1', '-1', '@SUM(A1)', '\t=1', '\r=1', '  +1']:
            self.assertEqual(csv_value(text), "'" + text)
        self.assertEqual(csv_value('A normal joke'), 'A normal joke')

    def test_csv_is_owner_scoped_and_formula_safe(self):
        response = self.client.get(URL + 'export/')
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['text'].startswith("'="))
        self.assertEqual(rows[0]['views'], '1')
        self.assertIn('attachment;', response['Content-Disposition'])
