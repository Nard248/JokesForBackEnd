"""Fill the local content gaps a native client needs but the seeds never create.

The local database has plenty of text jokes — 344 of them — but the media and
mature surfaces are effectively empty:

    audio    0 published jokes
    video    1
    tier_2   2

You cannot build a format skin against zero rows. The audio card has its own
background, foreground and divider (``#F2E9FF`` / ``#6A1CF6``) and its own
locked-state layout, and none of it is reachable in a running app until an audio
joke exists to render.

Why this is not folded into ``seed_e2e``
----------------------------------------
``seed_e2e`` is a fixture for the Playwright suite, which exhausts a 10-reads-a-
day cap and asserts on what remains. Adding rows there shifts those counts and
would destabilise a green test tier to serve an unrelated purpose. This command
is additive, separately marked, and safe to run or skip.

Media files are generated with ffmpeg so they genuinely decode and play — a
zero-byte placeholder would let a broken player look like working code.

Idempotent: re-running reuses the jokes it already made.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from jokes.models import AgeRating, Format, Joke, JokeMedia, Language, MediaAsset

User = get_user_model()

#: Marker so these rows can be found, refreshed, or excluded without guessing.
DEV_MARKER = '[media-dev]'

#: `audio`/`video` require `setup` + exactly one media item, and forbid
#: `punchline` and `lines` (jokes/submission_rules.py). `text` is NOT NULL at the
#: DB level, so it carries the same string the setup does — which is also how
#: the existing published media jokes are shaped.
_MEDIA_SPECS = [
    {
        'format': 'audio',
        'setup': f'{DEV_MARKER} The sound a build makes when it finally passes',
        'kind': 'audio',
        'duration_ms': 3000,
    },
    {
        'format': 'audio',
        'setup': f'{DEV_MARKER} Listen to what my code review sounded like',
        'kind': 'audio',
        'duration_ms': 5000,
    },
    {
        'format': 'video',
        'setup': f'{DEV_MARKER} Watch the deploy pipeline discover the truth',
        'kind': 'video',
        'duration_ms': 3000,
        'width': 640,
        'height': 360,
    },
]

#: The catalogue has a mature tier the API can serve but almost nothing fills.
#: Two rows are not enough to see how a feed of them behaves.
_TIER2_SPECS = [
    {
        'format': 'oneliner',
        'text': f'{DEV_MARKER} My therapist says I have a preoccupation with vengeance. '
                'We will see about that.',
    },
    {
        'format': 'setup',
        'setup': f'{DEV_MARKER} What is the difference between a hippo and a Zippo?',
        'punchline': 'One is really heavy and the other is a little lighter.',
    },
    {
        'format': 'observ',
        'text': f'{DEV_MARKER} Nothing ages a person like watching a junior engineer '
                'discover that the staging database is the production database.',
    },
]


def _ffmpeg_available():
    return shutil.which('ffmpeg') is not None


def _make_audio(path, duration_ms):
    """A real, decodable m4a — a sine tone, not a placeholder."""
    subprocess.run(
        [
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi', '-i', f'sine=frequency=440:duration={duration_ms / 1000}',
            '-c:a', 'aac', '-b:a', '64k', str(path),
        ],
        check=True, capture_output=True,
    )


def _make_video(path, duration_ms, width, height):
    """A real, decodable mp4 with a moving test pattern and faststart, so a
    player can begin without downloading the whole file."""
    subprocess.run(
        [
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi',
            '-i', f'testsrc=size={width}x{height}:rate=15:duration={duration_ms / 1000}',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            str(path),
        ],
        check=True, capture_output=True,
    )


def _make_poster(path, width, height):
    subprocess.run(
        [
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi', '-i', f'testsrc=size={width}x{height}:rate=1:duration=1',
            '-frames:v', '1', str(path),
        ],
        check=True, capture_output=True,
    )


class Command(BaseCommand):
    help = (
        'Seed published audio/video jokes and mature-tier rows for local client '
        'development (idempotent). Separate from seed_e2e on purpose.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--fresh', action='store_true',
            help='Delete existing [media-dev] jokes and their assets first.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not _ffmpeg_available():
            self.stderr.write(self.style.ERROR(
                'ffmpeg not found. It generates the audio/video files, and a '
                'zero-byte placeholder would make a broken player look like '
                'working code. Install it (brew install ffmpeg) and re-run.'
            ))
            return

        if options['fresh']:
            stale = Joke.all_objects.filter(setup__startswith=DEV_MARKER)
            stale_text = Joke.all_objects.filter(text__startswith=DEV_MARKER)
            for asset in MediaAsset.objects.filter(
                joke_links__joke__in=stale.values('pk'),
            ).distinct():
                asset.delete_with_files()
            removed = stale.count() + stale_text.count()
            stale.delete()
            stale_text.delete()
            self.stdout.write(f'Removed {removed} existing {DEV_MARKER} jokes.')

        age = AgeRating.objects.order_by('min_age').first()
        lang = Language.objects.get(code='en')
        owner = self._owner()

        created_media = self._seed_media(owner, age, lang)
        created_tier2 = self._seed_tier2(age, lang)

        self.stdout.write(self.style.SUCCESS(
            f'{DEV_MARKER}: {created_media} media joke(s), {created_tier2} tier_2 joke(s) created.'
        ))
        self._report()

    def _owner(self):
        """MediaAsset requires an owner. Reuse the demo creator when it exists
        so these assets show up on a profile that already has content."""
        owner = User.objects.filter(email='demo.creator@jokesfor.dev').first()
        return owner or User.objects.order_by('pk').first()

    def _seed_media(self, owner, age, lang):
        if owner is None:
            self.stderr.write(self.style.WARNING(
                'No user exists to own media assets — run seed_demo_creator first. '
                'Skipping media jokes.'
            ))
            return 0

        created = 0
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for spec in _MEDIA_SPECS:
                fmt = Format.objects.filter(slug=spec['format']).first()
                if fmt is None:
                    self.stdout.write(self.style.WARNING(
                        f"  format {spec['format']!r} missing — skipped"
                    ))
                    continue
                if Joke.all_objects.filter(setup=spec['setup']).exists():
                    continue

                asset = self._build_asset(owner, spec, tmp)
                joke = Joke.objects.create(
                    # `text` is NOT NULL; media formats forbid a distinct text
                    # body, so it mirrors the setup exactly as published media
                    # jokes already do.
                    text=spec['setup'],
                    setup=spec['setup'],
                    punchline='',
                    format=fmt, age_rating=age, language=lang,
                    content_tier='tier_1', creator=owner,
                )
                JokeMedia.objects.create(joke=joke, asset=asset, position=0)
                created += 1
        return created

    def _build_asset(self, owner, spec, tmp):
        kind = spec['kind']
        asset = MediaAsset(
            owner=owner, kind=kind,
            duration_ms=spec.get('duration_ms'),
            width=spec.get('width'), height=spec.get('height'),
            # Pre-screened: these are synthetic tones and test patterns, so
            # marking them clean keeps them out of the moderation queue rather
            # than pretending a real SafeSearch call happened.
            safesearch={'seeded': True, 'verdict': 'clean'},
        )
        if kind == 'audio':
            src = tmp / 'audio.m4a'
            _make_audio(src, spec['duration_ms'])
            asset.file.save('audio.m4a', ContentFile(src.read_bytes()), save=False)
        else:
            src = tmp / 'video.mp4'
            _make_video(src, spec['duration_ms'], spec['width'], spec['height'])
            asset.file.save('video.mp4', ContentFile(src.read_bytes()), save=False)
            poster = tmp / 'poster.jpg'
            _make_poster(poster, spec['width'], spec['height'])
            asset.poster.save('poster.jpg', ContentFile(poster.read_bytes()), save=False)
        asset.save()
        return asset

    def _seed_tier2(self, age, lang):
        created = 0
        for spec in _TIER2_SPECS:
            fmt = Format.objects.filter(slug=spec['format']).first()
            if fmt is None:
                continue
            lookup = {
                'text': spec.get('text', ''),
                'setup': spec.get('setup', ''),
                'punchline': spec.get('punchline', ''),
            }
            if not lookup['text']:
                lookup['text'] = f"{lookup['setup']} {lookup['punchline']}".strip()
            if Joke.all_objects.filter(**lookup).exists():
                continue
            Joke.objects.create(
                **lookup, format=fmt, age_rating=age, language=lang,
                content_tier='tier_2',
            )
            created += 1
        return created

    def _report(self):
        from django.db.models import Count
        rows = (
            Joke.objects.values('format__slug')
            .annotate(n=Count('id')).order_by('-n')
        )
        counts = {r['format__slug']: r['n'] for r in rows}
        tier2 = Joke.objects.filter(content_tier='tier_2').count()
        self.stdout.write(
            '  published by format: '
            + ', '.join(f'{k}={v}' for k, v in counts.items() if v)
        )
        self.stdout.write(f'  tier_2 total: {tier2}')
