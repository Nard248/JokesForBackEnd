from io import StringIO

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from billing.entitlements import has_feature
from communities import services
from creator_insights.models import CreatorCollection, CreatorMetadataRequest


class SeedShowcaseTests(TestCase):
    def test_refuses_outside_debug(self):
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            call_command('seed_showcase', stdout=StringIO())

    @override_settings(DEBUG=True)
    def test_builds_the_scripted_showcase_and_is_repeatable(self):
        cache.clear()
        call_command('seed_showcase', stdout=StringIO())
        call_command('seed_showcase', stdout=StringIO())  # rebuilds, never duplicates

        maya = User.objects.get(email='maya@showcase.invalid')
        theo = User.objects.get(email='theo@showcase.invalid')
        sam = User.objects.get(email='sam@showcase.invalid')
        self.assertTrue(has_feature(maya, 'creator_community_insights'))
        self.assertFalse(has_feature(theo, 'creator_community_insights'))
        self.assertEqual(CreatorCollection.objects.filter(owner=maya).count(), 2)
        self.assertEqual(CreatorMetadataRequest.objects.filter(owner=maya, status='pending').count(), 1)

        rows = {r['slug']: r for r in services.directory(sam)['communities']}
        self.assertEqual(rows['space']['status'], 'forming')
        self.assertEqual(rows['weather']['status'], 'cooling')
        self.assertEqual(rows['work']['status'], 'active')
        self.assertEqual(rows['space']['viewer']['content_count'], 1)
        reach = services.creator_reach(maya)
        self.assertIsNotNone(reach['audience']['size'])
        self.assertTrue(reach['opportunities'])
