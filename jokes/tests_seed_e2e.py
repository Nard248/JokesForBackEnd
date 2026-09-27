"""Local creator fixtures must never provision accounts against remote resources."""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from billing.models import Subscription
from jokes.management.commands.seed_e2e import Command
from jokes.models import Joke, JokeSubmission

LOCAL_STORAGE = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}}
EMAIL = 'creator-workbench@e2e.invalid'
PASSWORD = 'E2E-local-only-2026!'
PRIMARY_TEXT = '[e2e] Creator workbench: timing is everything.'


@override_settings(STORAGES=LOCAL_STORAGE)
class SeedE2ESafetyTests(SimpleTestCase):
    def test_production_mode_rejected_before_database_access(self):
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            Command().handle(fresh=True)

    @override_settings(DEBUG=True)
    def test_remote_and_implicit_database_hosts_rejected_before_access(self):
        for host in ('production.example.com', '', 'localhost,production.example.com'):
            with self.subTest(host=host), patch.dict(connection.settings_dict, {'HOST': host}):
                with self.assertRaises(CommandError):
                    Command().handle(fresh=True)

    @override_settings(DEBUG=True)
    def test_alternate_libpq_routing_rejected(self):
        for options in ({'hostaddr': '203.0.113.10'}, {'service': 'production'}):
            with self.subTest(options=options), patch.dict(
                connection.settings_dict, {'HOST': 'localhost', 'OPTIONS': options},
            ), self.assertRaises(CommandError):
                Command().handle(fresh=True)

    @override_settings(DEBUG=True, STORAGES={'default': {'BACKEND': 'storages.backends.gcloud.GoogleCloudStorage'}})
    def test_cloud_storage_rejected_before_access(self):
        with self.assertRaises(CommandError):
            Command().handle(fresh=True)


@override_settings(DEBUG=True, STORAGES=LOCAL_STORAGE)
class SeedE2ECreatorTests(TestCase):
    def seed(self, **options):
        with patch('jokes.models.Joke._generate_share_image'):
            call_command('seed_e2e', stdout=io.StringIO(), **options)

    def test_creator_login_inventory_and_idempotent_reseed(self):
        self.seed()
        creator = get_user_model().objects.get(email=EMAIL)
        self.assertTrue(creator.is_active)
        self.assertTrue(creator.check_password(PASSWORD))
        self.assertTrue(creator.profile.is_adult)
        self.assertTrue(creator.preference.onboarding_completed)
        self.assertFalse(creator.is_staff)
        self.assertFalse(creator.is_superuser)
        self.assertEqual(creator.subscription.plan.slug, 'creator_pro')
        self.assertEqual(creator.subscription.status, 'active')
        self.assertEqual(creator.subscription.stripe_subscription_id, '')
        joke = Joke.objects.get(creator=creator, text=PRIMARY_TEXT)
        self.assertTrue(joke.context_tags.filter(slug='e2e-creator-theme').exists())
        self.assertTrue(joke.tones.filter(slug='e2e-creator-category').exists())
        self.assertTrue(JokeSubmission.objects.filter(user=creator, published_joke=joke, status='published').exists())
        self.assertEqual(Joke.objects.filter(creator=creator).count(), 26)
        self.seed()
        self.assertEqual(Joke.objects.filter(creator=creator).count(), 26)
        self.assertEqual(Subscription.objects.filter(user=creator).count(), 1)
        # Exercise the normal login endpoint, without force_authenticate or a
        # test-only login route, then use the real creator feature permission.
        client = APIClient()
        response = client.post('/api/v1/auth/login/', {'email': EMAIL, 'password': PASSWORD}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(client.get('/api/v1/creators/me/content/').status_code, 200)

    def test_fresh_rebuild_keeps_single_creator_submission_and_unrelated_data(self):
        self.seed()
        creator = get_user_model().objects.get(email=EMAIL)
        joke = Joke.objects.get(creator=creator, text=PRIMARY_TEXT)
        with patch('jokes.models.Joke._generate_share_image'):
            unrelated = Joke.objects.create(
                text='Unrelated local content', format=joke.format,
                age_rating=joke.age_rating, language=joke.language,
            )
        self.seed(fresh=True)
        self.assertTrue(Joke.objects.filter(pk=unrelated.pk).exists())
        self.assertEqual(Joke.objects.filter(creator=creator).count(), 26)
        self.assertEqual(JokeSubmission.objects.filter(user=creator).count(), 1)
