"""Side effects every publish/unpublish path must apply.

Admin editorial actions, the corpus importer and moderation takedowns change
visibility with bulk ``update()`` calls, which bypass model signals. Read paths
are gated by ``JokeManager`` / ``live_joke_q``, so content stops serving at
once; these helpers close the two places that are not read-gated:

* derived aggregates — the cached community aggregate is refreshed after the
  transaction commits (the once-a-day released counts stay frozen by design);
* the share card — a separately stored PNG at a guessable path that would keep
  serving an unpublished joke's image.
"""
import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def visibility_changed():
    """Refresh cached community state once the surrounding transaction commits."""
    from communities import services

    transaction.on_commit(services.invalidate)


def blank_share_cards(jokes):
    """Delete stored share cards for jokes that are no longer public.

    Per-item isolation: one storage failure must not stop the rest. Returns the
    ids whose file could not be deleted (their field is left pointing at the
    file so a retry can find it).
    """
    failed = []
    for joke in jokes:
        if not joke.share_image:
            continue
        try:
            joke.share_image.delete(save=False)
        except Exception:
            logger.warning('share_card_delete_failed', extra={'joke_id': joke.pk})
            failed.append(joke.pk)
            continue
        type(joke).all_objects.filter(pk=joke.pk).update(share_image='')
    return failed
