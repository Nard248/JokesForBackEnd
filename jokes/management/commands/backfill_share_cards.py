"""Backfill share cards for published jokes that lack one.

Seed/bulk-created jokes bypass Joke.save()'s card generation, so they have
no share_image (or a pre-share-cards-wave text-only card for media jokes).
This regenerates cards for LIVE (non-removed) jokes on demand — request-
triggered, no worker; run manually or as a one-off ops task.

Dry-run by default: prints what it WOULD do. Pass --apply to write.
Idempotent and safe to re-run. Never touches removed jokes (the share-cards
wave forbids generating a card for is_removed=True — mirrored here).
"""
from django.core.management.base import BaseCommand

from jokes.models import Joke


class Command(BaseCommand):
    help = 'Regenerate share cards for live jokes that are missing one.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually regenerate (default is a dry run).',
        )
        parser.add_argument(
            '--only-media', action='store_true',
            help='Only jokes whose format is image/video/audio (media cards).',
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Cap the number processed this run (0 = no cap).',
        )

    def handle(self, *args, **options):
        apply = options['apply']
        # Joke.objects excludes removed jokes globally — exactly the set we may
        # regenerate. A blank share_image FieldFile is falsy.
        qs = Joke.objects.filter(share_image='').order_by('pk')
        if options['only_media']:
            qs = qs.filter(format__slug__in=('image', 'video', 'audio'))
        if options['limit']:
            qs = qs[:options['limit']]

        total = qs.count() if not options['limit'] else len(qs)
        self.stdout.write(f'{total} live joke(s) missing a share card.')
        if not apply:
            self.stdout.write(self.style.WARNING('Dry run — pass --apply to regenerate.'))
            return

        done = 0
        failed = 0
        for joke in qs:
            try:
                joke.regenerate_share_image()
                done += 1
            except Exception as exc:  # fail-open per joke — one bad raster
                failed += 1              # must not abort the backfill.
                self.stderr.write(f'  joke {joke.pk}: {exc}')
        self.stdout.write(self.style.SUCCESS(
            f'Regenerated {done} card(s); {failed} failed (see stderr).'
        ))
