"""The materialized read path must return exactly what the ledger scan returned.

``legacy.compute_aggregate`` is the frozen pre-materialization implementation.
Randomized scenarios drive the real write paths (model saves/deletes under
frozen clocks, so ``auto_now`` stamps and share pruning see realistic times)
and compare both implementations field by field.
"""
import importlib
import random
from datetime import date, timedelta
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from freezegun import freeze_time

from communities import engine, materialize, services
from communities.models import CommunityMembership, CommunitySignal
from communities.tests import legacy
from jokes.models import (
    AgeRating,
    AnalyticsConsentRecord,
    Collection,
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
ROW_FIELDS = ('members', 'engaged', 'previous', 'contributors', 'activity', 'joke_count')


class Catalog:
    def build_catalog(self, themes=('space', 'office', 'puns', 'food')):
        self.fmt = Format.objects.get_or_create(slug='oneliner', defaults={'name': 'One-liner'})[0]
        self.age = AgeRating.objects.order_by('min_age').first() or AgeRating.objects.create(
            code='all', name='All', min_age=0)
        self.lang = Language.objects.get_or_create(code='en', defaults={'name': 'English'})[0]
        self.tags = [ContextTag.objects.create(name=f'{t.title()} M', slug=f'{t}-m') for t in themes]

    def joke(self, text, tags, tier='tier_1'):
        joke = Joke.objects.create(text=text, format=self.fmt, age_rating=self.age, language=self.lang,
                                   content_tier=tier)
        joke.context_tags.set(tags)
        return joke

    def person(self, name, adult=True, share=True, opt_ins=((-400, True),), active=True):
        user = User.objects.create_user(username=name, email=f'{name}@example.test', password='pw-12345678',
                                        is_active=active)
        user.profile.date_of_birth = date(1990, 1, 1) if adult else date.today() - timedelta(days=365 * 15)
        user.profile.share_analytics = share
        user.profile.save()
        for days, enabled in opt_ins:
            AnalyticsConsentRecord.objects.create(user=user, enabled=enabled, policy_version='test',
                                                  provenance='preference',
                                                  recorded_at=timezone.now() + timedelta(days=days))
        return user


@override_settings(COMMUNITIES_MIN_REFRESH_SECONDS=0)
class EquivalenceTests(Catalog, TestCase):
    """Randomized scenarios: every derived number must match the ledger scan."""

    def setUp(self):
        cache.clear()
        self.build_catalog()

    # ------------------------------------------------------------------ scenario
    def scenario(self, seed):
        rng = random.Random(seed)
        self.start = timezone.now()
        jokes = [
            self.joke(f'j{seed}-{i}', rng.sample(self.tags, rng.choice([0, 1, 1, 2, 2, 3])),
                      tier='tier_1' if rng.random() < 0.85 else 'tier_2')
            for i in range(24)
        ]
        profiles = {
            'eligible': {}, 'no_consent': {'share': False, 'opt_ins': ()},
            'minor': {'adult': False}, 'inactive': {'active': False},
            'late_opt_in': {'opt_ins': ((-400, False), (-rng.uniform(0, 60), True))},
            'withdrawn': {'share': False, 'opt_ins': ((-400, True), (-10, False))},
            'reopted': {'opt_ins': ((-400, True), (-50, False), (-20, True))},
            'never_recorded': {'opt_ins': ()},
        }
        kinds = rng.choices(list(profiles), weights=[55, 8, 7, 4, 10, 5, 7, 4], k=36)
        users = [self.person(f'u{seed}-{i}', **profiles[kind]) for i, kind in enumerate(kinds)]
        collections = {u.pk: [Collection.objects.create(user=u, name=f'c{n}') for n in range(rng.randint(0, 2))]
                       for u in users}

        def when(low=0.0, high=None):
            high = high if high is not None else (20 if rng.random() < 0.6 else 100)
            return self.start - timedelta(days=rng.uniform(low, high), minutes=1)

        actions = []
        for user in users:
            for joke in rng.sample(jokes, rng.randint(3, 12)):
                if rng.random() < 0.75:
                    at = when()
                    actions.append((at, 'react', user, joke, rng.choices(
                        ['lol', 'crying', 'hmm', 'eyeroll'], weights=[50, 25, 15, 10])[0]))
                    if rng.random() < 0.25:
                        actions.append((at + (self.start - at) * rng.random(), 'react', user, joke,
                                        rng.choice(['lol', 'crying', 'hmm', 'eyeroll'])))
                if rng.random() < 0.35:
                    at = when()
                    actions.append((at, 'favorite', user, joke, None))
                    if rng.random() < 0.15:
                        actions.append((at + (self.start - at) * rng.random(), 'unfavorite', user, joke, None))
                if rng.random() < 0.3:
                    for collection in [None, *collections[user.pk]][:rng.randint(1, 3)]:
                        at = when()
                        actions.append((at, 'save', user, joke, collection))
                        if rng.random() < 0.15:
                            actions.append((at + (self.start - at) * rng.random(), 'unsave', user, joke, collection))
                if rng.random() < 0.3:
                    for _ in range(rng.randint(1, 5)):
                        actions.append((when(high=45), 'share', user, joke, None))
            if rng.random() < 0.08:
                actions.append((when(high=40), 'anonymous_share', None, rng.choice(jokes), None))
        actions.sort(key=lambda action: action[0])
        for at, verb, user, joke, extra in actions:
            with freeze_time(at):
                self.apply(verb, user, joke, extra)

        communities = services.listed_communities()
        for user in rng.sample(users, 6):
            membership = CommunityMembership.objects.create(
                user=user, community=rng.choice(communities), state=rng.choice(['joined', 'left']))
            CommunityMembership.objects.filter(pk=membership.pk).update(updated_at=when(high=20))

        # After-the-fact changes that never touch the mirror: they must apply at read time.
        Joke.objects.filter(pk__in=[j.pk for j in jokes[:2]]).update(is_removed=True, removed_at=timezone.now())
        Joke.objects.filter(pk=jokes[2].pk).update(content_tier='tier_2')
        Joke.objects.filter(pk=jokes[3].pk).update(content_tier='tier_1')
        jokes[4].context_tags.set([self.tags[0]])
        jokes[5].context_tags.clear()
        withdrawn = next(u for u, k in zip(users, kinds, strict=True) if k == 'eligible')
        withdrawn.profile.share_analytics = False
        withdrawn.profile.save()
        deleted = next(u for u, k in zip(users, kinds, strict=True) if k == 'eligible' and u != withdrawn)
        deleted.delete()
        jokes[6].delete()
        self.users = [u for u in users if u != deleted]
        self.jokes = [j for j in jokes if j.pk != jokes[6].pk]
        return actions

    def apply(self, verb, user, joke, extra):
        if verb == 'react':
            existing = JokeReaction.objects.filter(user=user, joke=joke).first()
            if existing and existing.reaction == extra:
                existing.delete()  # toggle off, exactly like the react endpoint
            elif existing:
                existing.reaction = extra
                existing.save(update_fields=['reaction', 'updated_at'])
            else:
                JokeReaction.objects.create(user=user, joke=joke, reaction=extra)
        elif verb == 'favorite':
            Favorite.objects.get_or_create(user=user, joke=joke)
        elif verb == 'unfavorite':
            Favorite.objects.filter(user=user, joke=joke).delete()
        elif verb == 'save':
            SavedJoke.objects.get_or_create(user=user, joke=joke, collection=extra)
        elif verb == 'unsave':
            SavedJoke.objects.filter(user=user, joke=joke, collection=extra).delete()
        elif verb == 'share':
            ShareEvent.objects.create(user=user, joke=joke, platform='copy')
        elif verb == 'anonymous_share':
            ShareEvent.objects.create(user=None, joke=joke, platform='copy')

    # ------------------------------------------------------------------ checks
    def assertSameAggregate(self, now):
        with freeze_time(now):
            old, new = legacy.compute_aggregate(now), services.compute_aggregate(now)
        self.assertEqual(old['generated_at'], new['generated_at'])
        self.assertEqual(old['member_total'], new['member_total'])
        self.assertEqual(old['multi_community'], new['multi_community'])
        self.assertEqual(old['bridges'], new['bridges'])
        self.assertEqual(set(old['rows']), set(new['rows']))
        for cid, row in old['rows'].items():
            for field in ROW_FIELDS:
                self.assertEqual(row[field], new['rows'][cid][field], f'{field} of community {cid} at {now}')
            # Same terms, possibly summed in another order: only the last float bit may differ.
            self.assertAlmostEqual(row['score'], new['rows'][cid]['score'], delta=0.0100001)
        return old

    def assertSameAffinities(self, now):
        """Per-person, per-community engine output — now and a week ago — not just the counts."""
        tag_to_community = {c.tag_id: c.pk for c in services.listed_communities()}
        since = now - timedelta(days=services.WINDOW_DAYS)
        with freeze_time(now):
            raw = legacy.to_engine_events(legacy.eligible_signals(since), tag_to_community)
            rows = services.signal_rows(since, eligible=True)
            for moment in (now, now - timedelta(days=materialize.TREND_DAYS)):
                old = engine.affinities(raw, moment)
                new = services.affinities_at(rows, moment, tag_to_community)
                self.assertEqual(set(old), set(new))
                for key, result in old.items():
                    self.assertAlmostEqual(result.pop('score'), new[key].pop('score'), places=9)
                    self.assertEqual(result, new[key])

    def assertSameViewerStates(self, now):
        communities = services.listed_communities()
        tag_to_community = {c.tag_id: c.pk for c in communities}
        for user in self.users[:12]:
            with freeze_time(now):
                new = services.viewer_states(user, communities)
                events = legacy.to_engine_events(
                    legacy.collect_signals(now - timedelta(days=legacy.WINDOW_DAYS), users=[user.pk]),
                    tag_to_community,
                )
                overrides = [{'actor_id': user.pk, 'subject_id': cid, 'state': state} for cid, state in
                             CommunityMembership.objects.filter(user=user).values_list('community_id', 'state')]
                results = engine.affinities(events, now, overrides)
            for cid in tag_to_community.values():
                old_state, new_state = results.get((user.pk, cid)), new.get(cid)
                self.assertEqual(old_state is None, new_state is None)
                if old_state:
                    self.assertAlmostEqual(old_state.pop('score'), new_state.pop('score'), places=9)
                    self.assertEqual(old_state, new_state)

    def assertSameCreatorAudience(self, now):
        since = now - timedelta(days=services.WINDOW_DAYS)
        for creator in self.users[:4]:
            jokes = Joke.objects.filter(pk__in=[j.pk for j in self.jokes[::3]], content_tier='tier_1')
            with freeze_time(now):
                old = {p for p, _, _, _ in legacy.eligible_signals(since, jokes=jokes.values('pk'),
                                                                   exclude_user=creator)}
                new = set(services.signal_rows(since, jokes=jokes.values('pk'), eligible=True, exclude_user=creator)
                          .values_list('user_id', flat=True))
            self.assertEqual(old, new)

    def check_scenario(self, seed):
        self.scenario(seed)
        moments = [timezone.now(), timezone.now() + timedelta(days=2, hours=5), timezone.now() + timedelta(days=9)]
        first = None
        for moment in moments:
            data = self.assertSameAggregate(moment)
            first = first or data
            self.assertSameAffinities(moment)
            self.assertSameViewerStates(moment)
            self.assertSameCreatorAudience(moment)
        # The scenario must actually exercise formation, history and activity.
        self.assertTrue(any(r['members'] for r in first['rows'].values()))
        self.assertTrue(any(r['previous'] for r in first['rows'].values()))
        self.assertTrue(any(sum(r['activity']) for r in first['rows'].values()))
        # A full rebuild from the ledgers serves the same numbers as incremental upkeep.
        materialize.rebuild()
        for moment in moments:
            self.assertSameAggregate(moment)

    def test_randomized_scenario_seed_1(self):
        self.check_scenario(1)

    def test_randomized_scenario_seed_2(self):
        self.check_scenario(2)

    def test_randomized_scenario_seed_3(self):
        self.check_scenario(3)

    def test_randomized_scenario_seed_4(self):
        self.check_scenario(4)


@override_settings(COMMUNITIES_MIN_REFRESH_SECONDS=0)
class MaintenanceTests(Catalog, TestCase):
    """Each write path keeps the mirror (and therefore the numbers) right."""

    def setUp(self):
        cache.clear()
        self.build_catalog(themes=('space', 'office'))
        self.space, self.office = self.tags
        self.space_jokes = [self.joke(f'space {i}', [self.space]) for i in range(3)]
        self.office_jokes = [self.joke(f'office {i}', [self.office]) for i in range(2)]

    def mirror(self, **filters):
        return set(CommunitySignal.objects.filter(**filters).values_list('kind', 'source_id'))

    def enjoy(self, user, jokes):
        with self.captureOnCommitCallbacks(execute=True):
            for joke in jokes:
                JokeReaction.objects.create(user=user, joke=joke, reaction='lol')
                Favorite.objects.create(user=user, joke=joke)

    def five_fans(self, jokes=None):
        fans = [self.person(f'fan{i}') for i in range(5)]
        for fan in fans:
            self.enjoy(fan, jokes or self.space_jokes[:2])
        return fans

    def status(self, slug='space-m'):
        community = next(c for c in services.listed_communities() if c.tag.slug == slug)
        return services.community_row(community, services.aggregate())['status']

    def test_only_positive_signals_are_mirrored(self):
        fan = self.person('fan')
        laugh = JokeReaction.objects.create(user=fan, joke=self.space_jokes[0], reaction='lol')
        JokeReaction.objects.create(user=fan, joke=self.space_jokes[1], reaction='eyeroll')
        ShareEvent.objects.create(user=None, joke=self.space_jokes[0], platform='copy')
        self.assertEqual(self.mirror(), {('like', laugh.pk)})

    def test_unreact_and_switching_reactions(self):
        fans = self.five_fans()
        self.assertEqual(self.status(), 'active')
        reaction = JokeReaction.objects.get(user=fans[0], joke=self.space_jokes[0])
        with self.captureOnCommitCallbacks(execute=True):
            reaction.reaction = 'hmm'
            reaction.save(update_fields=['reaction', 'updated_at'])
        self.assertNotIn(('like', reaction.pk), self.mirror())
        with freeze_time(timezone.now() + timedelta(hours=1)), self.captureOnCommitCallbacks(execute=True):
            reaction.reaction = 'crying'
            reaction.save(update_fields=['reaction', 'updated_at'])
        self.assertEqual(CommunitySignal.objects.get(kind='like', source_id=reaction.pk).occurred_at,
                         reaction.updated_at)
        with self.captureOnCommitCallbacks(execute=True):
            reaction.delete()
            Favorite.objects.filter(user=fans[0], joke=self.space_jokes[0]).delete()
        self.assertFalse(CommunitySignal.objects.filter(user=fans[0], joke=self.space_jokes[0]).exists())
        self.assertEqual(self.status(), 'forming')

    def test_unsave_keeps_saves_in_other_collections(self):
        fan = self.person('fan')
        shelf = Collection.objects.create(user=fan, name='shelf')
        loose = SavedJoke.objects.create(user=fan, joke=self.space_jokes[0])
        shelved = SavedJoke.objects.create(user=fan, joke=self.space_jokes[0], collection=shelf)
        loose.delete()
        self.assertEqual(self.mirror(kind='save'), {('save', shelved.pk)})
        shelf.delete()  # cascades to its saves
        self.assertEqual(self.mirror(kind='save'), set())

    def test_removed_retiered_and_retagged_jokes_leave_immediately(self):
        self.five_fans()
        self.assertEqual(self.status(), 'active')
        Joke.objects.filter(pk=self.space_jokes[0].pk).update(is_removed=True, removed_at=timezone.now())
        services.invalidate()
        self.assertEqual(self.status(), 'forming')
        Joke.all_objects.filter(pk=self.space_jokes[0].pk).update(is_removed=False, removed_at=None)
        services.invalidate()
        self.assertEqual(self.status(), 'active')
        Joke.objects.filter(pk=self.space_jokes[1].pk).update(content_tier='tier_2')
        services.invalidate()
        self.assertEqual(self.status(), 'forming')
        Joke.objects.filter(pk=self.space_jokes[1].pk).update(content_tier='tier_1')
        services.invalidate()
        self.assertEqual(self.status(), 'active')
        with self.captureOnCommitCallbacks(execute=True):  # a re-tag invalidates on its own
            self.space_jokes[1].context_tags.set([self.office])
        self.assertEqual(self.status(), 'forming')

    def test_consent_withdrawal_and_late_opt_in(self):
        fans = self.five_fans()
        self.assertEqual(self.status(), 'active')
        with self.captureOnCommitCallbacks(execute=True):
            fans[0].profile.share_analytics = False
            fans[0].profile.save()
        self.assertEqual(self.status(), 'forming')
        with self.captureOnCommitCallbacks(execute=True):
            fans[0].profile.share_analytics = True
            fans[0].profile.save()
            # Re-opting in now does not resurrect signals from before the opt-in.
            AnalyticsConsentRecord.objects.create(user=fans[0], enabled=True, policy_version='test',
                                                  provenance='preference',
                                                  recorded_at=timezone.now() + timedelta(seconds=1))
        self.assertEqual(self.status(), 'forming')

    def test_account_deletion_drops_the_person_and_their_rows(self):
        fans = self.five_fans()
        ShareEvent.objects.create(user=fans[0], joke=self.space_jokes[2], platform='copy')
        self.assertEqual(self.status(), 'active')
        with self.captureOnCommitCallbacks(execute=True):
            fans[0].delete()
        self.assertFalse(CommunitySignal.objects.filter(user_id=fans[0].pk).exists())
        self.assertEqual(ShareEvent.objects.filter(user__isnull=True).count(), 1)  # kept, now anonymous
        self.assertEqual(self.status(), 'forming')

    def test_joke_deletion_cascades_cleanly(self):
        fans = self.five_fans()
        for fan in fans:
            ShareEvent.objects.create(user=fan, joke=self.space_jokes[0], platform='copy')
            SavedJoke.objects.create(user=fan, joke=self.space_jokes[0])
        self.space_jokes[0].delete()
        self.assertFalse(CommunitySignal.objects.filter(joke_id=self.space_jokes[0].pk).exists())

    def test_repeated_shares_are_pruned_without_changing_numbers(self):
        fan = self.person('fan')
        now = timezone.now()
        shares = {}
        for days in (30, 20, 10, 1):
            with freeze_time(now - timedelta(days=days)):
                shares[days] = ShareEvent.objects.create(user=fan, joke=self.space_jokes[0], platform='copy')
        # 30 and 20 can never matter again: 10 is the newest share before the week-ago cutoff.
        self.assertEqual(self.mirror(kind='share'), {('share', shares[10].pk), ('share', shares[1].pk)})
        shares[10].delete()  # e.g. removed in the admin: the newest older share counts again
        self.assertEqual(self.mirror(kind='share'), {('share', shares[20].pk), ('share', shares[1].pk)})

    def test_rebuild_is_idempotent_and_matches_incremental_upkeep(self):
        fans = self.five_fans()
        SavedJoke.objects.create(user=fans[1], joke=self.office_jokes[0])
        ShareEvent.objects.create(user=fans[2], joke=self.office_jokes[1], platform='copy')
        incremental = self.mirror()
        call_command('rebuild_community_signals', stdout=SimpleNamespace(write=lambda *a, **k: None))
        self.assertEqual(self.mirror(), incremental)
        materialize.rebuild()
        self.assertEqual(self.mirror(), incremental)
        self.assertEqual(CommunitySignal.objects.count(), len(incremental))

    def test_backfill_migration_materializes_existing_ledgers_idempotently(self):
        fans = self.five_fans()
        ShareEvent.objects.create(user=fans[0], joke=self.space_jokes[0], platform='copy')
        expected = self.mirror()
        CommunitySignal.objects.all().delete()
        migration = importlib.import_module('communities.migrations.0004_backfill_community_signals')
        editor = SimpleNamespace(connection=connection)
        migration.backfill(django_apps, editor)
        migration.backfill(django_apps, editor)
        self.assertEqual(self.mirror(), expected)
        self.assertEqual(CommunitySignal.objects.count(), len(expected))
        self.assertEqual(self.status(), 'active')

    def test_aggregate_query_count_does_not_grow_with_engagement(self):
        self.five_fans()
        with CaptureQueriesContext(connection) as small:
            services.compute_aggregate()
        for i in range(5, 15):
            fan = self.person(f'fan{i}')
            self.enjoy(fan, self.space_jokes + self.office_jokes)
            for joke in self.office_jokes:
                ShareEvent.objects.create(user=fan, joke=joke, platform='copy')
        with CaptureQueriesContext(connection) as large:
            services.compute_aggregate()
        self.assertEqual(len(small.captured_queries), len(large.captured_queries))
