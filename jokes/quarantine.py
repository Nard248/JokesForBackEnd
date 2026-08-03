"""Lazy expiry for quarantined media (Appeals wave, Task 2).

No cron exists in this single-app deployment, so quarantined assets whose
14-day appeal window has lapsed are purged the next time this module
function runs — piggybacked on other request-triggered sweeps (the upload
path's orphan sweep today; the appeal-create endpoint in Task 3).
"""
from datetime import timedelta

from django.utils import timezone

from .models import Appeal, MediaAsset


def purge_lapsed_quarantine():
    """Hard-delete every quarantined MediaAsset whose quarantine window
    (14 days) has lapsed AND whose linked joke(s) have no OPEN (pending)
    appeal AND are all still removed. Assets tied to a joke with an open
    appeal are left alone (purging them would make the appeal un-reversible);
    assets linked to a LIVE (non-removed) joke are left alone too — a
    restore that failed to release, or a re-share, must never let this sweep
    destroy a serving joke's media (mirrors take_down_joke's still_shared
    predicate). Audits `media_purged` once per purge batch (not per asset)."""
    from audit.services import record_audit

    cutoff = timezone.now() - timedelta(days=14)
    candidates = MediaAsset.objects.filter(
        quarantined_at__isnull=False, quarantined_at__lt=cutoff,
    )
    open_appeal_joke_ids = set(
        Appeal.objects.filter(status='pending', joke__isnull=False)
        .values_list('joke_id', flat=True)
    )
    purged_ids = []
    for asset in candidates:
        joke_ids = set(asset.joke_links.values_list('joke_id', flat=True))
        if joke_ids & open_appeal_joke_ids:
            continue
        # Live-joke guard: never purge media a non-removed joke still links.
        if asset.joke_links.filter(joke__is_removed=False).exists():
            continue
        purged_ids.append(asset.pk)
        asset.purge()
    if purged_ids:
        record_audit(
            None, 'media_purged', outcome='success',
            target_type='media_asset',
            target_id=','.join(sorted(str(i) for i in purged_ids)),
        )
