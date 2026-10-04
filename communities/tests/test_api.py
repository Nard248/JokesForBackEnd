from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from billing.models import Plan, Subscription
from communities import services
from communities.models import Community, CommunityMembership
from jokes.models import (
    AgeRating,
    ContextTag,
    Favorite,
    Format,
    Joke,
    JokeReaction,
    Language,
    SavedJoke,
    ShareEvent,
)

User = get_user_model()


class CommunityFixture(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.fmt = Format.objects.get_or_create(slug='oneliner', defaults={'name': 'One-liner'})[0]
        self.age = AgeRating.objects.order_by('min_age').first() or AgeRating.objects.create(
            code='all', name='All', min_age=0)
        self.lang = Language.objects.get_or_create(code='en', defaults={'name': 'English'})[0]
        self.space = ContextTag.objects.create(name='Space', slug='space')
        self.office = ContextTag.objects.create(name='Office life', slug='office-life')
        self.space_jokes = [self.joke(f'space {i}', self.space) for i in range(3)]
        self.office_jokes = [self.joke(f'office {i}', self.office) for i in range(3)]

    def joke(self, text, tag, tier='tier_1', creator=None):
        joke = Joke.objects.create(text=text, format=self.fmt, age_rating=self.age, language=self.lang,
                                   content_tier=tier, creator=creator)
        joke.context_tags.add(tag)
        return joke

    def person(self, name, adult=True, consent=True):
        user = User.objects.create_user(username=name, email=f'{name}@example.test', password='pw-12345678')
        user.profile.date_of_birth = date(1990, 1, 1) if adult else date.today() - timedelta(days=365 * 15)
        user.profile.share_analytics = consent
        user.profile.save()
        return user

    def enjoy(self, user, jokes):
        for joke in jokes:
            JokeReaction.objects.create(user=user, joke=joke, reaction='lol')
            Favorite.objects.create(user=user, joke=joke)

    def directory(self, user=None):
        self.client.force_authenticate(user)
        response = self.client.get('/api/v1/communities/')
        self.assertEqual(response.status_code, 200)
        return {row['slug']: row for row in response.data['communities']}, response.data


class FormationTests(CommunityFixture):
    def test_every_theme_has_a_community(self):
        self.assertTrue(Community.objects.filter(tag=self.space).exists())
        rows, _ = self.directory()
        self.assertIn('space', rows)
        self.assertEqual(rows['space']['emoji'], '🚀')

    def test_five_consenting_adults_form_an_active_community(self):
        for i in range(5):
            self.enjoy(self.person(f'fan{i}'), self.space_jokes[:2])
        rows, data = self.directory()
        self.assertEqual(rows['space']['status'], 'active')
        self.assertEqual(rows['space']['members'], 5)
        self.assertEqual(rows['office-life']['status'], 'forming')
        self.assertEqual(data['stats']['active_communities'], 1)

    def test_small_counts_are_suppressed(self):
        for i in range(4):
            self.enjoy(self.person(f'fan{i}'), self.space_jokes[:2])
        rows, data = self.directory()
        self.assertEqual(rows['space']['status'], 'forming')
        self.assertIsNone(rows['space']['members'])
        self.assertIsNone(data['stats']['members'])

    def test_non_consenting_and_minor_signals_never_count(self):
        for i in range(3):
            self.enjoy(self.person(f'fan{i}'), self.space_jokes[:2])
        self.enjoy(self.person('quiet', consent=False), self.space_jokes[:2])
        self.enjoy(self.person('teen', adult=False), self.space_jokes[:2])
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'forming')

    def test_one_joke_or_views_alone_do_not_infer_membership(self):
        for i in range(6):
            self.enjoy(self.person(f'fan{i}'), self.space_jokes[:1])
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'forming')

    def test_mature_and_removed_jokes_cannot_form_communities(self):
        mature = [self.joke(f'm{i}', self.space, tier='tier_2') for i in range(2)]
        for i in range(5):
            self.enjoy(self.person(f'fan{i}'), mature)
        removed = self.space_jokes[:2]
        Joke.objects.filter(pk__in=[j.pk for j in removed]).update(is_removed=True)
        for i in range(5, 10):
            self.enjoy(self.person(f'fan{i}'), removed)
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'forming')

    def test_negative_reactions_are_not_enjoyment(self):
        for i in range(5):
            user = self.person(f'fan{i}')
            for joke in self.space_jokes:
                JokeReaction.objects.create(user=user, joke=joke, reaction='eyeroll')
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'forming')

    def test_saves_and_shares_count(self):
        for i in range(5):
            user = self.person(f'fan{i}')
            for joke in self.space_jokes[:2]:
                SavedJoke.objects.create(user=user, joke=joke)
                ShareEvent.objects.create(user=user, joke=joke, platform='copy')
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'active')

    def test_decayed_signals_cool_a_community(self):
        fans = [self.person(f'fan{i}') for i in range(5)]
        for fan in fans:
            self.enjoy(fan, self.space_jokes[:2])
        old = timezone.now() - timedelta(days=21)
        JokeReaction.objects.update(updated_at=old)
        Favorite.objects.update(created_at=old)
        rows, _ = self.directory()
        self.assertNotEqual(rows['space']['status'], 'active')

    def test_overlapping_members_create_a_bridge(self):
        for i in range(5):
            fan = self.person(f'fan{i}')
            self.enjoy(fan, self.space_jokes[:2])
            self.enjoy(fan, self.office_jokes[:2])
        _, data = self.directory()
        self.assertEqual(data['bridges'], [{'source': 'office-life', 'target': 'space', 'members': 5}])
        self.assertEqual(data['stats']['multi_community_members'], 5)

    def test_engagement_invalidates_the_cached_aggregate(self):
        fans = [self.person(f'fan{i}') for i in range(5)]
        for fan in fans[:4]:
            self.enjoy(fan, self.space_jokes[:2])
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'forming')
        self.enjoy(fans[4], self.space_jokes[:2])
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'active')

    def test_payload_never_contains_user_identities(self):
        fans = [self.person(f'fan{i}') for i in range(6)]
        for fan in fans:
            self.enjoy(fan, self.space_jokes[:2])
        _, data = self.directory()
        body = str(data)
        for fan in fans:
            self.assertNotIn(fan.username, body)
        self.assertNotIn('members_ids', body)


class ViewerTests(CommunityFixture):
    def test_anonymous_viewer_has_no_personal_state(self):
        rows, data = self.directory()
        self.assertIsNone(data['viewer'])
        self.assertIsNone(rows['space']['viewer'])

    def test_viewer_sees_own_progress_even_without_analytics(self):
        me = self.person('me', consent=False)
        self.enjoy(me, self.space_jokes[:2])
        rows, data = self.directory(me)
        self.assertFalse(data['viewer']['counted'])
        self.assertTrue(rows['space']['viewer']['inferred'])
        self.assertIn('turn on audience analytics', rows['space']['explanation'])
        self.assertEqual(rows['space']['viewer']['progress'], 1.0)

    def test_join_and_leave_persist_and_leave_overrides_inference(self):
        me = self.person('me')
        self.enjoy(me, self.space_jokes[:2])
        self.client.force_authenticate(me)
        response = self.client.post('/api/v1/communities/space/membership/', {'action': 'leave'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['viewer']['member'])
        self.assertEqual(response.data['viewer']['explicit'], 'left')
        rows, data = self.directory(me)
        self.assertNotIn('space', data['viewer']['communities'])
        response = self.client.post('/api/v1/communities/office-life/membership/', {'action': 'join'}, format='json')
        self.assertTrue(response.data['viewer']['member'])
        self.assertEqual(CommunityMembership.objects.get(user=me, community__tag=self.office).state, 'joined')

    def test_explicit_memberships_are_in_the_account_export(self):
        me = self.person('me')
        CommunityMembership.objects.create(user=me, community=self.space.community, state='joined')
        self.client.force_authenticate(me)
        response = self.client.get('/api/v1/users/me/data-export/')
        self.assertEqual(response.status_code, 200)
        import io
        import json
        import zipfile
        if response.get('Content-Type', '').startswith('application/zip'):
            archive = zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content)
                                                 if response.streaming else response.content))
            payload = json.loads(archive.read(archive.namelist()[0]))
        else:
            payload = response.json()
        self.assertEqual(payload['community_memberships'][0]['community'], 'space')

    def test_explicit_joins_never_activate_a_community(self):
        for i in range(6):
            CommunityMembership.objects.create(user=self.person(f'j{i}'), community=self.space.community,
                                               state='joined')
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'forming')
        self.assertEqual(rows['space']['members'], 6)

    def test_membership_requires_auth_and_valid_action(self):
        response = self.client.post('/api/v1/communities/space/membership/', {'action': 'join'}, format='json')
        self.assertIn(response.status_code, (401, 403))
        self.client.force_authenticate(self.person('me'))
        response = self.client.post('/api/v1/communities/space/membership/', {'action': 'own'}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/v1/communities/nope/membership/', {'action': 'join'}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_unlisted_communities_are_hidden(self):
        Community.objects.filter(tag=self.office).update(is_listed=False)
        services.invalidate()
        rows, _ = self.directory()
        self.assertNotIn('office-life', rows)
        self.assertEqual(self.client.get('/api/v1/communities/office-life/').status_code, 404)


class DetailTests(CommunityFixture):
    def test_detail_lists_visible_trending_jokes_and_respects_tiers(self):
        mature = self.joke('mature space', self.space, tier='tier_2')
        fan = self.person('fan')
        self.enjoy(fan, self.space_jokes[1:2])
        response = self.client.get('/api/v1/communities/space/')
        self.assertEqual(response.status_code, 200)
        ids = [j['id'] for j in response.data['trending']]
        self.assertEqual(ids[0], self.space_jokes[1].pk)
        self.assertNotIn(mature.pk, ids)
        self.assertNotIn(mature.pk, [j['id'] for j in response.data['newest']])

    def test_detail_lists_public_creators_only(self):
        public = self.person('public_creator')
        hidden = self.person('hidden_creator')
        hidden.profile.public_profile = False
        hidden.profile.save()
        self.joke('mine', self.space, creator=public)
        self.joke('secret', self.space, creator=hidden)
        response = self.client.get('/api/v1/communities/space/')
        self.assertEqual([c['id'] for c in response.data['creators']], [public.pk])


class CreatorReachTests(CommunityFixture):
    def setUp(self):
        super().setUp()
        self.creator = self.person('creator')
        self.mine = [self.joke(f'mine {i}', self.space, creator=self.creator) for i in range(2)]

    def pro(self):
        Subscription.objects.create(user=self.creator, plan=Plan.objects.get(slug='creator_pro'), status='active')

    def test_requires_creator_pro(self):
        self.client.force_authenticate(self.creator)
        self.assertEqual(self.client.get('/api/v1/creators/me/communities/').status_code, 403)

    def test_requires_published_jokes(self):
        nobody = self.person('nobody')
        Subscription.objects.create(user=nobody, plan=Plan.objects.get(slug='creator_pro'), status='active')
        self.client.force_authenticate(nobody)
        self.assertEqual(self.client.get('/api/v1/creators/me/communities/').status_code, 403)

    def test_reach_counts_audience_members_and_suggests_openings(self):
        self.pro()
        for i in range(6):
            fan = self.person(f'fan{i}')
            self.enjoy(fan, self.mine)
            self.enjoy(fan, self.office_jokes[:2])
        self.enjoy(self.creator, self.mine)  # own activity is excluded
        self.client.force_authenticate(self.creator)
        response = self.client.get('/api/v1/creators/me/communities/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        rows = {r['slug']: r for r in response.data['communities']}
        self.assertEqual(rows['space']['reached_members'], 6)
        self.assertEqual(rows['space']['reach_rate'], 100.0)
        self.assertEqual(rows['space']['your_jokes'], 2)
        self.assertEqual(response.data['audience']['size'], 6)
        kinds = {o['kind']: o for o in response.data['opportunities']}
        self.assertEqual(kinds['stronghold']['slug'], 'space')
        self.assertEqual(kinds['untapped']['slug'], 'office-life')

    def test_small_reach_is_suppressed(self):
        self.pro()
        for i in range(3):
            self.enjoy(self.person(f'fan{i}'), self.mine)
        self.client.force_authenticate(self.creator)
        response = self.client.get('/api/v1/creators/me/communities/')
        self.assertIsNone(response.data['audience']['size'])
        self.assertTrue(all(r['reached_members'] is None for r in response.data['communities']))
