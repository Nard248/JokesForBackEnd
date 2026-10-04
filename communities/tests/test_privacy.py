"""Released person-counts: keyed, day-stable discrete Laplace noise from a daily snapshot."""
from datetime import timedelta

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from freezegun import freeze_time

from billing.models import Plan, Subscription
from communities import privacy, services
from communities.tests.test_api import CommunityFixture

DAY = '2026-10-04'


@override_settings(COMMUNITIES_NOISE_EPSILON=1.0)
class NoiseTests(SimpleTestCase):
    def test_noise_is_stable_for_the_same_statistic_subject_and_day(self):
        self.assertEqual(privacy.noise('members', (7,), DAY), privacy.noise('members', (7,), DAY))
        draws = {privacy.noise('members', (7,), f'2026-10-{d:02d}') for d in range(1, 29)}
        self.assertGreater(len(draws), 2)  # a new day is a new draw

    def test_noise_is_keyed_by_statistic_subject_and_secret(self):
        base = [privacy.noise('members', (c,), DAY) for c in range(200)]
        self.assertNotEqual(base, [privacy.noise('engaged', (c,), DAY) for c in range(200)])
        self.assertNotEqual(base, [privacy.noise('members', (c + 1,), DAY) for c in range(200)])
        with self.settings(SECRET_KEY='another-secret-key-for-tests'):
            self.assertNotEqual(base, [privacy.noise('members', (c,), DAY) for c in range(200)])

    def test_noise_follows_the_discrete_laplace_distribution(self):
        draws = [privacy.noise('members', (c,), DAY) for c in range(6000)]
        alpha = 2.718281828 ** -1.0
        self.assertAlmostEqual(sum(draws) / len(draws), 0, delta=0.08)
        self.assertAlmostEqual(draws.count(0) / len(draws), (1 - alpha) / (1 + alpha), delta=0.03)
        self.assertAlmostEqual(sum(d > 0 for d in draws) / len(draws), sum(d < 0 for d in draws) / len(draws),
                               delta=0.03)
        self.assertLess(sum(abs(d) >= 5 for d in draws) / len(draws), 0.02)

    def test_release_rounds_to_five_and_suppresses_on_the_noisy_value(self):
        for count in range(0, 60):
            shown = privacy.release(count, 'members', count, day=DAY)
            if shown is not None:
                self.assertEqual(shown % 5, 0)
                self.assertGreaterEqual(shown, 5)
                self.assertEqual(shown, max(5, int((count + privacy.noise('members', (count,), DAY)) / 5 + 0.5) * 5))
            else:
                self.assertLess(count + privacy.noise('members', (count,), DAY), 5)

    @override_settings(COMMUNITIES_NOISE_EPSILON=0)
    def test_zero_epsilon_disables_noise(self):
        self.assertEqual([privacy.release(n, 'members', 1, day=DAY) for n in (0, 4, 5, 7, 8, 12)],
                         [None, None, 5, 5, 10, 10])
        self.assertEqual(privacy.release_delta(-3, 'growth', 1, day=DAY), -5)


@override_settings(COMMUNITIES_NOISE_EPSILON=1.0)
class ReleasedCountsTests(CommunityFixture):
    def test_public_counts_carry_the_days_noise_and_repeat_exactly(self):
        for i in range(12):
            self.enjoy(self.person(f'fan{i}'), self.space_jokes[:2])
        rows, data = self.directory()
        day = timezone.now().date().isoformat()
        cid = self.space.community.pk
        self.assertEqual(data['counts_date'], day)
        self.assertEqual(rows['space']['members'], privacy.release(12, 'members', cid, day=day))
        expected_engaged = privacy.release(12, 'engaged', cid, day=day)
        if rows['space']['members'] is not None and expected_engaged is not None:
            self.assertEqual(rows['space']['engaged_members'], min(expected_engaged, rows['space']['members']))
        # Asking again — even after every cache is gone — returns the same draw.
        self.assertEqual(self.directory()[1]['communities'], data['communities'])
        cache.clear()
        again = self.directory()[1]
        self.assertEqual(again['communities'], data['communities'])
        self.assertEqual(again['stats'], data['stats'])

    def test_counts_hold_within_the_day_while_status_stays_live(self):
        fans = [self.person(f'fan{i}') for i in range(9)]
        for fan in fans[:4]:
            self.enjoy(fan, self.space_jokes[:2])
        before, data = self.directory()
        self.assertEqual(before['space']['status'], 'forming')
        for fan in fans[4:]:
            self.enjoy(fan, self.space_jokes[:2])  # five more members the same day
        after, later = self.directory()
        self.assertEqual(after['space']['status'], 'active')  # live: the fifth laugh activates it
        for field in ('members', 'engaged_members'):
            self.assertEqual(after['space'][field], before['space'][field])
        self.assertEqual(later['stats']['members'], data['stats']['members'])
        with freeze_time(timezone.now() + timedelta(days=1)):
            tomorrow = {r['slug']: r for r in self.directory()[1]['communities']}
            day = timezone.now().date().isoformat()
            self.assertEqual(tomorrow['space']['members'],
                             privacy.release(9, 'members', self.space.community.pk, day=day))

    def test_consent_withdrawal_still_lowers_todays_counts(self):
        fans = [self.person(f'fan{i}') for i in range(5)]
        for fan in fans:
            self.enjoy(fan, self.space_jokes[:2])
        self.directory()
        with self.captureOnCommitCallbacks(execute=True):
            for fan in fans:
                fan.profile.share_analytics = False
                fan.profile.save()
        rows, data = self.directory()
        self.assertIsNone(rows['space']['members'])
        self.assertIsNone(data['stats']['members'])

    def test_bridges_are_released_for_every_pair_including_empty_ones(self):
        snapshot = {'rows': {1: {'members': [], 'engaged_ids': [], 'previous_ids': []},
                             2: {'members': [], 'engaged_ids': [], 'previous_ids': []}}}
        released = services.release_public(snapshot, DAY, population=set())
        expected = privacy.release(0, 'bridge', 1, 2, day=DAY)
        self.assertEqual(released['bridges'], [[1, 2, expected]] if expected is not None else [])

    def test_creator_reach_is_noised_stable_and_shares_the_public_size_draw(self):
        creator = self.person('creator')
        mine = [self.joke(f'mine {i}', self.space, creator=creator) for i in range(2)]
        Subscription.objects.create(user=creator, plan=Plan.objects.get(slug='creator_pro'), status='active')
        for i in range(11):
            self.enjoy(self.person(f'fan{i}'), mine)
        self.client.force_authenticate(creator)
        first = self.client.get('/api/v1/creators/me/communities/').data
        second = self.client.get('/api/v1/creators/me/communities/').data
        self.assertEqual(first, second)
        day = timezone.now().date().isoformat()
        space = next(r for r in first['communities'] if r['slug'] == 'space')
        self.assertEqual(space['members'], privacy.release(11, 'members', self.space.community.pk, day=day))
        self.assertEqual(first['audience']['size'], privacy.release(11, 'creator-audience', creator.pk, day=day))
        for value in (space['members'], space['reached_members'], first['audience']['size']):
            self.assertTrue(value is None or (value >= 5 and value % 5 == 0))
