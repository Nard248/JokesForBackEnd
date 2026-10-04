"""Bounded raw analytics cleanup for an operator or a request opportunity."""
from django.core.management.base import BaseCommand, CommandError

from jokes.telemetry import purge_expired_analytics


class Command(BaseCommand):
    help = 'Delete up to 5000 optional analytics rows older than 90 days; reading history is preserved.'

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=500)

    def handle(self, *args, **options):
        try:
            deleted = purge_expired_analytics(batch_size=options['batch_size'])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(', '.join(f'{model}={count}' for model, count in deleted.items()))
