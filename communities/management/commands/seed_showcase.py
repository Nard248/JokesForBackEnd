"""Seed a LOCAL product showcase: Creator Studio + self-forming communities.

What it builds (all identities use the reserved ``@showcase.invalid`` domain):

* ``maya@showcase.invalid`` — Maya Okafor, a Creator Pro comedian with jokes
  across themes, followers, 28 days of consenting-audience telemetry, private
  notes, a set list, a series and a pending metadata request.
* ``theo@showcase.invalid`` — Theo Lindqvist, a creator on the free plan, to
  show which Studio tools are included and which are Creator Pro.
* ``sam@showcase.invalid`` — Sam Rivera, a reader one laugh away from becoming
  the fifth member who activates the forming *Space* community.
* ~260 synthetic audience members whose engagement forms overlapping active
  communities, one cooling community (Weather) and one forming one (Space).
  About 15% do not share analytics: their activity exists but is never counted.

Every run rebuilds the showcase rows from scratch with a fixed random seed.
Local-only by construction: the same guard as ``seed_e2e`` refuses anything
but DEBUG + loopback PostgreSQL + filesystem storage.

    DATABASE_URL= DEBUG=True DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=... \\
    DB_HOST=localhost .venv/bin/python manage.py seed_showcase
"""
import os
import random
from datetime import date, timedelta
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, connections, transaction
from django.utils import timezone

from billing.models import Plan, Subscription
from communities import services
from communities.models import Community, CommunityMembership
from creator_insights import library
from follows.models import Follow
from jokes.models import (
    AgeRating,
    AnalyticsConsentRecord,
    ContextTag,
    Favorite,
    Format,
    Joke,
    JokeDwell,
    JokeImpression,
    JokeReaction,
    JokeView,
    Language,
    SavedJoke,
    ShareEvent,
    Tone,
    UserProfile,
)
from jokes.telemetry import POLICY_VERSION

User = get_user_model()

DOMAIN = '@showcase.invalid'
PASSWORD = 'Showcase-2026!'
RANDOM_SEED = 20261004
AUDIENCE = 260
NON_CONSENTING_SHARE = 0.15

FIRST = ['Alex', 'Jordan', 'Riley', 'Casey', 'Morgan', 'Taylor', 'Jamie', 'Avery', 'Quinn', 'Rowan',
         'Noor', 'Ines', 'Mateo', 'Hana', 'Kofi', 'Lena', 'Omar', 'Yuki', 'Zara', 'Felix',
         'Ana', 'Ravi', 'Mila', 'Tomas', 'Leah', 'Arjun', 'Sofia', 'Emeka', 'Greta', 'Luca']
LAST = ['Park', 'Silva', 'Nguyen', 'Haddad', 'Moreau', 'Brennan', 'Sato', 'Okoye', 'Larsen', 'Costa',
        'Novak', 'Reyes', 'Fischer', 'Ahmed', 'Kaur', 'Duarte', 'Ivanova', 'Mensah', 'Rossi', 'Berg']

# Interest weights for the synthetic audience (Space and Weather are scripted).
THEME_WEIGHTS = {
    'work': 34, 'tech': 26, 'family': 20, 'food': 18, 'mondays': 16, 'travel': 14, 'animals': 14,
    'puns': 12, 'school': 10, 'science': 9, 'money': 8, 'dating': 8,
}

CREATORS = {
    'maya': {
        'name': 'Maya Okafor', 'handle': 'mayaokafor', 'pro': True,
        'bio': 'Stand-up. Recovering project manager. Tuesday open mics in Brooklyn.',
        'jokes': [
            ('work', 'office-proper', 'oneliner', 'My calendar has so many “quick syncs” it now qualifies as a synchronized swimming team.'),
            ('work', 'office-proper', 'setup', ('Why did the meeting go on forever?', 'Someone said “one last thing” and meant it as a lifestyle.')),
            ('work', 'office-proper', 'oneliner', 'I don’t have imposter syndrome. I have an imposter who keeps getting invited to meetings.'),
            ('work', 'office-proper', 'observ', 'Every office has one printer that only works when IT is standing next to it. It is not a printer. It is a hostage.'),
            ('work', 'dad', 'setup', ('What do you call a performance review with no surprises?', 'A rumor.')),
            ('tech', 'nerd', 'oneliner', 'I told my laptop I needed a break. It installed 47 updates out of solidarity.'),
            ('tech', 'nerd', 'setup', ('Why did the password break up with me?', 'It needed at least one special character in my life.')),
            ('tech', 'nerd', 'observ', 'Smart homes are great until your fridge has opinions about your midnight snacks and posts them to the family group chat.'),
            ('tech', 'nerd', 'oneliner', 'My code works and I have no idea why. My code breaks and I have no idea why. I call it consistency.'),
            ('mondays', 'office-proper', 'oneliner', 'Monday is the only day that shows up uninvited and still asks if you had a good weekend.'),
            ('mondays', 'wholesome', 'setup', ('Why is Monday coffee so strong?', 'It’s been through things.')),
            ('mondays', 'office-proper', 'oneliner', 'I’m not saying Mondays are hard, but my alarm clock filed for hazard pay.'),
            ('travel', 'wholesome', 'oneliner', 'Airports are the only place where eating a croissant at 6 a.m. next to a stranger in socks is “normal.”'),
            ('travel', 'office-proper', 'setup', ('Why did my suitcase fail the vibe check?', 'It came back from the carousel with emotional baggage.')),
            ('money', 'dad', 'oneliner', 'My budget and I are in a long-distance relationship. It’s in a spreadsheet and I’m at brunch.'),
            ('space', 'nerd', 'oneliner', 'I tried to plan a party in space, but there was no atmosphere.'),
        ],
    },
    'priya': {
        'name': 'Priya Ramos', 'handle': 'priyaramos', 'pro': False,
        'bio': 'Writes jokes between school runs.',
        'jokes': [
            ('family', 'wholesome', 'oneliner', 'My kids think I’m a superhero. Mostly because I disappear whenever it’s time to clean up.'),
            ('family', 'wholesome', 'setup', ('Why did the toddler bring a ladder to dinner?', 'Someone said dessert was on the house.')),
            ('family', 'dad', 'oneliner', 'Family group chat: 300 messages, 2 decisions, 0 dinner plans.'),
            ('food', 'wholesome', 'oneliner', 'I’m on a seafood diet. I see food, I pause, I reconsider, I eat it anyway.'),
            ('food', 'dad', 'setup', ('Why did the avocado go to therapy?', 'It had too many pits of despair.')),
            ('space', 'nerd', 'setup', ('How do astronauts organize a party?', 'They planet.')),
            ('space', 'wholesome', 'oneliner', 'The moon broke up with the sun. It needed its own space, but it still reflects on it every night.'),
            ('space', 'nerd', 'setup', ('Why did the star get detention?', 'It wouldn’t stop twinkling during the test.')),
        ],
    },
    'dev': {
        'name': 'Dev Kowalski', 'handle': 'devkowalski', 'pro': False,
        'bio': 'Science teacher by day, pun enthusiast by night.',
        'jokes': [
            ('science', 'nerd', 'setup', ('Why can’t you trust atoms?', 'They make up everything, including their alibis.')),
            ('science', 'nerd', 'oneliner', 'I’d tell a chemistry joke, but all the good ones argon.'),
            ('animals', 'wholesome', 'oneliner', 'My cat has two moods: “feed me” and “I have never seen you before in my life.”'),
            ('animals', 'dad', 'setup', ('What do you call a sleeping dinosaur?', 'A dino-snore, obviously.')),
            ('puns', 'puns', 'oneliner', 'I used to hate facial hair, but then it grew on me.'),
            ('weather', 'dad', 'oneliner', 'The weather forecast said 0% chance of rain, so naturally I’m now a fountain.'),
            ('weather', 'wholesome', 'setup', ('What does a cloud wear under its raincoat?', 'Thunderwear.')),
            ('weather', 'dad', 'oneliner', 'Fog is just the sky giving up on being seen today. Relatable.'),
        ],
    },
    'theo': {
        'name': 'Theo Lindqvist', 'handle': 'theolindqvist', 'pro': False,
        'bio': 'New to stand-up. Testing material on whoever stands still.',
        'jokes': [
            ('school', 'wholesome', 'oneliner', 'Group projects taught me that “we” is a very flexible word.'),
            ('school', 'dad', 'setup', ('Why did the student eat his homework?', 'The teacher said it was a piece of cake.')),
            ('money', 'office-proper', 'oneliner', 'My savings account and my gym membership have the same relationship with me: hopeful but rarely visited.'),
            ('school', 'nerd', 'oneliner', 'Exams are just a pop quiz that had time to plan its revenge.'),
            ('money', 'dad', 'setup', ('Why did the dollar break up with the coin?', 'It wanted someone with more cents.')),
        ],
    },
}


class Command(BaseCommand):
    help = 'Rebuild the local Creator Studio + communities showcase (local PostgreSQL only).'

    def handle(self, *args, **options):
        config = connections['default'].settings_dict
        routing = config.get('OPTIONS') or {}
        if (
            not settings.DEBUG
            or config.get('ENGINE') != 'django.db.backends.postgresql'
            or str(config.get('HOST', '')).lower() not in {'localhost', '127.0.0.1', '::1'}
            or any(routing.get(key) or os.environ.get('PG' + key.upper()) for key in ('hostaddr', 'service'))
            or settings.STORAGES['default']['BACKEND'] != 'django.core.files.storage.FileSystemStorage'
        ):
            raise CommandError(
                'seed_showcase is local-only: requires DEBUG=True, explicit loopback PostgreSQL, no '
                'hostaddr/service overrides and local filesystem storage. Clear DATABASE_URL first.'
            )
        self.rng = random.Random(RANDOM_SEED)
        self.now = timezone.now()
        self._seed()
        services.invalidate()
        self._report()

    # ------------------------------------------------------------------ helpers
    def _when(self, recent=0.65, max_days=28):
        """A timestamp skewed to the last week and to evening hours."""
        days = self.rng.uniform(0, 7) if self.rng.random() < recent else self.rng.uniform(7, max_days)
        moment = self.now - timedelta(days=days)
        hour = self.rng.choice([8, 9, 12, 13, 18, 19, 20, 20, 21, 21, 22, 23])
        moment = moment.replace(hour=hour, minute=self.rng.randrange(60))
        return min(moment, self.now - timedelta(minutes=5))

    def _backdate(self, model, rows, fields):
        """Set auto_now(_add) timestamps that bulk_create overwrote. rows = [(pk, datetime)]."""
        table = model._meta.db_table
        assignments = ', '.join(f'{field} = v.at' for field in fields)
        date_field = {'jokes_jokeimpression': 'created_date', 'jokes_jokedwell': 'created_date',
                      'jokes_jokeview': 'viewed_date'}.get(table)
        if date_field:
            assignments += f', {date_field} = (v.at AT TIME ZONE \'UTC\')::date'
        with connection.cursor() as cursor:
            for start in range(0, len(rows), 1000):
                chunk = rows[start:start + 1000]
                values = ', '.join(['(%s, %s::timestamptz)'] * len(chunk))
                params = [item for row in chunk for item in row]
                cursor.execute(
                    f'UPDATE {table} AS t SET {assignments} FROM (VALUES {values}) AS v(id, at) WHERE t.id = v.id',
                    params,
                )

    def _account(self, key, name, handle, bio='', dob=date(1990, 5, 17), consent=True):
        email = f'{key}{DOMAIN}'
        user = User.objects.create_user(username=email, email=email, password=PASSWORD)
        profile = user.profile
        profile.display_name, profile.handle, profile.bio = name, handle, bio
        profile.date_of_birth, profile.share_analytics = dob, consent
        profile.email_digest_opt_in = False
        profile.save()
        user.preference.onboarding_completed = True
        user.preference.notification_enabled = False
        user.preference.save(update_fields=['onboarding_completed', 'notification_enabled'])
        AnalyticsConsentRecord.objects.create(user=user, enabled=consent, policy_version=POLICY_VERSION,
                                              provenance='preference')
        return user

    # --------------------------------------------------------------------- seed
    @transaction.atomic
    def _seed(self):
        Joke.all_objects.filter(creator__email__endswith=DOMAIN).delete()
        removed, _ = User.objects.filter(email__endswith=DOMAIN).delete()
        if removed:
            self.stdout.write(f'Removed previous showcase rows ({removed} objects).')

        space, _ = ContextTag.objects.get_or_create(
            slug='space', defaults={'name': 'Space', 'description': 'Astronomy, astronauts and cosmic puns.'})
        Community.objects.filter(tag=space).update(tagline='Astronomy, astronauts and cosmic puns.')

        self.fmt = {f.slug: f for f in Format.objects.filter(slug__in=['oneliner', 'setup', 'observ'])}
        self.age = AgeRating.objects.order_by('min_age').first()
        self.lang = Language.objects.get(code='en')
        self.tones = {t.slug: t for t in Tone.objects.all()}
        self.tags = {t.slug: t for t in ContextTag.objects.all()}

        self.creators = {}
        self.creator_jokes = {}
        for key, spec in CREATORS.items():
            user = self._account(key, spec['name'], spec['handle'], spec['bio'], dob=date(1988, 3, 9))
            self.creators[key] = user
            self.creator_jokes[key] = [self._joke(user, *row) for row in spec['jokes']]
        Subscription.objects.update_or_create(user=self.creators['maya'], defaults={
            'plan': Plan.objects.get(slug='creator_pro'), 'status': 'active',
            'stripe_customer_id': '', 'stripe_subscription_id': '', 'stripe_price_id': '',
            'current_period_start': self.now - timedelta(days=12),
            'current_period_end': self.now + timedelta(days=18), 'cancel_at_period_end': False,
        })
        self.reader = self._account('sam', 'Sam Rivera', 'samrivera', 'Here for the puns.', dob=date(1996, 8, 2))

        self.pool = {
            slug: list(Joke.objects.filter(content_tier='tier_1', context_tags=tag).values_list('pk', flat=True))
            for slug, tag in self.tags.items()
        }
        self.maya_ids = {j.pk for j in self.creator_jokes['maya']}
        self.fans = self._audience()
        self.signals = {'reaction': [], 'favorite': [], 'save': [], 'share': [],
                        'impression': [], 'view': [], 'dwell': []}
        self.seen = set()
        self._organic_engagement()
        self._scripted_space()
        self._scripted_weather()
        self._passive_exposure()
        self._write_signals()
        self._follows()
        self._studio_library()
        CommunityMembership.objects.create(user=self.reader, community=self.tags['puns'].community,
                                           state='joined')

    def _joke(self, creator, theme, tone, fmt, body):
        setup, punchline, text = ('', '', body) if isinstance(body, str) else (body[0], body[1], f'{body[0]} {body[1]}')
        joke = Joke.objects.create(
            text=text, setup=setup, punchline=punchline, format=self.fmt.get(fmt, self.fmt['oneliner']),
            age_rating=self.age, language=self.lang, content_tier='tier_1', creator=creator,
        )
        joke.context_tags.add(self.tags[theme])
        if tone in self.tones:
            joke.tones.add(self.tones[tone])
        Joke.all_objects.filter(pk=joke.pk).update(created_at=self.now - timedelta(days=self.rng.uniform(3, 60)))
        return joke

    def _audience(self):
        fans = []
        for index in range(AUDIENCE):
            email = f'fan{index:03d}{DOMAIN}'
            user = User(username=email, email=email, is_active=True)
            user.set_unusable_password()
            user.save()
            fans.append(user)
        profiles = list(UserProfile.objects.filter(user__in=fans).select_related('user'))
        consent_rows = []
        for profile in profiles:
            profile.display_name = f'{self.rng.choice(FIRST)} {self.rng.choice(LAST)}'
            profile.date_of_birth = date(self.rng.randint(1968, 2004), self.rng.randint(1, 12), self.rng.randint(1, 28))
            profile.share_analytics = self.rng.random() >= NON_CONSENTING_SHARE
            profile.email_digest_opt_in = False
            consent_rows.append(AnalyticsConsentRecord(user_id=profile.user_id, enabled=profile.share_analytics,
                                                       policy_version=POLICY_VERSION, provenance='preference'))
        UserProfile.objects.bulk_update(profiles, ['display_name', 'date_of_birth', 'share_analytics',
                                                   'email_digest_opt_in'])
        AnalyticsConsentRecord.objects.bulk_create(consent_rows)
        return fans

    def _enjoy(self, user, joke_id, at, strength=1.0):
        """One reader engaging with one joke: exposure, reading, then responses."""
        if (user.pk, joke_id) in self.seen:
            return
        self.seen.add((user.pk, joke_id))
        rng = self.rng
        self.signals['impression'].append((JokeImpression(user=user, joke_id=joke_id, source='feed',
                                                          created_date=at.date()), at - timedelta(minutes=2)))
        self.signals['view'].append((JokeView(user=user, joke_id=joke_id, source='feed', revealed_punchline=True,
                                                    viewed_date=at.date()), at))
        self.signals['dwell'].append((JokeDwell(user=user, joke_id=joke_id, dwell_ms=rng.randint(3500, 21000),
                                                scroll_pct=rng.randint(60, 100), source='feed',
                                                created_date=at.date()), at + timedelta(seconds=20)))
        roll = rng.random()
        kind = 'lol' if roll < 0.6 else 'crying' if roll < 0.9 else 'hmm'
        self.signals['reaction'].append((JokeReaction(user=user, joke_id=joke_id, reaction=kind), at))
        if rng.random() < 0.38 * strength:
            self.signals['favorite'].append((Favorite(user=user, joke_id=joke_id), at + timedelta(minutes=1)))
        if rng.random() < 0.18 * strength:
            self.signals['save'].append((SavedJoke(user=user, joke_id=joke_id), at + timedelta(minutes=1)))
        if rng.random() < 0.11 * strength:
            platform = rng.choice(['copy', 'whatsapp', 'twitter', 'other'])
            self.signals['share'].append((ShareEvent(user=user, joke_id=joke_id, platform=platform),
                                          at + timedelta(minutes=3)))

    def _organic_engagement(self):
        themes, weights = zip(*THEME_WEIGHTS.items(), strict=True)
        for fan in self.fans:
            interests = set(self.rng.choices(themes, weights=weights, k=self.rng.choice([1, 2, 2, 3])))
            for theme in interests:
                pool = self.pool[theme]
                featured = [pk for pk in pool if pk in self.maya_ids and self.rng.random() < 0.22]
                rest = [pk for pk in pool if pk not in featured]
                picks = featured + self.rng.sample(rest, k=min(len(rest), self.rng.randint(2, 4)))
                for joke_id in picks[:5]:
                    self._enjoy(fan, joke_id, self._when())

    def _scripted_space(self):
        """Four readers are hooked on Space; three more dabble. Sam is one laugh away."""
        space = self.pool['space']
        eligible = list(UserProfile.objects.filter(user__in=self.fans, share_analytics=True)
                        .values_list('user_id', flat=True))
        by_id = {f.pk: f for f in self.fans}
        chosen = self.rng.sample(eligible, 7)
        for user_id in chosen[:4]:
            for joke_id in self.rng.sample(space, 3):
                self._enjoy(by_id[user_id], joke_id, self.now - timedelta(hours=self.rng.uniform(2, 60)), strength=2.5)
        for user_id in chosen[4:]:
            self._enjoy(by_id[user_id], self.rng.choice(space), self._when())
        # Sam: one favourited Space joke today (4 points) — the next laugh makes the community.
        first = self.creator_jokes['maya'][-1].pk
        at = self.now - timedelta(hours=3)
        self.seen.add((self.reader.pk, first))
        self.signals['reaction'].append((JokeReaction(user=self.reader, joke_id=first, reaction='lol'), at))
        self.signals['favorite'].append((Favorite(user=self.reader, joke_id=first), at))
        for joke_id in self.rng.sample(self.pool['puns'], 3):
            self._enjoy(self.reader, joke_id, self._when(recent=0.9))

    def _scripted_weather(self):
        """A community that was active two weeks ago and has since cooled."""
        eligible = list(UserProfile.objects.filter(user__in=self.fans, share_analytics=True)
                        .values_list('user_id', flat=True))
        by_id = {f.pk: f for f in self.fans}
        for user_id in self.rng.sample(eligible, 7):
            for joke_id in self.rng.sample(self.pool['weather'], 3):
                at = self.now - timedelta(days=self.rng.uniform(11.5, 13.5))
                if (user_id, joke_id) not in self.seen:
                    self.seen.add((user_id, joke_id))
                    self.signals['reaction'].append((JokeReaction(user=by_id[user_id], joke_id=joke_id,
                                                                  reaction='lol'), at))
                    self.signals['favorite'].append((Favorite(user=by_id[user_id], joke_id=joke_id), at))

    def _passive_exposure(self):
        """Readers scroll past far more jokes than they respond to."""
        maya = list(self.maya_ids)
        catalog = [pk for ids in self.pool.values() for pk in ids]
        for fan in self.fans:
            for joke_id in self.rng.sample(maya, 6) + self.rng.sample(catalog, 6):
                if (fan.pk, joke_id) in self.seen:
                    continue
                self.seen.add((fan.pk, joke_id))
                at = self._when(recent=0.5)
                self.signals['impression'].append((JokeImpression(user=fan, joke_id=joke_id, source='feed',
                                                                  created_date=at.date()), at))
                if self.rng.random() < 0.45:
                    self.signals['view'].append((JokeView(user=fan, joke_id=joke_id, source='feed', viewed_date=at.date()), at))

    def _write_signals(self):
        stamps = {
            'reaction': (JokeReaction, ['created_at', 'updated_at']),
            'favorite': (Favorite, ['created_at']),
            'save': (SavedJoke, ['created_at']),
            'share': (ShareEvent, ['created_at']),
            'impression': (JokeImpression, ['created_at']),
            'view': (JokeView, ['viewed_at']),
            'dwell': (JokeDwell, ['created_at']),
        }
        for key, (model, fields) in stamps.items():
            pairs = self.signals[key]
            created = model.objects.bulk_create([obj for obj, _ in pairs], batch_size=1000)
            self._backdate(model, [(obj.pk, at) for obj, (_, at) in zip(created, pairs, strict=True)], fields)

    def _follows(self):
        engaged = {}
        for obj, _ in self.signals['reaction']:
            if obj.joke_id in self.maya_ids:
                engaged[obj.user_id] = engaged.get(obj.user_id, 0) + 1
        follows = [Follow(follower_id=uid, creator=self.creators['maya'])
                   for uid, n in engaged.items() if n >= 2 and self.rng.random() < 0.7]
        follows.append(Follow(follower=self.reader, creator=self.creators['maya']))
        created = Follow.objects.bulk_create(follows)
        self._backdate(Follow, [(f.pk, self._when(recent=0.4)) for f in created], ['created_at'])

    def _studio_library(self):
        maya = self.creators['maya']
        request = SimpleNamespace(user=maya)
        jokes = self.creator_jokes['maya']
        notes = {
            0: 'Closer candidate. Pause after “synchronized” — the laugh comes on the second beat.',
            3: 'Printer bit: tag with an IT callback. Works better as the third joke in a set.',
            9: 'Opener for Monday crowds. Try shortening to one breath.',
        }
        for index, note in notes.items():
            library.save_note(request, jokes[index].pk, note)
        library.save_collection(request, {
            'name': 'Thursday open mic · 7 min', 'kind': 'set_list',
            'description': 'Running order for the Pine Box open mic. Strongest office bit closes.',
            'joke_ids': [jokes[i].pk for i in (9, 5, 13, 3, 1, 0)],
        })
        library.save_collection(request, {
            'name': 'Office survival guide', 'kind': 'series',
            'description': 'Weekly series for the work-humor crowd.',
            'joke_ids': [jokes[i].pk for i in (0, 1, 2, 3, 4)],
        })
        library.create_metadata_requests(request, {
            'joke_ids': [jokes[11].pk], 'themes': ['mondays', 'work'],
            'reason': 'This one lands with the work crowd too — adding the Work theme.',
        })

    def _report(self):
        data = services.directory(self.reader)
        self.stdout.write(self.style.SUCCESS('Showcase ready.'))
        for row in data['communities']:
            members = row['members'] if row['members'] is not None else '<5'
            self.stdout.write(f"  {row['emoji']}  {row['name']:<10} {row['status']:<8} members={members}")
        self.stdout.write(f"  stats: {data['stats']}")
        self.stdout.write(f'  Creator Pro: maya{DOMAIN} · Free creator: theo{DOMAIN} · '
                          f'Reader: sam{DOMAIN} · password: {PASSWORD}')
