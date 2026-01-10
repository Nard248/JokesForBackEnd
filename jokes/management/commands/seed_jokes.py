import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from jokes.models import (
    Joke, Format, AgeRating, Tone, ContextTag, Language, CultureTag, Source
)


class Command(BaseCommand):
    help = 'Seed jokes from the jokes.json fixture file'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=150,
            help='Maximum number of jokes to load (default: 150)'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete all existing jokes before loading'
        )

    def handle(self, *args, **options):
        # Check lookup tables are populated
        self._validate_lookup_tables()

        # Clear existing jokes if requested
        if options['clear']:
            deleted_count = Joke.objects.count()
            Joke.objects.all().delete()
            self.stdout.write(
                self.style.WARNING(f'Deleted {deleted_count} existing jokes')
            )

        # Load jokes from fixture
        fixture_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'fixtures',
            'jokes.json'
        )

        if not os.path.exists(fixture_path):
            self.stdout.write(
                self.style.WARNING(
                    f'Fixture file not found: {fixture_path}\n'
                    '0 jokes loaded'
                )
            )
            return

        with open(fixture_path, 'r', encoding='utf-8') as f:
            jokes_data = json.load(f)

        if not jokes_data:
            self.stdout.write(
                self.style.WARNING('Fixture file is empty\n0 jokes loaded')
            )
            return

        # Limit to requested count
        max_count = options['count']
        jokes_data = jokes_data[:max_count]

        # Load jokes with M2M relationships
        loaded_count = self._load_jokes(jokes_data)

        self.stdout.write(
            self.style.SUCCESS(f'Successfully loaded {loaded_count} jokes')
        )

    def _validate_lookup_tables(self):
        """Ensure all lookup tables have data."""
        checks = [
            (Format, 'Format'),
            (AgeRating, 'AgeRating'),
            (Tone, 'Tone'),
            (ContextTag, 'ContextTag'),
            (Language, 'Language'),
            (CultureTag, 'CultureTag'),
            (Source, 'Source'),
        ]

        missing = []
        for model, name in checks:
            if model.objects.count() == 0:
                missing.append(name)

        if missing:
            raise CommandError(
                f'Missing lookup data. Empty tables: {", ".join(missing)}. '
                'Run "python manage.py loaddata lookup_data" first.'
            )

    @transaction.atomic
    def _load_jokes(self, jokes_data):
        """Load jokes from fixture data, handling M2M relationships."""
        loaded_count = 0

        for joke_entry in jokes_data:
            if joke_entry.get('model') != 'jokes.joke':
                continue

            fields = joke_entry.get('fields', {})

            # Extract M2M fields before creating joke
            tones_pks = fields.pop('tones', [])
            context_tags_pks = fields.pop('context_tags', [])
            culture_tags_pks = fields.pop('culture_tags', [])

            # Create the joke object
            joke = Joke.objects.create(
                text=fields.get('text', ''),
                setup=fields.get('setup', ''),
                punchline=fields.get('punchline', ''),
                format_id=fields.get('format'),
                age_rating_id=fields.get('age_rating'),
                language_id=fields.get('language'),
                source_id=fields.get('source'),
            )

            # Set M2M relationships
            if tones_pks:
                joke.tones.set(tones_pks)
            if context_tags_pks:
                joke.context_tags.set(context_tags_pks)
            if culture_tags_pks:
                joke.culture_tags.set(culture_tags_pks)

            loaded_count += 1

        return loaded_count
