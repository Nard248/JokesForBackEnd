from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.utils import timezone

from communities import formation, services
from communities.models import Community, CommunityMembership, CommunityState
from communities.tests.test_api import CommunityFixture
from inbox.models import Notification
from jokes.models import Joke, JokeSubmission

SPACE = {'community': 'space', 'name': 'Space', 'emoji': '🚀'}


class FormationNotificationTests(CommunityFixture):
    def setUp(self):
        super().setUp()
        self.directory()  # first sight: every community is recorded as forming
        self.community = Community.objects.get(tag=self.space)

    def formed(self, **filters):
        return Notification.objects.filter(verb='community_formed', **filters)

    def roles(self):
        return {n.recipient_id: n.data['role'] for n in self.formed()}

    def activate_space(self, names=('fan0', 'fan1', 'fan2', 'fan3', 'fan4')):
        fans = [self.person(name) for name in names]
        for fan in fans:
            self.enjoy(fan, self.space_jokes[:2])
        return fans

    def test_baseline_records_every_listed_community_without_notifying(self):
        self.assertEqual(CommunityState.objects.get(community=self.community).status, 'forming')
        self.assertFalse(self.formed().exists())

    def test_activation_notifies_counted_members_and_theme_creators(self):
        maya = self.person('maya')
        self.joke('maya on space', self.space, creator=maya)
        mature = self.person('mature')
        self.joke('mature on space', self.space, tier='tier_2', creator=mature)
        removed = self.person('removed')
        Joke.all_objects.filter(pk=self.joke('removed on space', self.space, creator=removed).pk).update(
            is_removed=True)
        gone = self.person('gone')
        self.joke('gone on space', self.space, creator=gone)
        gone.is_active = False
        gone.save(update_fields=['is_active'])
        office = self.person('office')
        self.joke('office creator', self.office, creator=office)
        quiet = self.person('quiet', consent=False)
        self.enjoy(quiet, self.space_jokes[:2])
        leaver = self.person('leaver')
        self.enjoy(leaver, self.space_jokes[:2])
        CommunityMembership.objects.create(user=leaver, community=self.community, state='left')
        joiner = self.person('joiner')
        CommunityMembership.objects.create(user=joiner, community=self.community, state='joined')
        fans = self.activate_space()

        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'active')
        expected = {fan.pk: 'member' for fan in fans}
        expected.update({joiner.pk: 'member', maya.pk: 'creator'})
        self.assertEqual(self.roles(), expected)
        notice = self.formed().get(recipient=fans[0])
        self.assertEqual(notice.data, {**SPACE, 'role': 'member'})
        self.assertIsNone(notice.actor_id)
        self.assertIsNone(notice.joke_id)
        self.assertFalse(notice.read)
        self.assertEqual(self.formed().get(recipient=maya).data, {**SPACE, 'role': 'creator'})
        state = CommunityState.objects.get(community=self.community)
        self.assertEqual((state.status, state.notified_at is not None), ('active', True))
        self.assertEqual(CommunityState.objects.get(community__tag=self.office).status, 'forming')

    def legacy_joke(self, text, submitter, status):
        joke = self.joke(text, self.space)
        JokeSubmission.objects.create(user=submitter, text=text, format=self.fmt, age_rating=self.age,
                                      language=self.lang, status=status, published_joke=joke)
        return joke

    def test_a_legacy_published_submission_counts_its_submitter_as_a_creator(self):
        legacy = self.person('legacy')
        self.legacy_joke('legacy on space', legacy, 'published')
        rejected = self.person('rejected')
        self.legacy_joke('rejected on space', rejected, 'rejected')
        pending = self.person('pending')
        self.legacy_joke('pending on space', pending, 'pending')
        fans = self.activate_space()

        self.directory()
        expected = {fan.pk: 'member' for fan in fans}
        expected[legacy.pk] = 'creator'
        self.assertEqual(self.roles(), expected)
        self.assertEqual(self.formed().get(recipient=legacy).data, {**SPACE, 'role': 'creator'})

    def test_a_creator_who_is_also_a_member_gets_one_creator_notice(self):
        both = self.person('both')
        self.joke('both on space', self.space, creator=both)
        self.activate_space(('fan1', 'fan2', 'fan3', 'fan4'))
        self.enjoy(both, self.space_jokes[:2])
        self.directory()
        self.assertEqual(list(self.formed().filter(recipient=both).values_list('data__role', flat=True)),
                         ['creator'])

    def test_the_same_activation_never_notifies_twice(self):
        fans = self.activate_space()
        self.directory()
        self.client.get('/api/v1/communities/space/')
        services.invalidate()
        self.directory()
        cache.clear()
        self.directory()
        self.assertEqual(self.formed().count(), 5)
        # An aggregate that finished late (computed before the last observation) is ignored.
        stale = timezone.now() - timedelta(minutes=5)
        formation.record_transitions({self.community.pk: 'forming'}, {}, stale)
        formation.record_transitions({self.community.pk: 'active'}, {self.community.pk: [fans[0].pk]},
                                     timezone.now())
        self.assertEqual(CommunityState.objects.get(community=self.community).status, 'active')
        self.assertEqual(self.formed().count(), 5)

    def test_brief_cooling_reactivates_silently_and_long_cooling_announces_again(self):
        a, b = self.person('a'), self.person('b')
        cid = self.community.pk
        start = timezone.now() + timedelta(minutes=1)

        def observe(status, days, members=()):
            return formation.record_transitions({cid: status}, {cid: [m.pk for m in members]},
                                                start + timedelta(days=days))

        self.assertEqual(observe('active', 0, [a]), [cid])
        self.assertEqual(observe('cooling', 1), [])
        self.assertEqual(observe('active', 3, [a, b]), [])  # back within 14 days: same formation
        self.assertEqual(self.formed().count(), 1)
        self.assertEqual(observe('forming', 4), [])
        self.assertEqual(observe('active', 4 + 13, [a, b]), [])
        self.assertEqual(observe('cooling', 18), [])
        self.assertEqual(observe('active', 18 + 14, [a, b]), [cid])
        self.assertEqual(self.formed().filter(recipient=a).count(), 2)
        self.assertEqual(self.formed().filter(recipient=b).count(), 1)

    def test_already_active_communities_are_a_baseline_not_an_announcement(self):
        CommunityState.objects.all().delete()
        self.activate_space()
        rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'active')
        self.assertFalse(self.formed().exists())
        state = CommunityState.objects.get(community=self.community)
        self.assertEqual(state.status, 'active')
        self.assertIsNotNone(state.active_since)
        self.assertIsNone(state.notified_at)

    def test_a_community_first_seen_cooling_rebounds_silently_within_fourteen_days(self):
        CommunityState.objects.all().delete()
        a = self.person('a')
        cid = self.community.pk
        start = timezone.now() + timedelta(minutes=1)

        def observe(status, days):
            return formation.record_transitions({cid: status}, {cid: [a.pk]}, start + timedelta(days=days))

        self.assertEqual(observe('cooling', 0), [])  # baseline: active last week, inactive now
        state = CommunityState.objects.get(community=self.community)
        self.assertEqual((state.status, state.inactive_since), ('cooling', start))
        self.assertEqual(observe('active', 13), [])  # same formation coming back
        self.assertFalse(self.formed().exists())
        self.assertEqual(observe('cooling', 14), [])
        self.assertEqual(observe('active', 14 + 14), [cid])  # inactive 14+ days: a new formation
        self.assertEqual(self.formed().filter(recipient=a).count(), 1)

    def test_a_community_first_seen_cooling_announces_after_fourteen_days(self):
        CommunityState.objects.all().delete()
        a = self.person('a')
        cid = self.community.pk
        start = timezone.now() + timedelta(minutes=1)
        formation.record_transitions({cid: 'cooling'}, {}, start)
        self.assertEqual(formation.record_transitions({cid: 'active'}, {cid: [a.pk]}, start + timedelta(days=14)),
                         [cid])
        self.assertEqual(self.formed().filter(recipient=a).count(), 1)

    def test_a_notification_failure_never_breaks_the_directory_and_is_retried(self):
        self.activate_space()
        with mock.patch.object(formation, '_notify', side_effect=RuntimeError('boom')), \
                self.assertLogs('communities.services', level='ERROR'):
            rows, _ = self.directory()
        self.assertEqual(rows['space']['status'], 'active')
        self.assertEqual(CommunityState.objects.get(community=self.community).status, 'forming')
        self.assertFalse(self.formed().exists())
        services.invalidate()
        self.directory()
        self.assertEqual(self.formed().count(), 5)

    def test_the_inbox_api_serves_the_notice_unchanged(self):
        fans = self.activate_space()
        self.directory()
        self.client.force_authenticate(fans[0])
        response = self.client.get('/api/v1/notifications/')
        self.assertEqual(response.status_code, 200)
        row = response.data['results'][0]
        self.assertEqual(row['verb'], 'community_formed')
        self.assertEqual(row['data'], {**SPACE, 'role': 'member'})
        self.assertIsNone(row['actor'])
        self.assertIsNone(row['joke'])
        self.assertEqual(self.client.get('/api/v1/notifications/unread-count/').data['count'], 1)
