"""Consent, coverage and minimum samples are analytics behavior, not UI hints."""
from datetime import date, timedelta
from importlib import import_module
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from creator_insights.services import build_creator_insights
from follows.models import Follow
from jokes.models import (
    AgeRating,
    Favorite,
    Format,
    Joke,
    JokeDwell,
    JokeImpression,
    JokeMedia,
    JokeReaction,
    JokeSubmission,
    JokeView,
    JokeWatch,
    Language,
    MediaAsset,
    SavedJoke,
    ShareEvent,
    Tone,
    UserBlock,
)

User = get_user_model()
INGEST = '/api/v1/telemetry/events'


def reader(name, *, consent=True, born=date(1990, 1, 1)):
    user = User.objects.create_user(username=name)
    user.profile.share_analytics = consent
    user.profile.date_of_birth = born
    user.profile.save(update_fields=['share_analytics', 'date_of_birth'])
    return user


class MeasurementPolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.creator = reader('measurement-creator', consent=False)
        cls.adult = reader('measurement-adult')
        cls.optout = reader('measurement-optout', consent=False)
        cls.minor = reader('measurement-minor', born=timezone.now().date() - timedelta(days=3650))
        with patch('jokes.models.Joke._generate_share_image'):
            cls.joke = Joke.objects.create(
                text='Measured joke', creator=cls.creator,
                format=Format.objects.get(slug='oneliner'),
                age_rating=AgeRating.objects.first(), language=Language.objects.get(code='en'),
            )
        cls.joke.tones.add(Tone.objects.first())

    def ingest(self, user, events):
        client = APIClient()
        client.force_authenticate(user)
        return client.post(INGEST, {'events': events}, format='json')

    def test_optout_and_minors_cannot_submit_any_analytics(self):
        events = [
            {'joke': self.joke.pk, 'type': 'impression'},
            {'joke': self.joke.pk, 'type': 'reveal'},
            {'joke': self.joke.pk, 'type': 'dwell', 'value': 5000},
            {'joke': self.joke.pk, 'type': 'watch', 'watch_ms': 5000},
        ]
        for user in (self.optout, self.minor):
            with self.subTest(user=user.pk):
                response = self.ingest(user, events)
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.data['accepted'], 0)
        self.assertFalse(JokeImpression.objects.exists())
        self.assertFalse(JokeDwell.objects.exists())
        self.assertFalse(JokeView.objects.exists())

    def test_unknown_age_is_ineligible_even_with_consent(self):
        unknown = reader('measurement-unknown', born=None)
        response = self.ingest(unknown, [{'joke': self.joke.pk, 'type': 'impression'}])
        self.assertEqual(response.data['accepted'], 0)

    def test_ingest_only_accepts_currently_visible_content(self):
        for field, value in (('content_tier', 'tier_2'), ('content_tier', 'tier_3'), ('is_removed', True)):
            with self.subTest(field=field, value=value):
                Joke.all_objects.filter(pk=self.joke.pk).update(content_tier='tier_1', is_removed=False)
                Joke.all_objects.filter(pk=self.joke.pk).update(**{field: value})
                response = self.ingest(self.adult, [{'joke': self.joke.pk, 'type': 'impression'}])
                self.assertEqual(response.data['accepted'], 0)
        Joke.all_objects.filter(pk=self.joke.pk).update(content_tier='tier_1', is_removed=False)
        UserBlock.objects.create(blocker=self.creator, blocked=self.adult)
        self.assertEqual(self.ingest(self.adult, [{'joke': self.joke.pk, 'type': 'impression'}]).data['accepted'], 0)

    def test_unknown_sources_and_malformed_ids_are_skipped_with_valid_sibling(self):
        response = self.ingest(self.adult, [
            {'joke': self.joke.pk, 'type': 'impression', 'source': 'invented'},
            {'joke': self.joke.pk, 'type': 'impression', 'source': ['feed']},
            {'joke': str(self.joke.pk), 'type': 'impression'},
            {'joke': self.joke.pk, 'type': 'impression', 'source': 'feed'},
        ])
        self.assertEqual(response.data['accepted'], 1)
        self.assertEqual(JokeImpression.objects.get().source, 'feed')

    def test_reveal_does_not_rewrite_yesterdays_view(self):
        yesterday = timezone.now().date() - timedelta(days=1)
        old = JokeView.objects.create(user=self.adult, joke=self.joke, viewed_date=yesterday)
        self.ingest(self.adult, [{'joke': self.joke.pk, 'type': 'reveal'}])
        old.refresh_from_db()
        self.assertFalse(old.revealed_punchline)
        self.assertTrue(JokeView.objects.filter(
            user=self.adult, joke=self.joke, viewed_date=timezone.now().date(),
            revealed_punchline=True,
        ).exists())

    def test_impression_daily_identity_is_enforced_by_database(self):
        JokeImpression.objects.create(user=self.adult, joke=self.joke)
        with self.assertRaises(IntegrityError), transaction.atomic():
            JokeImpression.objects.create(user=self.adult, joke=self.joke)

    def test_impression_migration_keeps_earliest_source_and_other_dates(self):
        # PostgreSQL transactional DDL lets us exercise the real cleanup SQL
        # against legacy duplicates without rewinding unrelated app migrations.
        constraint = JokeImpression._meta.constraints[0]
        with connection.schema_editor() as editor:
            editor.remove_constraint(JokeImpression, constraint)
        first = JokeImpression.objects.create(user=self.adult, joke=self.joke, source='feed')
        later = JokeImpression.objects.create(user=self.adult, joke=self.joke, source='search')
        yesterday = JokeImpression.objects.create(
            user=self.adult, joke=self.joke, source='pack',
            created_date=timezone.now().date() - timedelta(days=1),
        )
        migration = import_module('jokes.migrations.0037_impression_daily_uniqueness')
        with connection.cursor() as cursor:
            # Simulate pre-existing committed legacy data: finish fixture FK
            # checks before ALTER TABLE, while retaining TestCase rollback.
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute(migration.Migration.operations[0].sql)
        self.assertSetEqual(set(JokeImpression.objects.values_list('pk', flat=True)), {first.pk, yesterday.pk})
        self.assertFalse(JokeImpression.objects.filter(pk=later.pk).exists())
        self.assertEqual(JokeImpression.objects.get(pk=first.pk).source, 'feed')
        with connection.schema_editor() as editor:
            editor.add_constraint(JokeImpression, constraint)
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL DEFERRED')

    def test_adult_mature_optin_allows_tier2_telemetry(self):
        Joke.objects.filter(pk=self.joke.pk).update(content_tier='tier_2')
        self.adult.preference.show_mature = True
        self.adult.preference.save(update_fields=['show_mature'])
        response = self.ingest(self.adult, [{'joke': self.joke.pk, 'type': 'impression'}])
        self.assertEqual(response.data['accepted'], 1)

    def test_all_aggregates_exclude_nonconsenting_and_minor_contributions(self):
        for user in (self.adult, self.optout, self.minor):
            JokeView.objects.create(user=user, joke=self.joke)
            JokeImpression.objects.create(user=user, joke=self.joke)
            JokeDwell.objects.create(user=user, joke=self.joke, dwell_ms=5000)
            JokeReaction.objects.create(user=user, joke=self.joke, reaction='lol')
            Favorite.objects.create(user=user, joke=self.joke)
            SavedJoke.objects.create(user=user, joke=self.joke)
            ShareEvent.objects.create(user=user, joke=self.joke)
            Follow.objects.create(follower=user, creator=self.creator)
        ShareEvent.objects.create(joke=self.joke)  # Anonymous share is not audience consent.
        data = build_creator_insights(self.creator, 'all')
        for metric in ('reach', 'views', 'impressions', 'unique_reach', 'reactions', 'favorites', 'saves', 'shares', 'followers'):
            with self.subTest(metric=metric):
                self.assertEqual(data['overview'][metric], 1)
        self.assertEqual(data['top_jokes'][0]['views'], 1)
        self.assertEqual(data['top_jokes'][0]['shares'], 1)
        self.assertEqual(data['reactions_breakdown'], [{'reaction': 'lol', 'count': 1}])
        self.assertIn('measurement_notes', data)
        self.adult.profile.share_analytics = False
        self.adult.profile.save(update_fields=['share_analytics'])
        data = build_creator_insights(self.creator, 'all')
        self.assertEqual(data['overview']['views'], 0)
        self.assertEqual(data['overview']['followers'], 0)
        self.assertEqual(data['top_jokes'][0]['reactions'], 0)

    def test_open_rate_matches_user_joke_day_instead_of_dividing_unmatched_views(self):
        second = reader('measurement-second')
        JokeImpression.objects.create(user=self.adult, joke=self.joke)
        JokeImpression.objects.create(user=second, joke=self.joke)
        for _ in range(4):
            JokeView.objects.create(user=self.adult, joke=self.joke)
        unmatched = reader('measurement-unmatched')
        JokeView.objects.create(user=unmatched, joke=self.joke)
        self.assertEqual(build_creator_insights(self.creator, 'all')['overview']['open_rate'], 0.5)

    def test_daily_reach_is_distinct_and_always_spans_full_28_days(self):
        old = timezone.now().date() - timedelta(days=20)
        for _ in range(3):
            JokeView.objects.create(user=self.adult, joke=self.joke, viewed_date=old)
        data = build_creator_insights(self.creator, 'week')
        self.assertEqual(data['overview']['views'], 0)
        self.assertEqual(data['overview']['daily_reach_28d'][7], 1)
        self.assertEqual(data['overview']['daily_views_28d'][7], 3)

    def test_low_sample_audience_and_recommendations_are_suppressed(self):
        JokeView.objects.create(user=self.adult, joke=self.joke)
        JokeReaction.objects.create(user=self.adult, joke=self.joke, reaction='lol')
        data = build_creator_insights(self.creator, 'all')
        self.assertEqual(data['audience']['top_categories'], [])
        self.assertTrue(data['audience']['suppressed'])
        for card in data['suggestions']:
            if card['kind'] in ('peak_hour', 'what_resonates'):
                self.assertEqual(card['data']['status'], 'insufficient_data')
        self.assertNotIn('grow their audience fastest', str(data))

    def test_direct_fk_creator_can_access_own_insights_without_submission(self):
        client = APIClient()
        client.force_authenticate(self.creator)
        response = client.get('/api/v1/creators/me/insights/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.data['top_jokes']], [self.joke.pk])

    def test_owner_scope_retains_tier2_but_never_serializes_tier3(self):
        Joke.objects.filter(pk=self.joke.pk).update(content_tier='tier_2')
        self.assertEqual(build_creator_insights(self.creator, 'all')['overview']['published_jokes'], 1)
        Joke.objects.filter(pk=self.joke.pk).update(content_tier='tier_3')
        data = build_creator_insights(self.creator, 'all')
        self.assertEqual(data['overview']['published_jokes'], 0)
        self.assertEqual(data['top_jokes'], [])

    def test_self_interactions_excluded_for_direct_and_legacy_ownership(self):
        self.creator.profile.share_analytics = True
        self.creator.profile.save(update_fields=['share_analytics'])
        JokeView.objects.create(user=self.creator, joke=self.joke)
        JokeImpression.objects.create(user=self.creator, joke=self.joke)
        JokeReaction.objects.create(user=self.creator, joke=self.joke, reaction='lol')
        self.assertEqual(build_creator_insights(self.creator, 'all')['overview']['views'], 0)
        Joke.objects.filter(pk=self.joke.pk).update(creator=None)
        JokeSubmission.objects.create(
            user=self.creator, format=self.joke.format, age_rating=self.joke.age_rating,
            language=self.joke.language, status='published', text=self.joke.text,
            published_joke=self.joke,
        )
        data = build_creator_insights(self.creator, 'all')
        self.assertEqual(data['overview']['views'], 0)
        self.assertEqual(data['overview']['impressions'], 0)
        self.assertEqual(data['overview']['reactions'], 0)

    def test_group_minimum_and_eligible_reader_threshold(self):
        # A large overall cohort must not expose a tiny individual content group.
        rare_tone = Tone.objects.exclude(pk=self.joke.tones.first().pk).first()
        with patch('jokes.models.Joke._generate_share_image'):
            rare = Joke.objects.create(
                text='Rare style', creator=self.creator, format=self.joke.format,
                age_rating=self.joke.age_rating, language=self.joke.language,
            )
        rare.tones.add(rare_tone)
        JokeView.objects.create(user=self.adult, joke=rare)
        for index in range(19):
            JokeView.objects.create(user=reader(f'threshold-{index}'), joke=self.joke)
        data = build_creator_insights(self.creator, 'all')
        self.assertFalse(data['audience']['suppressed'])
        self.assertEqual(data['audience']['top_categories'], [])
        JokeView.objects.create(user=self.adult, joke=self.joke)
        data = build_creator_insights(self.creator, 'all')
        self.assertEqual(data['audience']['top_categories'], [
            {'label': self.joke.tones.first().name, 'count': 20, 'sample_size': 20},
        ])

    def test_watch_requires_media_and_unknown_completion_stays_null(self):
        event = {'joke': self.joke.pk, 'type': 'watch', 'watch_ms': 5000}
        self.assertEqual(self.ingest(self.adult, [event]).data['accepted'], 0)
        asset = MediaAsset.objects.create(owner=self.creator, kind='audio', file='tests/sample.mp3')
        JokeMedia.objects.create(joke=self.joke, asset=asset)
        self.assertEqual(self.ingest(self.adult, [event]).data['accepted'], 1)
        self.assertIsNone(JokeWatch.objects.get().watch_pct)
        # Legacy ineligible telemetry must not affect averages or completion.
        for user in (self.optout, self.minor):
            JokeWatch.objects.create(user=user, joke=self.joke, watch_ms=60000, watch_pct=100)
        row = build_creator_insights(self.creator, 'all')['top_jokes'][0]
        self.assertEqual(row['avg_watch_seconds'], 5.0)
        self.assertIsNone(row['watch_completion_rate'])

    def test_malformed_bodies_and_unhashable_types_are_safe(self):
        client = APIClient()
        client.force_authenticate(self.adult)
        for payload in ([], ['events'], {'events': {}}, {'events': None}):
            response = client.post(INGEST, payload, format='json')
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.data['accepted'], 0)
        self.assertEqual(self.ingest(self.adult, [
            {'joke': self.joke.pk, 'type': ['impression']},
            {'joke': True, 'type': 'impression'},
            {'joke': 10 ** 100, 'type': 'impression'},
        ]).data['accepted'], 0)
