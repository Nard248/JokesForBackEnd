"""Private creator work, subscription boundaries, and moderation isolation."""
import io
import json
import zipfile
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from billing.models import Plan, Subscription
from jokes.models import AgeRating, ContextTag, Format, Joke, Language, Tone

User = get_user_model()
BASE = '/api/v1/creators/me/'


class CreatorLibraryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username='library-owner', password='test-password')
        cls.other = User.objects.create_user(username='library-other')
        cls.plan = Plan.objects.get(slug='creator_pro')
        for user in [cls.owner, cls.other]:
            Subscription.objects.create(user=user, plan=cls.plan, status='active')
        with patch('jokes.models.Joke._generate_share_image'):
            fields = {
                'format': Format.objects.get(slug='oneliner'),
                'age_rating': AgeRating.objects.first(), 'language': Language.objects.get(code='en'),
            }
            cls.joke = Joke.objects.create(text='First published joke', creator=cls.owner, **fields)
            cls.second = Joke.objects.create(text='Second published joke', creator=cls.owner, **fields)
            cls.foreign = Joke.objects.create(text='Other creator joke', creator=cls.other, **fields)
        cls.theme = ContextTag.objects.create(slug='library-theme', name='Library theme')
        cls.category = Tone.objects.create(slug='library-category', name='Library category')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.notes_url = f'{BASE}content/{self.joke.pk}/workspace/'

    def collection(self, **overrides):
        data = {'name': 'Opening set', 'kind': 'set_list', 'joke_ids': [self.joke.pk, self.second.pk]}
        data.update(overrides)
        response = self.client.post(BASE + 'collections/', data, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.data

    def test_note_round_trip_is_private_and_owner_scoped(self):
        self.assertEqual(self.client.get(self.notes_url).data['private_note'], '')
        response = self.client.patch(self.notes_url, {'private_note': 'Try a slower pause'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['private_note'], 'Try a slower pause')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        public = self.client.get(f'/api/v1/jokes/{self.joke.pk}/')
        self.assertNotIn('Try a slower pause', public.content.decode())
        self.client.force_authenticate(self.other)
        for method in ['get', 'patch', 'delete']:
            response = getattr(self.client, method)(self.notes_url, {'private_note': 'Unauthorized'}, format='json')
            self.assertEqual(response.status_code, 404)

    def test_cancellation_keeps_read_delete_but_blocks_paid_edits(self):
        self.client.patch(self.notes_url, {'private_note': 'Retain my work'}, format='json')
        collection = self.collection()
        Subscription.objects.filter(user=self.owner).update(status='canceled')
        self.owner.refresh_from_db()
        self.assertEqual(self.client.get(self.notes_url).data['private_note'], 'Retain my work')
        self.assertEqual(self.client.get(BASE + 'collections/').data['count'], 1)
        self.assertEqual(self.client.patch(self.notes_url, {'private_note': 'New'}, format='json').status_code, 403)
        self.assertEqual(self.client.post(BASE + 'collections/', {'name': 'New', 'kind': 'series'}, format='json').status_code, 403)
        self.assertEqual(self.client.delete(self.notes_url).status_code, 204)
        self.assertEqual(self.client.delete(f'{BASE}collections/{collection["id"]}/').status_code, 204)

    def test_note_and_collection_reject_unknown_fields_and_limits(self):
        for body in [{'private_note': 'x' * 5001}, {'private_note': 'ok', 'text': 'Replace published'}]:
            self.assertEqual(self.client.patch(self.notes_url, body, format='json').status_code, 400)
        for body in [
            {'name': 'x' * 101, 'kind': 'series'}, {'name': 'Set', 'kind': 'public'},
            {'name': 'Set', 'kind': 'series', 'is_public': True},
            {'name': 'Set', 'kind': 'series', 'joke_ids': [self.joke.pk, self.joke.pk]},
            {'name': 'Set', 'kind': 'series', 'description': 'x' * 1001},
            {'name': 'Set', 'kind': 'series', 'joke_ids': list(range(101))},
        ]:
            self.assertEqual(self.client.post(BASE + 'collections/', body, format='json').status_code, 400)

    def test_collection_order_and_partial_update(self):
        collection = self.collection()
        url = f'{BASE}collections/{collection["id"]}/'
        response = self.client.patch(url, {'joke_ids': [self.second.pk, self.joke.pk]}, format='json')
        self.assertEqual(response.data['joke_ids'], [self.second.pk, self.joke.pk])
        response = self.client.patch(url, {'name': 'Closing set'}, format='json')
        self.assertEqual(response.data['joke_ids'], [self.second.pk, self.joke.pk])
        self.assertEqual(response.data['name'], 'Closing set')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, {'name': 'Steal'}, format='json').status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_mixed_owner_batch_is_atomic(self):
        collection = self.collection()
        url = f'{BASE}collections/{collection["id"]}/'
        response = self.client.patch(url, {'name': 'Bad edit', 'joke_ids': [self.joke.pk, self.foreign.pk]}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(url).data['name'], 'Opening set')
        response = self.client.post(BASE + 'content/metadata-requests/', {
            'joke_ids': [self.joke.pk, self.foreign.pk], 'themes': [self.theme.slug],
        }, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(BASE + 'content/metadata-requests/').data['count'], 0)

    def test_inaccessible_entries_are_hidden_but_not_lost_on_name_edit(self):
        from creator_insights.models import CreatorCollectionEntry
        collection = self.collection()
        url = f'{BASE}collections/{collection["id"]}/'
        Joke.objects.filter(pk=self.second.pk).update(is_removed=True)
        response = self.client.get(url)
        self.assertEqual(response.data['joke_ids'], [self.joke.pk])
        self.assertEqual(response.data['unavailable_count'], 1)
        self.client.patch(url, {'name': 'Renamed'}, format='json')
        self.assertEqual(CreatorCollectionEntry.objects.filter(collection_id=collection['id']).count(), 2)
        response = self.client.patch(url, {'joke_ids': [self.second.pk]}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_mature_removed_and_prohibited_targets_are_rejected(self):
        for tier, removed in [('tier_2', False), ('tier_3', False), ('tier_1', True)]:
            with self.subTest(tier=tier, removed=removed):
                Joke.all_objects.filter(pk=self.joke.pk).update(content_tier=tier, is_removed=removed)
                self.assertEqual(self.client.get(self.notes_url).status_code, 404)
                self.assertEqual(self.client.patch(self.notes_url, {'private_note': 'x'}, format='json').status_code, 404)
                response = self.client.post(BASE + 'collections/', {
                    'name': 'Blocked', 'kind': 'series', 'joke_ids': [self.joke.pk],
                }, format='json')
                self.assertEqual(response.status_code, 404)

    def test_adult_opt_in_allows_mature_workspace(self):
        self.owner.profile.date_of_birth = date(1990, 1, 1)
        self.owner.profile.save(update_fields=['date_of_birth'])
        self.owner.preference.show_mature = True
        self.owner.preference.save(update_fields=['show_mature'])
        Joke.objects.filter(pk=self.joke.pk).update(content_tier='tier_2')
        self.assertEqual(self.client.patch(self.notes_url, {'private_note': 'Adult set'}, format='json').status_code, 200)

    def test_saved_notes_remain_discoverable_after_cancellation_and_hidden_notes_can_be_erased(self):
        self.client.patch(self.notes_url, {'private_note': 'Find this later'}, format='json')
        Subscription.objects.filter(user=self.owner).update(status='canceled')
        self.owner.refresh_from_db()
        url = BASE + 'content/workspace-notes/'
        response = self.client.get(url)
        self.assertEqual(response.data['results'][0]['private_note'], 'Find this later')
        self.assertEqual(response.data['unavailable_count'], 0)
        Joke.objects.filter(pk=self.joke.pk).update(is_removed=True)
        response = self.client.get(url)
        self.assertEqual(response.data['results'], [])
        self.assertEqual(response.data['unavailable_count'], 1)
        self.assertEqual(self.client.delete(self.notes_url).status_code, 204)
        self.assertEqual(self.client.get(url).data['unavailable_count'], 0)

    def test_collection_limit_is_enforced(self):
        from creator_insights.models import CreatorCollection
        CreatorCollection.objects.bulk_create([
            CreatorCollection(owner=self.owner, name=f'Set {i}', kind='set_list') for i in range(100)
        ])
        response = self.client.post(BASE + 'collections/', {'name': 'Too many', 'kind': 'series'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_library_export_is_private_and_cascades_with_account(self):
        from creator_insights.library import export_creator_library
        from creator_insights.models import CreatorCollection, CreatorWorkspaceNote
        self.client.patch(self.notes_url, {'private_note': 'Private timing'}, format='json')
        self.collection()
        exported = export_creator_library(self.owner)
        self.assertEqual(exported['notes'][0]['private_note'], 'Private timing')
        self.assertEqual(len(exported['collections']), 1)
        self.assertEqual(export_creator_library(self.other)['notes'], [])
        self.assertNotIn(self.joke.text, str(exported))
        self.owner.delete()
        self.assertFalse(CreatorCollection.objects.exists())
        self.assertFalse(CreatorWorkspaceNote.objects.exists())

    def test_account_zip_includes_library_without_paid_subscription(self):
        self.client.patch(self.notes_url, {'private_note': 'Export after cancel'}, format='json')
        Subscription.objects.filter(user=self.owner).update(status='canceled')
        self.owner.refresh_from_db()
        response = self.client.get('/api/v1/users/me/data-export/')
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            exported = json.loads(archive.read('jokes-for-data-export.json'))
        self.assertEqual(exported['creator_library']['notes'][0]['private_note'], 'Export after cancel')

    def test_anonymous_and_cookie_csrf_boundaries(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.notes_url).status_code, 401)
        client = APIClient(enforce_csrf_checks=True)
        access = str(RefreshToken.for_user(self.owner).access_token)
        client.cookies['jokes-access-token'] = access
        response = client.patch(self.notes_url, {'private_note': 'No CSRF'}, format='json')
        self.assertEqual(response.status_code, 403)
        csrf = client.get('/api/v1/auth/csrf/').json()['csrfToken']
        response = client.patch(self.notes_url, {'private_note': 'With CSRF'}, format='json', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        client.cookies.clear()
        response = client.patch(self.notes_url, {'private_note': 'Native'}, format='json', HTTP_AUTHORIZATION=f'Bearer {access}')
        self.assertEqual(response.status_code, 200)
