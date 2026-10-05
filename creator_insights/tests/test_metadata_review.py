"""Taxonomy proposals never publish themselves or bypass human moderation."""
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from audit.models import AuditLog
from billing.models import Plan, Subscription
from creator_insights.admin import CreatorMetadataRequestAdmin
from creator_insights.library import review_metadata_request
from creator_insights.models import CreatorMetadataRequest, CreatorWorkspaceNote
from jokes.models import AgeRating, ContextTag, Format, Joke, Language, Tone

User = get_user_model()
URL = '/api/v1/creators/me/content/metadata-requests/'


class CreatorMetadataReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username='metadata-owner')
        cls.other = User.objects.create_user(username='metadata-other')
        cls.staff = User.objects.create_user(username='metadata-staff', is_staff=True)
        cls.moderator = User.objects.create_superuser(username='metadata-moderator', email='moderator@example.com', password='test')
        Subscription.objects.create(user=cls.owner, plan=Plan.objects.get(slug='creator_pro'), status='active')
        with patch('jokes.models.Joke._generate_share_image'):
            fields = {
                'format': Format.objects.get(slug='oneliner'),
                'age_rating': AgeRating.objects.first(), 'language': Language.objects.get(code='en'),
            }
            cls.joke = Joke.objects.create(text='Published content remains stable', creator=cls.owner, **fields)
            cls.second = Joke.objects.create(text='Another published joke', creator=cls.owner, **fields)
        cls.theme = ContextTag.objects.create(slug='review-theme', name='Review theme')
        cls.category = Tone.objects.create(slug='review-category', name='Review category')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.request = RequestFactory().post('/admin/creator_insights/creatormetadatarequest/')
        self.request.user = self.moderator

    def propose(self, **overrides):
        data = {'joke_ids': [self.joke.pk], 'themes': [self.theme.slug], 'reason': 'Correct the topic'}
        data.update(overrides)
        response = self.client.post(URL, data, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.data['results']

    def test_proposal_leaves_public_joke_unchanged_until_review(self):
        review = self.propose(categories=[self.category.slug])[0]
        self.assertEqual(review['status'], 'pending')
        self.assertFalse(self.joke.context_tags.exists())
        self.assertFalse(self.joke.tones.exists())
        before = Joke.objects.values().get(pk=self.joke.pk)
        total = Joke.objects.count()
        approved = review_metadata_request(self.request, review['id'], approve=True)
        after = Joke.objects.values().get(pk=self.joke.pk)
        self.assertEqual(approved.status, 'approved')
        self.assertEqual(approved.before_metadata['themes'], [])
        self.assertEqual(approved.after_metadata['themes'], [self.theme.slug])
        self.assertEqual(list(self.joke.tones.values_list('slug', flat=True)), [self.category.slug])
        self.assertEqual(Joke.objects.count(), total)
        before.pop('updated_at')
        after.pop('updated_at')
        # Database triggers refresh both indexed documents for approved tags.
        for field in ('search_vector', 'search_vector_simple'):
            before.pop(field)
            after.pop(field)
        self.assertEqual(before, after)
        self.assertTrue(Joke.objects.search('review category').filter(pk=self.joke.pk).exists())
        self.assertEqual(AuditLog.objects.filter(action='creator_metadata_review', target_id=str(review['id'])).count(), 1)
        self.assertNotIn('Correct the topic', str(AuditLog.objects.get(action='creator_metadata_review').metadata))

    def test_duplicate_pending_request_rejects_entire_batch(self):
        self.propose()
        response = self.client.post(URL, {
            'joke_ids': [self.second.pk, self.joke.pk], 'categories': [self.category.slug],
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(CreatorMetadataRequest.objects.count(), 1)
        self.assertFalse(self.second.tones.exists())

    def test_all_proposal_fields_and_limits_are_strict(self):
        for changes in [
            {'themes': ['unknown-tag']}, {'themes': [self.theme.slug] * 2},
            {'themes': ['x'] * 31}, {'reason': 'x' * 1001},
            {'text': 'Publish directly'}, {'content_tier': 'tier_1'},
            {'owner': self.other.pk}, {'status': 'approved'},
            {'joke_ids': [self.joke.pk] * 2}, {'joke_ids': list(range(1, 52))},
            {'joke_ids': []},
        ]:
            with self.subTest(changes=changes):
                data = {'joke_ids': [self.joke.pk], 'themes': [self.theme.slug], **changes}
                self.assertEqual(self.client.post(URL, data, format='json').status_code, 400)
        self.assertEqual(self.client.post(URL, {'joke_ids': [self.joke.pk]}, format='json').status_code, 400)
        self.assertFalse(CreatorMetadataRequest.objects.exists())

    def test_stale_baseline_rejects_without_overwriting_newer_taxonomy(self):
        review = self.propose()[0]
        self.joke.tones.add(self.category)
        rejected = review_metadata_request(self.request, review['id'], approve=True)
        self.assertEqual(rejected.status, 'rejected')
        self.assertIn('changed', rejected.decision_reason)
        self.assertFalse(self.joke.context_tags.exists())
        self.assertTrue(self.joke.tones.filter(pk=self.category.pk).exists())

    def test_removed_or_reassigned_or_prohibited_joke_cannot_be_approved(self):
        for fields in [
            {'is_removed': True}, {'creator': self.other}, {'content_tier': 'tier_3'},
        ]:
            with self.subTest(fields=fields):
                Joke.all_objects.filter(pk=self.joke.pk).update(is_removed=False, creator=self.owner, content_tier='tier_1')
                review = self.propose()[0]
                Joke.all_objects.filter(pk=self.joke.pk).update(**fields)
                result = review_metadata_request(self.request, review['id'], approve=True)
                self.assertEqual(result.status, 'rejected')
                self.assertFalse(self.joke.context_tags.exists())

    def test_deleted_requested_tag_rejects_whole_proposal(self):
        review = self.propose(categories=[self.category.slug])[0]
        self.theme.delete()
        result = review_metadata_request(self.request, review['id'], approve=True)
        self.assertEqual(result.status, 'rejected')
        self.assertFalse(self.joke.tones.exists())

    def test_decisions_are_idempotent_and_cannot_be_reversed_by_second_action(self):
        review = self.propose()[0]
        approved = review_metadata_request(self.request, review['id'], approve=True)
        reviewed_at = approved.reviewed_at
        result = review_metadata_request(self.request, review['id'], approve=False, reason='Later click')
        self.assertEqual(result.status, 'approved')
        self.assertEqual(result.reviewed_at, reviewed_at)
        self.assertEqual(AuditLog.objects.filter(action='creator_metadata_review').count(), 1)

    def test_omit_means_unchanged_and_empty_means_clear(self):
        self.joke.tones.add(self.category)
        self.joke.context_tags.add(self.theme)
        review = self.propose(themes=[])[0]
        review_metadata_request(self.request, review['id'], approve=True)
        self.assertFalse(self.joke.context_tags.exists())
        self.assertTrue(self.joke.tones.exists())

    def test_moderator_permission_required_and_admin_proposals_are_immutable(self):
        review = self.propose()[0]
        for user in [self.owner, self.staff]:
            self.request.user = user
            with self.assertRaises(PermissionDenied):
                review_metadata_request(self.request, review['id'], approve=True)
        registered = CreatorMetadataRequestAdmin(CreatorMetadataRequest, admin.site)
        self.assertIn('changes', registered.readonly_fields)
        self.assertIn('status', registered.readonly_fields)
        self.assertIn('before_metadata', registered.readonly_fields)
        self.assertFalse(registered.has_add_permission(self.request))
        self.assertFalse(registered.has_delete_permission(self.request))
        self.assertNotIn(CreatorWorkspaceNote, admin.site._registry)

    def test_request_history_is_private_filters_unavailable_and_survives_cancellation(self):
        self.propose()
        Subscription.objects.filter(user=self.owner).update(status='canceled')
        self.owner.refresh_from_db()
        self.assertEqual(self.client.get(URL).data['count'], 1)
        self.assertEqual(self.client.post(URL, {'joke_ids': [self.second.pk], 'themes': []}, format='json').status_code, 403)
        Joke.objects.filter(pk=self.joke.pk).update(is_removed=True)
        self.assertEqual(self.client.get(URL).data['count'], 0)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(URL).data['count'], 0)

    def test_expired_subscription_cannot_submit_changes(self):
        Subscription.objects.filter(user=self.owner).update(status='past_due')
        self.owner.refresh_from_db()
        response = self.client.post(URL, {'joke_ids': [self.joke.pk], 'themes': [self.theme.slug]}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(CreatorMetadataRequest.objects.exists())
