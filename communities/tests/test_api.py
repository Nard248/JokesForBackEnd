from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from billing.models import Plan, Subscription
from communities import materialize, services
from communities.models import Community, CommunityMembership
from jokes.models import (
    AgeRating,
    AnalyticsConsentRecord,
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
OPTED_IN = timezone.now() - timedelta(days=365)
JOINED = timezone.now() - timedelta(days=400)


# Exact-count assertions: noise off here; communities/tests/test_privacy.py covers it.
@override_settings(COMMUNITIES_MIN_REFRESH_SECONDS=0, COMMUNITIES_NOISE_EPSILON=0)
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
        # Untagged jokes people enjoy to become established (3+ distinct jokes)
        # without touching any community's numbers.
        self.warmup_jokes = [self.joke(f'warm-up {i}', None) for i in range(3)]

    def joke(self, text, tag, tier='tier_1', creator=None):
        joke = Joke.objects.create(text=text, format=self.fmt, age_rating=self.age, language=self.lang,
                                   content_tier=tier, creator=creator)
        if tag is not None:
            joke.context_tags.add(tag)
        return joke

    def person(self, name, adult=True, consent=True, established=True):
        user = User.objects.create_user(username=name, email=f'{name}@example.test', password='pw-12345678')
        user.profile.date_of_birth = date(1990, 1, 1) if adult else date.today() - timedelta(days=365 * 15)
        user.profile.share_analytics = consent
        user.profile.save()
        if consent:
            AnalyticsConsentRecord.objects.create(user=user, enabled=True, policy_version='test',
                                                  provenance='preference', recorded_at=OPTED_IN)
        if established:
            self.establish(user)
        return user

    def establish(self, user):
        User.objects.filter(pk=user.pk).update(date_joined=JOINED)
        for joke in self.warmup_jokes:
            JokeReaction.objects.create(user=user, joke=joke, reaction='lol')

    def enjoy(self, user, jokes):
        with self.captureOnCommitCallbacks(execute=True):
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
        materialize.rebuild()  # QuerySet.update bypasses the model signals that maintain the mirror
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

    @override_settings(COMMUNITIES_MIN_REFRESH_SECONDS=60)
    def test_engagement_bursts_cannot_force_recomputation(self):
        for i in range(4):
            self.enjoy(self.person(f'fan{i}'), self.space_jokes[:2])
        self.directory()
        self.enjoy(self.person('fan4'), self.space_jokes[:2])
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'forming')  # stale within the refresh floor

    def test_small_communities_hide_activity_and_score(self):
        self.enjoy(self.person('lonely'), self.space_jokes[:2])
        rows, _ = self.directory()
        self.assertIsNone(rows['space']['activity'])
        self.assertIsNone(rows['space']['score'])

    def test_explicit_joins_by_non_sharing_adults_are_not_counted(self):
        for i in range(5):
            self.enjoy(self.person(f'fan{i}'), self.space_jokes[:2])
        for i in range(3):
            CommunityMembership.objects.create(user=self.person(f'quiet{i}', consent=False),
                                               community=self.space.community, state='joined')
        rows, _ = self.directory()
        self.assertEqual(rows['space']['members'], 5)

    def test_reactions_before_opting_in_do_not_count(self):
        for i in range(5):
            fan = self.person(f'fan{i}')
            self.enjoy(fan, self.space_jokes[:2])
            AnalyticsConsentRecord.objects.filter(user=fan).update(recorded_at=timezone.now() + timedelta(minutes=1))
        services.invalidate()
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'forming')

    def test_consent_withdrawal_invalidates_after_commit(self):
        fans = [self.person(f'fan{i}') for i in range(5)]
        for fan in fans:
            self.enjoy(fan, self.space_jokes[:2])
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'active')
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            fans[0].profile.share_analytics = False
            fans[0].profile.save()
        self.assertTrue(callbacks)  # invalidation is deferred to commit
        for callback in callbacks:
            callback()
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'forming')

    def test_anonymous_shares_do_not_affect_trending(self):
        fan = self.person('fan')
        self.enjoy(fan, self.space_jokes[2:3])
        for _ in range(10):
            ShareEvent.objects.create(user=None, joke=self.space_jokes[0], platform='copy')
        response = self.client.get('/api/v1/communities/space/')
        self.assertEqual(response.data['trending'][0]['id'], self.space_jokes[2].pk)

    def test_lost_version_key_never_serves_stale_data(self):
        fans = [self.person(f'fan{i}') for i in range(5)]
        for fan in fans[:4]:
            self.enjoy(fan, self.space_jokes[:2])
        self.directory()
        JokeReaction.objects.create(user=fans[4], joke=self.space_jokes[0], reaction='lol')
        Favorite.objects.create(user=fans[4], joke=self.space_jokes[1])  # no on_commit in TestCase
        cache.delete(services.VERSION_KEY)  # e.g. culled by DatabaseCache
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'active')

    def test_public_counts_are_coarsened(self):
        for i in range(7):
            self.enjoy(self.person(f'fan{i}'), self.space_jokes[:2])
        rows, _ = self.directory()
        self.assertEqual(rows['space']['members'], 5)
        self.assertIn('About 5 people', rows['space']['explanation'])

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
        self.assertEqual(rows['space']['members'], 5)  # 6 rounds to the nearest 5

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


    def test_detail_jokes_follow_the_default_language(self):
        french = Language.objects.get_or_create(code='fr', defaults={'name': 'French'})[0]
        foreign = self.joke('espace', self.space)
        Joke.objects.filter(pk=foreign.pk).update(language=french)

        def ids(params=None):
            data = self.client.get('/api/v1/communities/space/', params or {}).data
            return {j['id'] for j in data['trending'] + data['newest']}

        self.assertNotIn(foreign.pk, ids())
        self.assertIn(foreign.pk, ids({'language': 'fr'}))
        self.assertIn(foreign.pk, ids({'language': 'all'}))

    def test_detail_query_count_does_not_grow_with_jokes(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from jokes.models import Country, CultureTag
        spain = Country.objects.get(code='ES')
        culture = CultureTag.objects.create(slug='detail-culture', name='Detail culture')

        def tag_all():
            for joke in Joke.objects.filter(context_tags=self.space):
                joke.countries.add(spain)
                joke.culture_tags.add(culture)

        def count():
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get('/api/v1/communities/space/')
            self.assertEqual(response.status_code, 200)
            return len(ctx.captured_queries), len(response.data['trending']) + len(response.data['newest'])

        tag_all()
        count()  # warm the community aggregate cache
        few, few_rows = count()
        for i in range(4):
            self.joke(f'extra space {i}', self.space)
        tag_all()
        count()
        many, many_rows = count()
        self.assertGreater(many_rows, few_rows)
        self.assertEqual(few, many)


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
        self.assertEqual(rows['space']['reached_members'], 5)  # coarsened to multiples of 5
        self.assertEqual(rows['space']['members'], 5)
        self.assertEqual(rows['space']['reach_rate'], 100)
        self.assertEqual(rows['space']['your_jokes'], 2)
        self.assertEqual(response.data['audience']['size'], 5)
        kinds = {o['kind']: o for o in response.data['opportunities']}
        self.assertEqual(kinds['stronghold']['slug'], 'space')
        self.assertEqual(kinds['untapped']['slug'], 'office-life')

    def test_reach_is_a_daily_snapshot(self):
        self.pro()
        fans = [self.person(f'fan{i}') for i in range(6)]
        for fan in fans[:5]:
            self.enjoy(fan, self.mine)
        self.client.force_authenticate(self.creator)
        first = self.client.get('/api/v1/creators/me/communities/').data
        self.enjoy(fans[5], self.mine)  # one more reader the same day
        second = self.client.get('/api/v1/creators/me/communities/').data
        self.assertEqual(first, second)

    def test_withdrawn_consent_leaves_creator_reach_immediately(self):
        self.pro()
        fans = [self.person(f'fan{i}') for i in range(5)]
        for fan in fans:
            self.enjoy(fan, self.mine)
        self.client.force_authenticate(self.creator)
        self.assertEqual(self.client.get('/api/v1/creators/me/communities/').data['audience']['size'], 5)
        fans[0].profile.share_analytics = False
        fans[0].profile.save()
        self.assertIsNone(self.client.get('/api/v1/creators/me/communities/').data['audience']['size'])

    def test_small_reach_is_suppressed(self):
        self.pro()
        for i in range(3):
            self.enjoy(self.person(f'fan{i}'), self.mine)
        self.client.force_authenticate(self.creator)
        response = self.client.get('/api/v1/creators/me/communities/')
        self.assertIsNone(response.data['audience']['size'])
        self.assertTrue(all(r['reached_members'] is None for r in response.data['communities']))


class EstablishedAccountTests(CommunityFixture):
    """Sybil resistance: only established accounts move community numbers."""

    def test_new_accounts_cannot_activate_a_community(self):
        fans = [self.person(f'new{i}', established=False) for i in range(5)]
        for fan in fans:
            for joke in self.warmup_jokes:
                JokeReaction.objects.create(user=fan, joke=joke, reaction='lol')
            self.enjoy(fan, self.space_jokes[:2])
        rows, data = self.directory()
        self.assertEqual(rows['space']['status'], 'forming')
        self.assertIsNone(data['stats']['members'])
        # A week later the same accounts are established and the community forms.
        User.objects.filter(pk__in=[f.pk for f in fans]).update(date_joined=timezone.now() - timedelta(days=8))
        services.invalidate()
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'active')

    def test_accounts_need_signals_on_three_distinct_jokes(self):
        fans = [self.person(f'thin{i}', established=False) for i in range(5)]
        User.objects.filter(pk__in=[f.pk for f in fans]).update(date_joined=JOINED)
        for fan in fans:
            self.enjoy(fan, self.space_jokes[:2])  # two jokes: a member by taste, not yet counted
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'forming')
        for fan in fans:
            self.enjoy(fan, self.office_jokes[:1])  # any third joke establishes the account
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'active')

    def test_thresholds_are_settings(self):
        fans = [self.person(f'new{i}', established=False) for i in range(5)]
        for fan in fans:
            self.enjoy(fan, self.space_jokes[:2])
        with self.settings(COMMUNITIES_ESTABLISHED_ACCOUNT_DAYS=0, COMMUNITIES_ESTABLISHED_MIN_JOKES=2):
            services.invalidate()
            rows, data = self.directory()
            self.assertEqual(rows['space']['status'], 'active')
            self.assertEqual(data['methodology']['established_min_jokes'], 2)

    def test_explicit_joins_by_new_accounts_change_only_their_own_view(self):
        for i in range(5):
            self.enjoy(self.person(f'fan{i}'), self.space_jokes[:2])
        joiners = [self.person(f'sock{i}', established=False) for i in range(5)]
        for sock in joiners:
            CommunityMembership.objects.create(user=sock, community=self.space.community, state='joined')
        rows, data = self.directory(joiners[0])
        self.assertEqual(rows['space']['members'], 5)
        self.assertEqual(data['stats']['members'], 5)
        self.assertTrue(rows['space']['viewer']['member'])
        self.assertEqual(rows['space']['viewer']['explicit'], 'joined')
        self.assertFalse(data['viewer']['counted'])
        self.assertIn('space', data['viewer']['communities'])

    def test_new_consenting_viewer_learns_when_they_will_count(self):
        me = self.person('me', established=False)
        self.enjoy(me, self.space_jokes[:2])
        rows, data = self.directory(me)
        self.assertFalse(data['viewer']['counted'])
        self.assertTrue(data['viewer']['shares_analytics'])
        self.assertTrue(rows['space']['viewer']['inferred'])
        self.assertIn('7 days old', rows['space']['explanation'])

    def test_new_accounts_do_not_count_toward_creator_reach(self):
        creator = self.person('creator')
        mine = [self.joke(f'mine {i}', self.space, creator=creator) for i in range(2)]
        Subscription.objects.create(user=creator, plan=Plan.objects.get(slug='creator_pro'), status='active')
        for i in range(6):
            self.enjoy(self.person(f'sock{i}', established=False), mine)
        self.client.force_authenticate(creator)
        response = self.client.get('/api/v1/creators/me/communities/')
        self.assertIsNone(response.data['audience']['size'])
        self.assertTrue(all(r['reached_members'] is None for r in response.data['communities']))
