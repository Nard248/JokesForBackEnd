"""Operational search repair using the same database function as live writes."""

from django.db import connections, transaction


def rebuild_search_documents(*, using='default', batch_size=500):
    """Rebuild all rows, including moderated ones, committing bounded batches."""
    from .models import Joke

    last_id = 0
    rebuilt = 0
    while ids := list(Joke.all_objects.using(using).filter(pk__gt=last_id)
                     .order_by('pk').values_list('pk', flat=True)[:batch_size]):
        with transaction.atomic(using=using), connections[using].cursor() as cursor:
            cursor.execute(
                'SELECT jokes_refresh_search_document(id) FROM unnest(%s::bigint[]) AS targets(id)',
                [ids],
            )
        rebuilt += len(ids)
        last_id = ids[-1]
    return rebuilt
