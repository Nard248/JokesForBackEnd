"""Deterministic, local-only fixtures for the end-to-end suite.

Registration specs create their users through the real API. Reader specs need
enough tier_1 material to verify unrestricted reading across the former limit.
Creator specs use a fixed, verified adult account with Creator Pro and 26 own
published rows, so filtering, pagination and export can use the real API.

That last part is the point. The paywall leak that reached production only
affected two-part formats, and the fixtures in the unit suite build jokes with
``text=''`` — unlike real published rows, which carry a denormalized
"<setup> <punchline>". Tests written against those fixtures could not see the
bug. Everything created here is shaped the way the publish pipeline shapes it.

Idempotent on local development databases. Refuses non-debug mode, non-loopback
PostgreSQL, alternate libpq routing, and nonlocal media storage before any write.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from billing.models import Plan, Subscription
from jokes.management.local_only import require_local_database
from jokes.models import AgeRating, ContextTag, Format, Joke, JokeSubmission, Language, Tone

#: Marker so the fixture can be found and refreshed without touching real rows.
E2E_MARKER = '[e2e]'

# Public test credentials, never a production account. The command has no
# bypass flag for its DEBUG/local resource guard.
E2E_CREATOR_EMAIL = 'creator-workbench@e2e.invalid'
E2E_CREATOR_PASSWORD = 'E2E-local-only-2026!'
E2E_CREATOR_TEXT = f'{E2E_MARKER} Creator workbench: timing is everything.'
E2E_CREATOR_COUNT = 26

#: One joke per format, each built the way the publish pipeline builds it.
#: `text` is the denormalized field a published joke really carries.
_SPECS = [
    {
        'format': 'setup',
        'setup': f'{E2E_MARKER} Why did the two-part joke cross the road?',
        'punchline': 'To prove every reader can reach the punchline.',
    },
    {
        'format': 'anti',
        'setup': f'{E2E_MARKER} Why did the anti-joke cross the road?',
        'punchline': 'It did not. It stayed exactly where it was.',
    },
    {
        'format': 'oneliner',
        'text': f'{E2E_MARKER} I told my laptop a joke about paging; it never returned.',
    },
    {
        'format': 'observ',
        'text': f'{E2E_MARKER} Adulthood is discovering your search index has opinions.',
    },
    {
        'format': 'story',
        'text': (
            f'{E2E_MARKER} A tester walks into a bar and orders one beer, then zero '
            'beers, then nine hundred and ninety nine thousand beers, then a lizard, '
            'then minus one beer. Satisfied, the tester leaves. The first real '
            'customer walks in and asks where the bathroom is, and the bar bursts '
            'into flames because nobody thought to test that at all.'
        ),
    },
    {
        'format': 'knock',
        'lines': ['Knock, knock.', "Who's there?", 'Regression.', 'Regression who?'],
    },
]

#: Enough material to exercise repeated reads beyond the former reader limit.
_FILLER_COUNT = 24


class Command(BaseCommand):
    help = 'Seed local-only E2E reader content and a verified Creator Pro test account.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fresh', action='store_true',
            help='Delete existing [e2e] jokes first instead of reusing them.',
        )

    def handle(self, *args, **options):
        # Inspect connection configuration without opening a connection. Guard
        # before transaction.atomic: even --fresh must never reach a remote DB.
        require_local_database('seed_e2e')
        self._seed(options)

    @transaction.atomic
    def _seed(self, options):
        if options['fresh']:
            removed, _ = Joke.all_objects.filter(text__startswith=E2E_MARKER).delete()
            Joke.all_objects.filter(setup__startswith=E2E_MARKER).delete()
            self.stdout.write(f'Removed {removed} existing [e2e] jokes.')

        age = AgeRating.objects.order_by('min_age').first()
        lang = Language.objects.get(code='en')
        created = 0

        def _publish(**fields):
            """Create a joke the way the publish pipeline does, incl. the
            denormalized `text` that two-part formats really carry."""
            nonlocal created
            slug = fields.pop('format')
            fmt = Format.objects.filter(slug=slug).first()
            if fmt is None:
                self.stdout.write(self.style.WARNING(f'  format {slug!r} missing — skipped'))
                return
            setup = fields.get('setup', '')
            punchline = fields.get('punchline', '')
            lines = fields.get('lines')
            text = fields.get('text', '')
            if not text:
                if setup and punchline:
                    text = f'{setup} {punchline}'
                elif lines:
                    text = ' '.join(lines)
            lookup = {'setup': setup, 'punchline': punchline, 'text': text}
            if Joke.all_objects.filter(**lookup).exists():
                return
            Joke.objects.create(
                text=text, setup=setup, punchline=punchline, lines=lines,
                format=fmt, age_rating=age, language=lang, content_tier='tier_1',
            )
            created += 1

        for spec in _SPECS:
            _publish(**dict(spec))

        for i in range(_FILLER_COUNT):
            _publish(
                format='oneliner',
                text=f'{E2E_MARKER} Filler joke {i:02d}: free readers can keep going.',
            )

        self._seed_creator(age, lang)
        total = Joke.objects.filter(text__startswith=E2E_MARKER).count()
        total += Joke.objects.filter(setup__startswith=E2E_MARKER).count()
        self.stdout.write(self.style.SUCCESS(
            f'E2E content ready: {created} created, {total} [e2e] jokes live.'
        ))

    def _seed_creator(self, age, lang):
        """Restore only the reserved local fixture identity and its own rows."""
        creator, _ = get_user_model().objects.get_or_create(
            username=E2E_CREATOR_EMAIL, defaults={'email': E2E_CREATOR_EMAIL},
        )
        if creator.email != E2E_CREATOR_EMAIL:
            raise CommandError('Reserved E2E username belongs to a different local email; refusing to overwrite it.')
        creator.is_active = True  # This app uses is_active as its verified-email flag.
        creator.is_staff = False
        creator.is_superuser = False
        creator.set_password(E2E_CREATOR_PASSWORD)
        creator.save(update_fields=['is_active', 'is_staff', 'is_superuser', 'password'])
        creator.profile.date_of_birth = date(1990, 1, 1)
        creator.profile.display_name = 'E2E Creator'
        creator.profile.email_digest_opt_in = False
        creator.profile.creator_milestone_opt_in = False
        creator.profile.save(update_fields=[
            'date_of_birth', 'display_name', 'email_digest_opt_in', 'creator_milestone_opt_in',
        ])
        creator.preference.onboarding_completed = True
        creator.preference.notification_enabled = False
        creator.preference.save(update_fields=['onboarding_completed', 'notification_enabled'])
        Subscription.objects.update_or_create(user=creator, defaults={
            'plan': Plan.objects.get(slug='creator_pro'), 'status': 'active',
            'stripe_customer_id': '', 'stripe_subscription_id': '', 'stripe_price_id': '',
            'current_period_start': timezone.now(),
            'current_period_end': timezone.now() + timedelta(days=30),
            'cancel_at_period_end': False,
        })
        theme, _ = ContextTag.objects.get_or_create(
            slug='e2e-creator-theme', defaults={'name': 'E2E Creator Theme'},
        )
        category, _ = Tone.objects.get_or_create(
            slug='e2e-creator-category', defaults={'name': 'E2E Creator Category'},
        )
        fmt = Format.objects.get(slug='oneliner')
        primary = None
        for index in range(E2E_CREATOR_COUNT):
            text = E2E_CREATOR_TEXT if index == 0 else (
                f'{E2E_MARKER} Creator workbench item {index:02d}: another page of possibilities.'
            )
            joke, _ = Joke.all_objects.update_or_create(creator=creator, text=text, defaults={
                'format': fmt, 'age_rating': age, 'language': lang, 'content_tier': 'tier_1',
                'setup': '', 'punchline': '', 'is_removed': False, 'removed_at': None,
            })
            if index == 0:
                primary = joke
                joke.context_tags.set([theme])
                joke.tones.set([category])
        submission, _ = JokeSubmission.objects.update_or_create(
            user=creator, text=E2E_CREATOR_TEXT, defaults={
                'format': fmt, 'age_rating': age, 'language': lang,
                'status': 'published', 'published_joke': primary,
            },
        )
        submission.context_tags.set([theme])
        submission.tones.set([category])
        self.stdout.write(self.style.SUCCESS(
            f'LOCAL TEST creator ready: {E2E_CREATOR_EMAIL}; {E2E_CREATOR_COUNT} owned jokes. '
            'The test-only password is E2E_CREATOR_PASSWORD in seed_e2e.py.'
        ))
