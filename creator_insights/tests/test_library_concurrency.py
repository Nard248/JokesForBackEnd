"""Real PostgreSQL races for durable library bounds and ordered updates."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from billing.models import Plan, Subscription
from creator_insights.models import (
    CreatorCollection,
    CreatorCollectionEntry,
    CreatorMetadataRequest,
)
from jokes.models import AgeRating, Format, Joke, Language

User = get_user_model()
BASE = '/api/v1/creators/me/'


class CreatorLibraryConcurrencyTests(TransactionTestCase):
    serialized_rollback = True

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        # Keep migration-seeded lookups for later classes and --keepdb runs,
        # matching the billing/telemetry concurrency-test convention.
        connection.creation.deserialize_db_from_string(connection._test_serialized_contents)

    def setUp(self):
        self.owner = User.objects.create_user(username='concurrent-library-owner')
        plan, _ = Plan.objects.get_or_create(slug='concurrent-library', defaults={
            'name': 'Creator concurrency fixture', 'features': {'creator_content_explorer': True},
        })
        Subscription.objects.create(user=self.owner, plan=plan, status='active')
        fmt, _ = Format.objects.get_or_create(slug='oneliner', defaults={'name': 'One-liner'})
        age, _ = AgeRating.objects.get_or_create(slug='library-all', defaults={'name': 'Library all'})
        language, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
        with patch('jokes.models.Joke._generate_share_image'):
            self.jokes = [Joke.objects.create(text=f'Ordered joke {i}', creator=self.owner, format=fmt, age_rating=age, language=language) for i in range(3)]

    def race(self, method, url, payloads):
        barrier = Barrier(2)
        owner_id = self.owner.pk

        def request(payload):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(User.objects.get(pk=owner_id))
                barrier.wait(timeout=10)
                return getattr(client, method)(url, payload, format='json').status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [executor.submit(request, data) for data in payloads]
            return sorted(future.result(timeout=20) for future in results)

    def test_concurrent_pending_requests_create_only_one(self):
        body = {'joke_ids': [self.jokes[0].pk], 'themes': []}
        self.assertEqual(self.race('post', BASE + 'content/metadata-requests/', [body, body]), [201, 409])
        self.assertEqual(CreatorMetadataRequest.objects.count(), 1)

    def test_concurrent_collection_creations_cannot_exceed_limit(self):
        CreatorCollection.objects.bulk_create([
            CreatorCollection(owner=self.owner, name=f'Set {i}', kind='set_list') for i in range(99)
        ])
        payloads = [{'name': 'First contender', 'kind': 'series'}, {'name': 'Second contender', 'kind': 'series'}]
        self.assertEqual(self.race('post', BASE + 'collections/', payloads), [201, 400])
        self.assertEqual(CreatorCollection.objects.filter(owner=self.owner).count(), 100)

    def test_concurrent_reorder_never_leaves_partial_or_duplicate_membership(self):
        collection = CreatorCollection.objects.create(owner=self.owner, name='Ordered set', kind='set_list')
        CreatorCollectionEntry.objects.bulk_create([
            CreatorCollectionEntry(collection=collection, joke=joke, position=i) for i, joke in enumerate(self.jokes)
        ])
        forward = [joke.pk for joke in self.jokes]
        backward = list(reversed(forward))
        payloads = [{'joke_ids': backward}, {'joke_ids': forward}]
        self.assertEqual(self.race('patch', f'{BASE}collections/{collection.pk}/', payloads), [200, 200])
        self.assertIn(list(collection.entries.values_list('joke_id', flat=True)), [forward, backward])
        self.assertEqual(list(collection.entries.values_list('position', flat=True)), [0, 1, 2])
