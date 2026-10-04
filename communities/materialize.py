"""Incremental, request-triggered materialization of community signals.

Every positive engagement row (laugh reaction, favorite, save, signed-in share)
is mirrored into ``CommunitySignal`` inside the same transaction that writes or
deletes it (``communities/signals.py``). No worker, no schedule: the write that
changes the ledger also changes the mirror.

The mirror is exact for the engine and every derived number:

* Within one signal kind the newest row is always the strongest (same weight,
  less decay), so the aggregate reads one row per (person, joke, kind).
* Shares are the only kind a person can repeat without limit. A share older
  than ``TREND_DAYS`` that has a newer share which is *also* older than
  ``TREND_DAYS`` can never again affect the current score, the week-ago
  comparison or the activity sparkline, so it is pruned.

Writes that bypass model signals (``bulk_create``, ``QuerySet.update`` on the
ledgers, ``loaddata``) must be followed by ``rebuild()`` —
``manage.py rebuild_community_signals``. The seed commands do this.
"""
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from communities.models import CommunitySignal
from jokes.models import Favorite, JokeReaction, SavedJoke, ShareEvent

POSITIVE_REACTIONS = (JokeReaction.REACTION_LOL, JokeReaction.REACTION_CRYING)
# The "a week ago" comparison and the activity sparkline both look back this far;
# share pruning relies on it.
TREND_DAYS = 7

# ledger model -> (signal kind, timestamp field)
SOURCES = {
    JokeReaction: (CommunitySignal.KIND_LIKE, 'updated_at'),
    Favorite: (CommunitySignal.KIND_FAVORITE, 'created_at'),
    SavedJoke: (CommunitySignal.KIND_SAVE, 'created_at'),
    ShareEvent: (CommunitySignal.KIND_SHARE, 'created_at'),
}


def _is_signal(instance):
    if isinstance(instance, JokeReaction):
        return instance.reaction in POSITIVE_REACTIONS
    if isinstance(instance, ShareEvent):
        return instance.user_id is not None  # anonymous shares never count
    return True


def _upsert(rows):
    CommunitySignal.objects.bulk_create(
        rows, update_conflicts=True, unique_fields=['kind', 'source_id'],
        update_fields=['user', 'joke', 'occurred_at'],
    )


def record(sender, instance, created=False):
    """Mirror one saved ledger row (or drop its mirror if it stopped being positive)."""
    kind, stamp = SOURCES[sender]
    if not _is_signal(instance):
        if not created:  # e.g. a reaction switched from 😂 to 🙄
            discard(sender, instance)
        return
    _upsert([CommunitySignal(user_id=instance.user_id, joke_id=instance.joke_id, kind=kind,
                             source_id=instance.pk, occurred_at=getattr(instance, stamp))])
    if kind == CommunitySignal.KIND_SHARE:
        prune_shares(instance.user_id, instance.joke_id)


def discard(sender, instance):
    """Drop the mirror of a deleted ledger row. Never inserts outside resyncing shares,
    so it is safe inside account and joke deletion cascades."""
    kind, _ = SOURCES[sender]
    CommunitySignal.objects.filter(kind=kind, source_id=instance.pk).delete()
    if kind == CommunitySignal.KIND_SHARE and instance.user_id is not None:
        # A pruned older share may matter again now that a newer one is gone.
        resync_shares(instance.user_id, instance.joke_id)


def prune_shares(user_id, joke_id, now=None):
    cutoff = (now or timezone.now()) - timedelta(days=TREND_DAYS)
    shares = CommunitySignal.objects.filter(user_id=user_id, joke_id=joke_id, kind=CommunitySignal.KIND_SHARE)
    anchor = (shares.filter(occurred_at__lte=cutoff).order_by('-occurred_at', '-pk')
              .values_list('pk', 'occurred_at').first())
    if anchor is not None:
        shares.filter(occurred_at__lte=anchor[1]).exclude(pk=anchor[0]).delete()


def resync_shares(user_id, joke_id):
    CommunitySignal.objects.filter(user_id=user_id, joke_id=joke_id, kind=CommunitySignal.KIND_SHARE).delete()
    rows = ShareEvent.objects.filter(user_id=user_id, joke_id=joke_id).values_list('pk', 'created_at')
    _upsert([CommunitySignal(user_id=user_id, joke_id=joke_id, kind=CommunitySignal.KIND_SHARE,
                             source_id=pk, occurred_at=at) for pk, at in rows])
    prune_shares(user_id, joke_id)


def _ledger_select():
    """One SELECT over the four ledgers yielding (user_id, joke_id, kind, source_id, occurred_at)."""
    reactions = ', '.join(f"'{value}'" for value in POSITIVE_REACTIONS)
    parts = []
    for model, (kind, stamp) in SOURCES.items():
        where = {
            JokeReaction: f'reaction IN ({reactions})',
            ShareEvent: 'user_id IS NOT NULL',
        }.get(model, 'TRUE')
        parts.append(f"SELECT user_id, joke_id, '{kind}', id, {stamp} FROM {model._meta.db_table} WHERE {where}")
    return ' UNION ALL '.join(parts)


def rebuild(now=None):
    """Recreate the whole mirror from the ledgers. Idempotent; returns the row count."""
    table = CommunitySignal._meta.db_table
    cutoff = (now or timezone.now()) - timedelta(days=TREND_DAYS)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f'DELETE FROM {table}')
        cursor.execute(f'INSERT INTO {table} (user_id, joke_id, kind, source_id, occurred_at) {_ledger_select()}')
        cursor.execute(
            f'''DELETE FROM {table} AS s USING (
                    SELECT user_id, joke_id, MAX(occurred_at) AS anchor FROM {table}
                    WHERE kind = %s AND occurred_at <= %s GROUP BY user_id, joke_id
                ) AS a
                WHERE s.kind = %s AND s.user_id = a.user_id AND s.joke_id = a.joke_id
                  AND s.occurred_at < a.anchor''',
            [CommunitySignal.KIND_SHARE, cutoff, CommunitySignal.KIND_SHARE],
        )
        cursor.execute(f'SELECT COUNT(*) FROM {table}')
        return cursor.fetchone()[0]
