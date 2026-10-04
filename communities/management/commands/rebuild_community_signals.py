from django.core.management.base import BaseCommand

from communities import materialize, services


class Command(BaseCommand):
    help = ('Recreate the materialized community signals from the engagement ledgers. Idempotent; '
            'run after loaddata, bulk imports or any ledger write that bypassed model signals.')

    def handle(self, *args, **options):
        count = materialize.rebuild()
        services.invalidate()
        self.stdout.write(self.style.SUCCESS(f'Materialized {count} community signals.'))
