"""Submitting without a language must work, not 500.

`JokeSubmissionCreateSerializer` advertises `language` as optional while the
column is NOT NULL, so an omitted language reached the database and raised
IntegrityError — a 500 in response to a request the API said was valid. Any
client that trusted the contract hit it; the iOS composer did, on its first
submission.
"""
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from jokes.models import AgeRating, Format, JokeSubmission, Language

User = get_user_model()


class SubmitWithoutLanguageTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='writer@test.com', email='writer@test.com', password='x',
        )
        cls.url = reverse('joke-submit')

    def setUp(self):
        self.client.force_authenticate(self.user)

    def test_a_submission_without_a_language_is_accepted(self):
        response = self.client.post(self.url, {
            'format': 'oneliner',
            'age_rating': AgeRating.objects.first().slug,
            'text': 'A one-liner sent without naming a language.',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.content[:400])
        submission = JokeSubmission.objects.get(pk=response.json()['id'])
        self.assertEqual(submission.language.code, 'en')
        self.assertEqual(submission.status, 'pending')

    def test_an_explicit_language_still_wins(self):
        other = Language.objects.exclude(code='en').first()
        if other is None:
            self.skipTest('only one language configured')
        response = self.client.post(self.url, {
            'format': 'oneliner',
            'age_rating': AgeRating.objects.first().slug,
            'text': 'A one-liner that names its language.',
            'language': other.code,
        }, format='json')

        self.assertEqual(response.status_code, 201, response.content[:400])
        submission = JokeSubmission.objects.get(pk=response.json()['id'])
        self.assertEqual(submission.language.code, other.code)
