from io import StringIO

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from billing.entitlements import has_feature
from communities import privacy, services
from communities.models import CommunitySignal
from creator_insights.models import CreatorCollection, CreatorMetadataRequest
from inbox.models import Notification
from jokes.models import Joke, JokeReaction


class SeedShowcaseTests(TestCase):
    def test_refuses_outside_debug(self):
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            call_command('seed_showcase', stdout=StringIO())

    @override_settings(DEBUG=True, COMMUNITIES_MIN_REFRESH_SECONDS=0)
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
        # The reseed re-baselined formation tracking: already-active communities announce nothing.
        self.assertFalse(Notification.objects.filter(verb='community_formed').exists())
        self.assertEqual(rows['weather']['status'], 'cooling')
        self.assertEqual(rows['work']['status'], 'active')
        self.assertEqual(rows['space']['viewer']['content_count'], 1)
        reach = services.creator_reach(maya)
        self.assertIsNotNone(reach['audience']['size'])
        self.assertTrue(reach['opportunities'])

        # Every scripted account is established, so it counts toward communities.
        self.assertTrue(privacy.is_established(sam))
        self.assertTrue(privacy.is_established(maya))
        self.assertGreater(privacy.established_users().filter(email__startswith='fan').count(), 150)

        # Sam's one additional laugh makes him the fifth engaged member: Space activates.
        enjoyed = CommunitySignal.objects.filter(user=sam).values('joke_id')
        joke = Joke.objects.filter(context_tags__slug='space', content_tier='tier_1').exclude(pk__in=enjoyed).first()
        with self.captureOnCommitCallbacks(execute=True):
            JokeReaction.objects.create(user=sam, joke=joke, reaction='lol')
        rows = {r['slug']: r for r in services.directory(sam)['communities']}
        self.assertEqual(rows['space']['status'], 'active')
        self.assertTrue(rows['space']['viewer']['inferred'])
        self.assertIn('Your laughs made you part of it.', rows['space']['explanation'])

        # ...and the flip notifies Sam as a member and Maya and Priya as Space creators, once.
        priya = User.objects.get(email='priya@showcase.invalid')
        formed = Notification.objects.filter(verb='community_formed')
        self.assertEqual(set(formed.values_list('data__community', flat=True)), {'space'})
        self.assertEqual(formed.get(recipient=sam).data,
                         {'community': 'space', 'name': 'Space', 'emoji': '🚀', 'role': 'member'})
        self.assertEqual(formed.get(recipient=maya).data['role'], 'creator')
        self.assertEqual(formed.get(recipient=priya).data['role'], 'creator')
        self.assertFalse(formed.filter(recipient=theo).exists())
        self.assertEqual(formed.filter(data__role='member').count(), 5)
        total = formed.count()
        services.directory(sam)
        services.invalidate()
        services.directory(maya)
        self.assertEqual(formed.count(), total)
