"""Stable retries, receipt-time consent, and raw telemetry lifecycle."""
import io
import json
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from jokes.models import AgeRating, Format, Joke, JokeDwell, JokeImpression, JokeView, Language

URL = '/api/v1/telemetry/events'


def setup_objects(test):
    test.user = get_user_model().objects.create_user(
        username='event-reader', email='events@example.com', password='test-password',
    )
    test.user.profile.date_of_birth = date(1990, 1, 1)
    test.user.profile.share_analytics = True
    test.user.profile.save()
    with patch('jokes.models.Joke._generate_share_image'):
        test.joke = Joke.objects.create(
            text='A measurable joke', format=Format.objects.get(slug='oneliner'),
            age_rating=AgeRating.objects.first(), language=Language.objects.get(code='en'),
        )
    test.client = APIClient()
    test.client.force_authenticate(test.user)


def event_for(test, **changes):
    event = {
        'schema_version': 2, 'event_id': str(uuid.uuid4()),
        'session_id': str(uuid.uuid4()), 'platform': 'web',
        'occurred_at': timezone.now().isoformat(), 'joke': test.joke.pk,
        'type': 'dwell', 'source': 'feed', 'value': 2400,
    }
    return {**event, **changes}


class VersionedTelemetryTests(TestCase):
    def setUp(self):
        setup_objects(self)

    def post(self, events):
        return self.client.post(URL, {'events': events}, format='json')

    def test_retries_do_not_duplicate_duration_and_conflicting_replay_rejects(self):
        event = event_for(self)
        response = self.post([event, event])
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {'accepted': 1, 'duplicates': 1, 'rejected': 0})
        self.assertEqual(JokeDwell.objects.count(), 1)
        self.assertEqual(self.post([{**event, 'value': 9000}]).json()['rejected'], 1)
        self.assertEqual(JokeDwell.objects.get().dwell_ms, 2400)

    def test_envelope_is_strict_and_timestamps_are_bounded(self):
        now = timezone.now()
        invalid = [
            {'schema_version': 3}, {'schema_version': True}, {'event_id': 'bad'},
            {'session_id': None}, {'platform': 'android'},
            {'occurred_at': '2026-01-01T00:00:00'},
            {'occurred_at': (now - timedelta(days=2)).isoformat()},
            {'occurred_at': (now + timedelta(minutes=6)).isoformat()},
            {'content_version': 9},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                self.assertEqual(self.post([event_for(self, **changes)]).json()['accepted'], 0)
        partial = {'joke': self.joke.pk, 'type': 'dwell', 'value': 1000, 'session_id': str(uuid.uuid4())}
        self.assertEqual(self.post([partial]).json()['accepted'], 0)
        self.assertEqual(JokeDwell.objects.count(), 0)

    def test_legacy_still_appends_and_receipt_stores_no_untrusted_properties(self):
        from jokes.models import AudienceEvent
        legacy = {'joke': self.joke.pk, 'type': 'dwell', 'value': 1200}
        self.assertEqual(self.post([legacy, legacy]).json()['accepted'], 2)
        self.assertEqual(JokeDwell.objects.count(), 2)
        self.assertEqual(AudienceEvent.objects.filter(schema_version=1, occurred_at=None).count(), 2)
        self.post([event_for(self, email='do-not-store@example.com', user=999, ip='1.2.3.4')])
        receipt = AudienceEvent.objects.get(schema_version=2)
        self.assertEqual(receipt.user_id, self.user.pk)
        self.assertIsNone(receipt.content_version)
        self.assertEqual(receipt.consent.provenance, 'legacy_observed')
        self.assertEqual(receipt.eligibility, 'adult_opt_in_at_receipt')
        self.assertNotIn('do-not-store', json.dumps(list(AudienceEvent.objects.values()), default=str))

    def test_receipt_and_projection_rollback_together(self):
        from jokes.models import AudienceEvent
        with patch('jokes.telemetry.JokeDwell.objects.create', side_effect=RuntimeError('projection failed')):
            with self.assertRaises(RuntimeError):
                self.post([event_for(self)])
        self.assertFalse(AudienceEvent.objects.exists())

    def test_consent_changes_are_strict_and_withdrawal_stops_collection(self):
        from jokes.models import AnalyticsConsentRecord, AudienceEvent
        self.post([event_for(self)])
        prefs = '/api/v1/users/me/preferences/'
        for invalid in ['false', 1, None, [], {}]:
            response = self.client.patch(prefs, {'privacy': {'share_analytics': invalid}}, format='json')
            self.assertEqual(response.status_code, 400)
        response = self.client.patch(prefs, {'privacy': {'share_analytics': False}}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.post([event_for(self)]).json()['accepted'], 0)
        self.assertEqual(AudienceEvent.objects.count(), 1)
        record = AnalyticsConsentRecord.objects.latest('pk')
        self.assertFalse(record.enabled)
        self.assertEqual(record.provenance, 'preference')
        count = AnalyticsConsentRecord.objects.count()
        self.client.patch(prefs, {'privacy': {'share_analytics': False}}, format='json')
        self.assertEqual(AnalyticsConsentRecord.objects.count(), count)

    def test_receipt_consent_does_not_claim_occurrence_time_consent(self):
        from jokes.models import AudienceEvent
        event = event_for(self, occurred_at=(timezone.now() - timedelta(hours=1)).isoformat())
        self.assertEqual(self.post([event]).json()['accepted'], 1)
        receipt = AudienceEvent.objects.get()
        self.assertGreater(receipt.consent.recorded_at, receipt.occurred_at)
        self.assertEqual(receipt.eligibility, 'adult_opt_in_at_receipt')

    def test_other_device_stale_profile_cannot_collect_after_withdrawal(self):
        stale_user = get_user_model().objects.get(pk=self.user.pk)
        self.assertTrue(stale_user.profile.share_analytics)
        other_device = APIClient()
        other_device.force_authenticate(stale_user)
        self.client.patch('/api/v1/users/me/preferences/', {
            'privacy': {'share_analytics': False},
        }, format='json')
        response = other_device.post(URL, {'events': [event_for(self)]}, format='json')
        self.assertEqual(response.json()['accepted'], 0)
        self.assertFalse(JokeDwell.objects.exists())

    def test_stale_public_profile_edit_does_not_resurrect_consent(self):
        stale_user = get_user_model().objects.get(pk=self.user.pk)
        self.assertTrue(stale_user.profile.share_analytics)
        self.client.patch('/api/v1/users/me/preferences/', {
            'privacy': {'share_analytics': False},
        }, format='json')
        other_device = APIClient()
        other_device.force_authenticate(stale_user)
        response = other_device.patch('/api/v1/users/me/profile/', {'bio': 'Updated bio'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.share_analytics)
        self.assertEqual(self.user.profile.bio, 'Updated bio')
        response = other_device.patch('/api/v1/users/me/profile/', {'share_analytics': True}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_event_ids_are_scoped_to_the_authenticated_person(self):
        from jokes.models import AudienceEvent
        event = event_for(self)
        self.post([event])
        other = get_user_model().objects.create_user(username='other-reader', password='pw')
        other.profile.share_analytics = True
        other.profile.date_of_birth = date(1990, 1, 1)
        other.profile.save()
        self.client.force_authenticate(other)
        self.assertEqual(self.post([event]).json()['accepted'], 1)
        self.assertEqual(AudienceEvent.objects.filter(event_id=event['event_id']).count(), 2)

    def test_export_includes_only_own_retained_telemetry_and_consent(self):
        self.post([event_for(self), event_for(self, type='impression')])
        response = self.client.get('/api/v1/users/me/data-export/')
        data = json.loads(zipfile.ZipFile(io.BytesIO(response.content)).read('jokes-for-data-export.json'))
        self.assertEqual(len(data['audience_events']), 2)
        self.assertEqual(len(data['analytics_consent']), 1)
        self.assertEqual(len(data['impressions']), 1)
        self.assertEqual(len(data['dwell_samples']), 1)
        self.assertEqual(data['watch_samples'], [])

    def test_account_delete_cascades_retained_telemetry_and_consent(self):
        from jokes.models import AnalyticsConsentRecord, AudienceEvent
        self.post([event_for(self), event_for(self, type='impression')])
        response = self.client.delete('/api/v1/users/me/', {'password': 'test-password'}, format='json')
        self.assertEqual(response.status_code, 204)
        for model in (AnalyticsConsentRecord, AudienceEvent, JokeDwell, JokeImpression):
            self.assertFalse(model.objects.exists(), model.__name__)

    def test_export_does_not_hide_physically_retained_rows_awaiting_cleanup(self):
        from jokes.models import AudienceEvent
        self.post([event_for(self)])
        old = timezone.now() - timedelta(days=91)
        AudienceEvent.objects.update(received_at=old)
        JokeDwell.objects.update(created_at=old, created_date=old.date())
        response = self.client.get('/api/v1/users/me/data-export/')
        data = json.loads(zipfile.ZipFile(io.BytesIO(response.content)).read('jokes-for-data-export.json'))
        self.assertEqual(len(data['audience_events']), 1)
        self.assertEqual(len(data['dwell_samples']), 1)
        self.assertTrue(data['analytics_retention']['pending_cleanup_included'])
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_retention_is_bounded_and_keeps_operational_history(self):
        from jokes.models import AudienceEvent
        from jokes.telemetry import purge_expired_analytics
        self.post([event_for(self), event_for(self), event_for(self, type='impression')])
        old = timezone.now() - timedelta(days=91)
        AudienceEvent.objects.update(received_at=old)
        JokeDwell.objects.update(created_at=old, created_date=old.date())
        JokeImpression.objects.update(created_at=old, created_date=old.date())
        view = JokeView.objects.create(user=self.user, joke=self.joke)
        JokeView.objects.filter(pk=view.pk).update(viewed_at=old, viewed_date=old.date())
        self.assertEqual(sum(purge_expired_analytics(batch_size=2).values()), 2)
        self.assertEqual(sum(purge_expired_analytics(batch_size=20).values()), 4)
        self.assertTrue(JokeView.objects.filter(pk=view.pk).exists())

    def test_expired_optional_samples_are_excluded_before_physical_cleanup(self):
        from creator_insights.services import _eligible_events
        self.post([event_for(self), event_for(self, type='impression')])
        old = timezone.now() - timedelta(days=91)
        JokeDwell.objects.update(created_at=old, created_date=old.date())
        JokeImpression.objects.update(created_at=old, created_date=old.date())
        self.assertFalse(_eligible_events(JokeDwell).exists())
        self.assertFalse(_eligible_events(JokeImpression).exists())
        self.assertTrue(JokeDwell.objects.exists())
        self.assertTrue(JokeImpression.objects.exists())

    def test_retention_opportunities_are_rate_limited(self):
        from jokes.telemetry import maybe_purge_expired_analytics
        with patch('jokes.telemetry.cache.add', side_effect=[True, False]), patch(
            'jokes.telemetry.purge_expired_analytics',
        ) as purge:
            maybe_purge_expired_analytics()
            maybe_purge_expired_analytics()
        purge.assert_called_once()


class ConcurrentTelemetryTests(TransactionTestCase):
    serialized_rollback = True

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        # Restore migration-seeded taxonomy after TransactionTestCase flush,
        # including for the next --keepdb run (same convention as billing).
        connection.creation.deserialize_db_from_string(connection._test_serialized_contents)

    def setUp(self):
        setup_objects(self)

    def test_concurrent_retry_projects_duration_once(self):
        event = event_for(self)

        def send(_):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
                return client.post(URL, {'events': [event]}, format='json').json()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, range(2)))
        self.assertEqual(sum(item['accepted'] for item in results), 1)
        self.assertEqual(sum(item['duplicates'] for item in results), 1)
        self.assertEqual(JokeDwell.objects.count(), 1)
