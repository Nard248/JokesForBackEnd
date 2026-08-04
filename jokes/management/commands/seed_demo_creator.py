"""Seed a rich, believable-but-fake DEMO CREATOR account.

Purpose: let the product owner log in and demo the Creator Insights page
(/create/insights) with fully populated graphs + upward movement, and demo the
subscription flow, without touching real users' data.

Everything the command creates is tagged by the `@jokesfor.dev` email domain so
`--fresh` can clean it up deterministically. It is idempotent: re-running always
tears down the previously-seeded jokes + viewers and rebuilds a fresh dataset.

Run locally against local Postgres:
    DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 \
    DB_HOST=localhost DB_PORT=5432 \
    .venv/bin/python manage.py seed_demo_creator --fresh

NOTE: no Celery / workers / cron — pure request-triggered management command.
"""
import random
import time
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max, Min, Q
from django.utils import timezone

from creator_insights.services import build_creator_insights
from follows.models import Follow
from jokes.models import (
    AgeRating,
    ContextTag,
    CultureTag,
    Favorite,
    Format,
    Joke,
    JokeDwell,
    JokeImpression,
    JokeReaction,
    JokeSubmission,
    JokeView,
    Language,
    SavedJoke,
    ShareEvent,
    Tone,
)

User = get_user_model()

SEED_DOMAIN = '@jokesfor.dev'
DEFAULT_EMAIL = 'demo.creator@jokesfor.dev'
DEFAULT_PASSWORD = 'DemoCreator!2026'
DISPLAY_NAME = 'Dara Punwell'
HANDLE = 'darapun'

# --- Reproducibility ---------------------------------------------------------
RANDOM_SEED = 2026

# --- Hour-of-day weights (0..23): evening-clustered so peak_read_hour lands
#     believably in prime time (~20:00). ---------------------------------------
HOUR_WEIGHTS = [
    1, 1, 1, 1, 1, 1, 2, 3, 3, 3, 3, 4,   # 00..11
    5, 4, 4, 5, 6, 7, 9, 11, 12, 10, 7, 4,  # 12..23
]

# --- Funnel ratios (tuned so the insights summary reads rich + healthy) ------
PAYOFF_PROB = 0.60      # revealed_punchline on a view -> payoff_rate
DWELL_PROB = 0.50       # a view produces a dwell sample
REACT_PROB = 0.06       # a view produces a reaction (unique per user/joke)
SAVE_PROB = 0.04
FAV_PROB = 0.04
SHARE_PROB = 0.05
BASE_IMPR_PER_JOKE_DAY = 4    # baseline impressions per joke per day (pre pop*trend)

REACTION_WEIGHTS = [
    (JokeReaction.REACTION_LOL, 0.50),
    (JokeReaction.REACTION_CRYING, 0.28),
    (JokeReaction.REACTION_HMM, 0.14),
    (JokeReaction.REACTION_EYEROLL, 0.08),
]
SHARE_PLATFORM_WEIGHTS = [
    ('copy', 0.34), ('whatsapp', 0.24), ('twitter', 0.20),
    ('facebook', 0.14), ('other', 0.08),
]
VIEW_SOURCE_WEIGHTS = [
    (JokeView.SOURCE_DAILY, 0.28), (JokeView.SOURCE_EXPLORE, 0.22),
    (JokeView.SOURCE_SEARCH, 0.18), (JokeView.SOURCE_MYSTERY, 0.10),
    (JokeView.SOURCE_SAVED, 0.08), (JokeView.SOURCE_PACK, 0.07),
    (JokeView.SOURCE_SHARE, 0.04), (JokeView.SOURCE_OTHER, 0.03),
]
IMPR_SOURCE_WEIGHTS = [
    (JokeImpression.SOURCE_FEED, 0.40), (JokeImpression.SOURCE_EXPLORE, 0.24),
    (JokeImpression.SOURCE_SEARCH, 0.16), (JokeImpression.SOURCE_DAILY, 0.12),
    (JokeImpression.SOURCE_PACK, 0.05), (JokeImpression.SOURCE_OTHER, 0.03),
]

# "Long" formats get read-through (scroll_pct) dwells so completion_rate is meaningful.
LONG_FORMATS = {'short-story', 'story', 'observ', 'anti'}

# --- The demo joke catalogue (genuinely short + funny; varied axes) ----------
# format slug / tone(category) slugs / context(theme) slugs / culture slugs.
# Ordered by intended popularity (first = strongest) so top_jokes ranks clearly.
JOKES = [
    dict(text="My boss told me to have a good day. So I went home.",
         fmt='oneliner', tones=['sarcasm'], themes=['work', 'mondays'], cultures=['universal']),
    dict(text="Why did the coffee file a police report? It got mugged.",
         setup="Why did the coffee file a police report?", punchline="It got mugged.",
         fmt='setup', tones=['dad-jokes', 'puns'], themes=['food'], cultures=['universal']),
    dict(text="Autocorrect is the reason I now confidently duck at people who "
              "cut me off in traffic.",
         fmt='observ', tones=['sarcasm'], themes=['tech'], cultures=['american']),
    dict(text="I told my girlfriend she drew her eyebrows too high. She looked surprised.",
         fmt='oneliner', tones=['dad-jokes'], themes=['dating'], cultures=['universal']),
    dict(text="Why do programmers prefer dark mode? Because light attracts bugs.",
         setup="Why do programmers prefer dark mode?", punchline="Because light attracts bugs.",
         fmt='setup', tones=['nerd'], themes=['tech'], cultures=['universal']),
    dict(text="My bank called about 'suspicious activity' on my account. It was me. "
              "Saving money.",
         fmt='observ', tones=['sarcasm'], themes=['money'], cultures=['american']),
    dict(text="I used to hate facial hair. But then it grew on me.",
         fmt='oneliner', tones=['puns', 'dad-jokes'], themes=['animals'], cultures=['universal']),
    dict(text="Why can't you trust an atom? Because they literally make up everything.",
         setup="Why can't you trust an atom?", punchline="Because they literally make up everything.",
         fmt='setup', tones=['nerd'], themes=['science'], cultures=['universal']),
    dict(text="School taught me that the mitochondria is the powerhouse of the cell "
              "and absolutely nothing about taxes. Fantastic priorities.",
         fmt='observ', tones=['clean', 'sarcasm'], themes=['school'], cultures=['universal']),
    dict(text="What do you call cheese that isn't yours? Nacho cheese.",
         setup="What do you call cheese that isn't yours?", punchline="Nacho cheese.",
         fmt='setup', tones=['puns', 'dad-jokes'], themes=['food'], cultures=['universal']),
    dict(text="I booked a table for two at a fancy restaurant to work on myself. "
              "The waiter asked if I was expecting anyone. I said, 'Just personal growth.' "
              "He brought one breadstick.",
         fmt='short-story', tones=['sarcasm', 'surreal'], themes=['dating', 'food'], cultures=['universal']),
    dict(text="I asked the British weatherman if it would rain. He said, 'Cloudy, with "
              "a strong chance of me being wrong.'",
         fmt='oneliner', tones=['dad-jokes'], themes=['weather'], cultures=['british']),
    dict(text="A man walks into a library and asks for books on paranoia. The librarian "
              "whispers, 'They're right behind you.' They were. It was just the shelf.",
         fmt='anti', tones=['surreal'], themes=['school'], cultures=['universal']),
    dict(text="My suitcase told me there'd be no vacation this year. Now we're both "
              "dealing with a lot of emotional baggage.",
         fmt='short-story', tones=['puns', 'wholesome'], themes=['travel'], cultures=['universal']),
]

# Popularity weight per joke (index-aligned with JOKES). Gentle gradient — enough
# spread that top_jokes ranks clearly, but no runaway joke (the insights top_jokes
# query cost is O(per-joke views x impressions x reactions x saves x shares), so a
# steep top joke is what makes that query slow).
POPULARITY = [1.35, 1.28, 1.20, 1.14, 1.08, 1.03, 0.99, 0.95, 0.91, 0.87, 0.83, 0.78, 0.72, 0.65]


def weighted_pick(pairs):
    """pairs = [(value, weight), ...] -> one value."""
    values = [p[0] for p in pairs]
    weights = [p[1] for p in pairs]
    return random.choices(values, weights=weights, k=1)[0]


class Command(BaseCommand):
    help = 'Seed a rich fake demo creator + audience so /create/insights is fully populated.'

    def add_arguments(self, parser):
        parser.add_argument('--email', default=DEFAULT_EMAIL)
        parser.add_argument('--password', default=DEFAULT_PASSWORD)
        parser.add_argument('--jokes', type=int, default=14)
        parser.add_argument('--viewers', type=int, default=140)
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument(
            '--fresh', action='store_true',
            help='Fully wipe previously-seeded demo data + demo/viewer users, then reseed.',
        )

    # ------------------------------------------------------------------ #
    #  Cleanup helpers                                                     #
    # ------------------------------------------------------------------ #
    def _seeded_users_qs(self, email):
        # Never match a real, pre-existing account: only fold in `email` when it
        # is itself a seed-domain account, so --fresh can't delete a real user.
        q = Q(email__iendswith=SEED_DOMAIN)
        if email.lower().endswith(SEED_DOMAIN):
            q |= Q(email__iexact=email)
        return User.objects.filter(q)

    def _full_wipe(self, email):
        """--fresh: delete seeded jokes (cascades their engagement) then all
        seeded users (cascades their engagement/follows/profiles/subscriptions)."""
        users = self._seeded_users_qs(email)
        jokes_deleted, _ = Joke.all_objects.filter(creator__in=users).delete()
        users_deleted, _ = users.delete()
        self.stdout.write(self.style.WARNING(
            f'  --fresh wipe: removed {jokes_deleted} joke-graph rows + {users_deleted} user-graph rows'
        ))

    def _reset_demo_dataset(self, creator):
        """Idempotent reset run on every invocation: drop the creator's seeded
        jokes (cascades all engagement on them) and only THIS creator's viewers
        (cascades their engagement/follows). Other seeded creators are untouched,
        so demo + a real account can each hold their own rich dataset."""
        Joke.all_objects.filter(creator=creator).delete()
        (User.objects
         .filter(email__istartswith=f'demo.viewer.{creator.pk}.')
         .delete())

    # ------------------------------------------------------------------ #
    #  Reference-data + user setup                                        #
    # ------------------------------------------------------------------ #
    def _lookup(self):
        """Fetch (or create) the lookup rows the jokes reference. Defensive so
        the command is self-contained even on a bare DB."""
        fmt = {f.slug: f for f in Format.objects.all()}
        # Ensure every format the catalogue references exists.
        for slug in {j['fmt'] for j in JOKES}:
            if slug not in fmt:
                fmt[slug] = Format.objects.create(
                    name=slug.replace('-', ' ').title(), slug=slug)
        tones = {t.slug: t for t in Tone.objects.all()}
        for slug in {s for j in JOKES for s in j['tones']}:
            if slug not in tones:
                tones[slug] = Tone.objects.create(name=slug.title(), slug=slug)
        themes = {c.slug: c for c in ContextTag.objects.all()}
        for slug in {s for j in JOKES for s in j['themes']}:
            if slug not in themes:
                themes[slug] = ContextTag.objects.create(name=slug.title(), slug=slug)
        cultures = {c.slug: c for c in CultureTag.objects.all()}
        for slug in {s for j in JOKES for s in j['cultures']}:
            if slug not in cultures:
                cultures[slug] = CultureTag.objects.create(name=slug.title(), slug=slug)
        age = AgeRating.objects.filter(slug='teen').first() or AgeRating.objects.first()
        if age is None:
            age = AgeRating.objects.create(name='Teen', slug='teen')
        lang = Language.objects.filter(code='en').first() or Language.objects.first()
        if lang is None:
            lang = Language.objects.create(code='en', name='English')
        return fmt, tones, themes, cultures, age, lang

    def _get_or_make_creator(self, email, password):
        creator = User.objects.filter(email__iexact=email).first()
        username = email.split('@')[0].replace('.', '_')[:150]
        is_seed_account = email.lower().endswith(SEED_DOMAIN)
        # A real, pre-existing account (e.g. the owner's) is only ATTRIBUTED demo
        # content — never re-credentialed, re-activated, or identity-clobbered.
        preserve = creator is not None and not is_seed_account
        if creator is None:
            creator = User(username=username, email=email, is_active=True)
            creator.set_password(password)
            creator.save()  # triggers signals -> UserProfile / Preference / Collection
        elif not preserve:
            creator.is_active = True
            creator.set_password(password)
            creator.save()

        # Public identity for the profile/insights header.
        profile = creator.profile
        if not preserve:
            profile.display_name = DISPLAY_NAME
            # handle is globally unique; only claim it if free (or already ours).
            clash = User.objects.filter(profile__handle=HANDLE).exclude(pk=creator.pk).exists()
            profile.handle = HANDLE if not clash else f'{HANDLE}{creator.pk}'
            profile.bio = 'Serving up daily one-liners and slow-burn story jokes. Reply guy of the punchline.'
        else:
            # Fill only what's empty — never overwrite the real account's identity.
            if not (profile.display_name or '').strip():
                profile.display_name = DISPLAY_NAME
            if not (profile.handle or '').strip():
                clash = User.objects.filter(profile__handle=HANDLE).exclude(pk=creator.pk).exists()
                profile.handle = HANDLE if not clash else f'{HANDLE}{creator.pk}'
            if not (profile.bio or '').strip():
                profile.bio = 'Serving up daily one-liners and slow-burn story jokes.'
        profile.public_profile = True
        profile.save()
        return creator

    def _make_viewers(self, n, creator):
        """Lightweight fake viewers for distinct-interaction attribution,
        namespaced per creator (demo.viewer.<creator_pk>.<i>) so multiple seeded
        creators never share — and therefore never wipe — each other's audience."""
        viewers = [
            User(
                username=f'demo_viewer_{creator.pk}_{i}',
                email=f'demo.viewer.{creator.pk}.{i}{SEED_DOMAIN}',
                is_active=True,
                password='!',  # unusable; viewers never log in
            )
            for i in range(1, n + 1)
        ]
        User.objects.bulk_create(viewers, batch_size=500)
        return viewers

    # ------------------------------------------------------------------ #
    #  Time helpers                                                       #
    # ------------------------------------------------------------------ #
    def _aware(self, d, hour):
        naive = datetime(d.year, d.month, d.day, hour,
                         random.randint(0, 59), random.randint(0, 59))
        return timezone.make_aware(naive)

    def _evening_dt(self, d):
        return self._aware(d, random.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0])

    def _bulk_backdate(self, model, objs, dt_field, date_field=None):
        """bulk_create then bulk_update the timestamp fields to their backdated
        targets. auto_now_add forces now() on INSERT, so we re-write afterwards
        (bulk_update writes attribute values verbatim, no pre_save)."""
        if not objs:
            return
        targets = [getattr(o, dt_field) for o in objs]
        model.objects.bulk_create(objs, batch_size=2000)
        for o, t in zip(objs, targets):
            setattr(o, dt_field, t)
            if date_field:
                setattr(o, date_field, t.date())
        fields = [dt_field] + ([date_field] if date_field else [])
        model.objects.bulk_update(objs, fields, batch_size=2000)

    # ------------------------------------------------------------------ #
    #  Main                                                               #
    # ------------------------------------------------------------------ #
    @transaction.atomic
    def handle(self, *args, **opts):
        random.seed(RANDOM_SEED)
        email = opts['email']
        password = opts['password']
        n_jokes = max(1, opts['jokes'])
        n_viewers = max(10, opts['viewers'])
        days = max(2, opts['days'])

        if opts['fresh']:
            self._full_wipe(email)

        fmt, tones, themes, cultures, age, lang = self._lookup()
        creator = self._get_or_make_creator(email, password)
        self._reset_demo_dataset(creator)  # idempotent: clear prior jokes + viewers
        viewers = self._make_viewers(n_viewers, creator)

        today = timezone.localdate()
        # date + upward-trend scale for each day index (0 = oldest, days-1 = today)
        day_dates = [today - timedelta(days=(days - 1 - di)) for di in range(days)]
        scales = [0.55 + 0.90 * (di / (days - 1)) for di in range(days)]

        # --- Create the jokes (bulk; backdate publish dates across the window) ---
        catalogue = JOKES[:n_jokes]
        joke_objs = []
        publish_dts = []
        for i, spec in enumerate(catalogue):
            # oldest joke first -> newest last (so the newest lands ~today).
            frac = i / (len(catalogue) - 1) if len(catalogue) > 1 else 1.0
            pub_date = today - timedelta(days=int((days - 1) * (1 - frac)))
            pub_dt = self._aware(pub_date, random.choice([9, 12, 17, 20]))
            publish_dts.append(pub_dt)
            joke_objs.append(Joke(
                text=spec['text'], setup=spec.get('setup', ''), punchline=spec.get('punchline', ''),
                format=fmt[spec['fmt']], age_rating=age, language=lang,
                creator=creator, content_tier='tier_1', is_removed=False,
                created_at=pub_dt,
            ))
        self._bulk_backdate(Joke, joke_objs, 'created_at')

        # M2M tags per joke.
        for spec, joke in zip(catalogue, joke_objs):
            joke.tones.set([tones[s] for s in spec['tones']])
            joke.context_tags.set([themes[s] for s in spec['themes']])
            joke.culture_tags.set([cultures[s] for s in spec['cultures']])

        # Published submissions (so the 'consistency' suggestion is believable).
        subs = []
        for spec, joke, pub_dt in zip(catalogue, joke_objs, publish_dts):
            subs.append(JokeSubmission(
                user=creator, text=joke.text, setup=joke.setup, punchline=joke.punchline,
                format=joke.format, age_rating=age, language=lang, source='original',
                status='published', published_joke=joke,
                created_at=pub_dt, updated_at=pub_dt,
            ))
        JokeSubmission.objects.bulk_create(subs, batch_size=500)
        for s, pub_dt in zip(subs, publish_dts):
            s.created_at = pub_dt
            s.updated_at = pub_dt
        JokeSubmission.objects.bulk_update(subs, ['created_at', 'updated_at'], batch_size=500)

        # --- Generate the engagement funnel ---
        impressions, views, dwells = [], [], []
        reactions, saves, favs, shares = [], [], [], []
        reacted, saved, faved = set(), set(), set()  # enforce per-user/joke uniqueness

        pops = POPULARITY[:len(catalogue)]
        for j_idx, (spec, joke) in enumerate(zip(catalogue, joke_objs)):
            is_long = spec['fmt'] in LONG_FORMATS
            pop = pops[j_idx]
            for di in range(days):
                d = day_dates[di]
                scale = scales[di]
                n_impr = int(round(BASE_IMPR_PER_JOKE_DAY * pop * scale))
                n_impr = max(0, min(n_impr, len(viewers)))
                if n_impr == 0:
                    continue
                seen = random.sample(viewers, n_impr)  # distinct viewers -> one impression each
                for u in seen:
                    impressions.append(JokeImpression(
                        user=u, joke=joke, source=weighted_pick(IMPR_SOURCE_WEIGHTS),
                        created_at=self._aware(d, random.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]),
                        created_date=d,
                    ))
                # A fraction of the card-seers open the joke (open_rate ~0.28-0.40).
                open_frac = random.uniform(0.28, 0.40)
                n_views = int(round(n_impr * open_frac))
                for u in seen[:n_views]:
                    vdt = self._evening_dt(d)
                    revealed = random.random() < PAYOFF_PROB
                    views.append(JokeView(
                        user=u, joke=joke, source=weighted_pick(VIEW_SOURCE_WEIGHTS),
                        revealed_punchline=revealed, viewed_at=vdt, viewed_date=d,
                    ))
                    key = (u.pk, joke.pk)
                    # Dwell sample
                    if random.random() < DWELL_PROB:
                        dwells.append(JokeDwell(
                            user=u, joke=joke,
                            dwell_ms=self._dwell_ms(is_long),
                            scroll_pct=self._scroll_pct(is_long),
                            source='detail',
                            created_at=vdt, created_date=d,
                        ))
                    # Reaction (unique per user/joke)
                    if random.random() < REACT_PROB and key not in reacted:
                        reacted.add(key)
                        reactions.append(JokeReaction(
                            user=u, joke=joke, reaction=weighted_pick(REACTION_WEIGHTS),
                            created_at=vdt,
                        ))
                    # Save (unique per user/joke, collection=None)
                    if random.random() < SAVE_PROB and key not in saved:
                        saved.add(key)
                        saves.append(SavedJoke(user=u, joke=joke, collection=None, created_at=vdt))
                    # Favorite (unique per user/joke)
                    if random.random() < FAV_PROB and key not in faved:
                        faved.add(key)
                        favs.append(Favorite(user=u, joke=joke, created_at=vdt))
                    # Share (no uniqueness constraint)
                    if random.random() < SHARE_PROB:
                        shares.append(ShareEvent(
                            user=u, joke=joke, platform=weighted_pick(SHARE_PLATFORM_WEIGHTS),
                            created_at=vdt,
                        ))

        self._bulk_backdate(JokeImpression, impressions, 'created_at', 'created_date')
        self._bulk_backdate(JokeView, views, 'viewed_at', 'viewed_date')
        self._bulk_backdate(JokeDwell, dwells, 'created_at', 'created_date')
        self._bulk_backdate(JokeReaction, reactions, 'created_at')
        self._bulk_backdate(SavedJoke, saves, 'created_at')
        self._bulk_backdate(Favorite, favs, 'created_at')
        self._bulk_backdate(ShareEvent, shares, 'created_at')

        # --- Followers (upward slope toward recent days) ---
        n_followers = min(len(viewers), int(len(viewers) * random.uniform(0.72, 0.90)))
        follower_pool = random.sample(viewers, n_followers)
        follows = []
        for u in follower_pool:
            di = random.choices(range(days), weights=scales, k=1)[0]
            follows.append(Follow(
                follower=u, creator=creator,
                created_at=self._aware(day_dates[di], random.randint(7, 23)),
            ))
        self._bulk_backdate(Follow, follows, 'created_at')

        # --- Verify backdating actually landed in the past ---
        self._verify_backdating()

        # --- Print the real insights summary ---
        self._print_summary(creator, email, password,
                            len(catalogue), n_viewers, days,
                            len(impressions), len(views), len(dwells),
                            len(reactions), len(saves), len(favs), len(shares), n_followers)

    # ------------------------------------------------------------------ #
    #  Distribution helpers                                              #
    # ------------------------------------------------------------------ #
    def _dwell_ms(self, is_long):
        r = random.random()
        if r < 0.22:
            return random.randint(800, 3999)       # brief glance (below read threshold)
        if is_long:
            return random.randint(9000, 150000)    # genuine read of a longer joke
        return random.randint(4000, 45000)         # genuine read

    def _scroll_pct(self, is_long):
        # Long jokes always carry read-through depth; short jokes sometimes do.
        if not (is_long or random.random() < 0.25):
            return None
        deep = random.random() < (0.65 if is_long else 0.55)
        return random.randint(90, 100) if deep else random.randint(30, 89)

    # ------------------------------------------------------------------ #
    #  Verification + summary                                            #
    # ------------------------------------------------------------------ #
    def _verify_backdating(self):
        today = timezone.localdate()
        checks = [
            ('JokeView.viewed_at', JokeView, 'viewed_at'),
            ('JokeImpression.created_at', JokeImpression, 'created_at'),
            ('JokeDwell.created_at', JokeDwell, 'created_at'),
            ('Follow.created_at', Follow, 'created_at'),
        ]
        self.stdout.write(self.style.MIGRATE_HEADING('\nBackdating verification (min .. max):'))
        for label, model, field in checks:
            agg = model.objects.aggregate(lo=Min(field), hi=Max(field))
            lo, hi = agg['lo'], agg['hi']
            ok = lo is not None and lo.date() < today  # spread reaches into the past
            flag = 'OK' if ok else 'WARNING (not historical!)'
            self.stdout.write(f'  {label:28s} {lo} .. {hi}  [{flag}]')

    def _print_summary(self, creator, email, password, n_jokes, n_viewers, days,
                        n_impr, n_views, n_dwell, n_react, n_save, n_fav, n_share, n_followers):
        _t0 = time.perf_counter()
        data = build_creator_insights(creator, 'month')
        _elapsed = time.perf_counter() - _t0
        ov = data['overview']
        nonzero_days = sum(1 for v in ov['daily_reach_28d'] if v > 0)
        follower_series_nonzero = sum(1 for v in ov['follower_growth_28d'] if v > 0)

        s = self.style
        self.stdout.write(s.SUCCESS('\n' + '=' * 66))
        self.stdout.write(s.SUCCESS('  DEMO CREATOR SEEDED'))
        self.stdout.write(s.SUCCESS('=' * 66))
        self.stdout.write(f'  Login email    : {email}')
        self.stdout.write(f'  Login password : {password}')
        self.stdout.write(f'  Display / handle: {DISPLAY_NAME} / @{creator.profile.handle}')
        self.stdout.write(f'  Seeded         : {n_jokes} jokes, {n_viewers} viewers, {days} days')
        self.stdout.write(f'  Rows           : {n_impr} impressions, {n_views} views, '
                          f'{n_dwell} dwells, {n_react} reactions, {n_save} saves, '
                          f'{n_fav} favs, {n_share} shares, {n_followers} followers')

        self.stdout.write(s.MIGRATE_HEADING(
            f"\n  build_creator_insights(creator, 'month') [{_elapsed:.2f}s] overview:"))
        pct = lambda x: f'{x*100:.1f}%' if x is not None else 'None'
        self.stdout.write(f"    views={ov['views']}  reach={ov['reach']}  "
                          f"impressions={ov['impressions']}  unique_reach={ov['unique_reach']}")
        self.stdout.write(f"    open_rate={pct(ov['open_rate'])}  payoff_rate={pct(ov['payoff_rate'])}  "
                          f"read_rate={pct(ov['read_rate'])}  completion_rate={pct(ov['completion_rate'])}")
        self.stdout.write(f"    avg_read_seconds={ov['avg_read_seconds']}  "
                          f"peak_read_hour={ov['peak_read_hour']}:00")
        self.stdout.write(f"    reactions={ov['reactions']}  favorites={ov['favorites']}  "
                          f"saves={ov['saves']}  shares={ov['shares']}")
        self.stdout.write(f"    followers={ov['followers']}  "
                          f"daily_reach_28d: {nonzero_days}/28 non-zero days  "
                          f"follower_growth_28d: {follower_series_nonzero}/28 non-zero")
        self.stdout.write(f"    daily_reach_28d last 7: {ov['daily_reach_28d'][-7:]}")
        self.stdout.write(f"    follower_growth_28d last 7: {ov['follower_growth_28d'][-7:]}")

        self.stdout.write(s.MIGRATE_HEADING('\n  Breakdowns:'))
        self.stdout.write(f"    reactions_breakdown : {data['reactions_breakdown']}")
        self.stdout.write(f"    shares_breakdown    : {data['shares_breakdown']}")
        self.stdout.write(f"    source_mix          : {data['source_mix']}")
        self.stdout.write(f"    audience top_themes : "
                          f"{[t['label'] for t in data['audience']['top_themes'][:5]]}")
        self.stdout.write(f"    audience top_formats: "
                          f"{[t['label'] for t in data['audience']['top_formats']]}")

        self.stdout.write(s.MIGRATE_HEADING(f"\n  top_jokes ({len(data['top_jokes'])}):"))
        for tj in data['top_jokes'][:5]:
            self.stdout.write(
                f"    v={tj['views']:<4} impr={tj['impressions']:<4} react={tj['reactions']:<3} "
                f"save={tj['saves']:<3} share={tj['shares']:<3} "
                f"payoff={pct(tj['payoff_rate'])} read={pct(tj['read_rate'])} "
                f"~{tj['avg_read_seconds']}s  \"{tj['text'][:44]}\"")

        self.stdout.write(s.MIGRATE_HEADING('\n  suggestions:'))
        for sg in data['suggestions']:
            self.stdout.write(f"    [{sg['kind']}] {sg['title']}")
        self.stdout.write(s.SUCCESS('=' * 66 + '\n'))
