from django.core.management.base import BaseCommand, CommandError

from jokes.search_index import rebuild_search_documents


class Command(BaseCommand):
    help = 'Rebuild weighted PostgreSQL joke search documents in bounded batches.'

    def add_arguments(self, parser):
        parser.add_argument('--database', default='default')
        parser.add_argument('--batch-size', type=int, default=500)

    def handle(self, *args, **options):
        if not 1 <= options['batch_size'] <= 5000:
            raise CommandError('--batch-size must be between 1 and 5000.')
        count = rebuild_search_documents(
            using=options['database'], batch_size=options['batch_size'],
        )
        self.stdout.write(self.style.SUCCESS(f'Rebuilt {count} joke search documents.'))
