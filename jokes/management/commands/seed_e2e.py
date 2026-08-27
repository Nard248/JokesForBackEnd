"""Deterministic content fixture for the end-to-end suite.

The E2E specs create their own *users* through the real registration API (so
signup itself is exercised), but they need a predictable body of *content* to
read: enough published tier_1 jokes to exhaust a 10/day paywall and still have
locked ones left over, and at least one joke of every format so a
format-specific regression cannot silently stop being covered.

That last part is the point. The paywall leak that reached production only
affected two-part formats, and the fixtures in the unit suite build jokes with
``text=''`` — unlike real published rows, which carry a denormalized
"<setup> <punchline>". Tests written against those fixtures could not see the
bug. Everything created here is shaped the way the publish pipeline shapes it.

Idempotent: safe to run before every suite.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from jokes.models import AgeRating, Format, Joke, Language

#: Marker so the fixture can be found and refreshed without touching real rows.
E2E_MARKER = '[e2e]'

#: One joke per format, each built the way the publish pipeline builds it.
#: `text` is the denormalized field a published joke really carries.
_SPECS = [
    {
        'format': 'setup',
        'setup': f'{E2E_MARKER} Why did the two-part joke cross the road?',
        'punchline': 'To prove the paywall strips every field.',
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

#: Filler so a reader can burn a 10/day allowance and still meet locked jokes.
_FILLER_COUNT = 24


class Command(BaseCommand):
    help = 'Seed deterministic published content for the end-to-end suite (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fresh', action='store_true',
            help='Delete existing [e2e] jokes first instead of reusing them.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
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
                text=f'{E2E_MARKER} Filler joke {i:02d}: the cap needs something to count.',
            )

        total = Joke.objects.filter(text__startswith=E2E_MARKER).count()
        total += Joke.objects.filter(setup__startswith=E2E_MARKER).count()
        self.stdout.write(self.style.SUCCESS(
            f'E2E content ready: {created} created, {total} [e2e] jokes live.'
        ))
