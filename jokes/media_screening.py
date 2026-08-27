"""Automated media pre-screening (spec §7): Vision SafeSearch + a dormant
CSAM hash-matcher seam.

SafeSearch runs in-request at upload. Blocking policy: adult or violence at
LIKELY or above hard-blocks; everything else is stored on the asset and
surfaced to the human reviewer (racy/medical/spoof inform, never block).

The HashMatcher interface ships with a NullMatcher: every vendor (PhotoDNA,
NCMEC, Thorn Safer) needs owner-side onboarding paperwork before activation.
When credentials exist, implement HashMatcher and swap it in get_matcher() —
the upload view, audit actions, and schema are already wired (spec §7.3).
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_LIKELIHOOD_ORDER = [
    'UNKNOWN', 'VERY_UNLIKELY', 'UNLIKELY', 'POSSIBLE', 'LIKELY', 'VERY_LIKELY',
]
_BLOCK_AT = _LIKELIHOOD_ORDER.index('LIKELY')
_BLOCK_CATEGORIES = ('adult', 'violence')
_REPORT_CATEGORIES = ('adult', 'violence', 'racy', 'medical', 'spoof')


def _client():
    from google.cloud import vision
    return vision.ImageAnnotatorClient()


def screen_image(image_bytes):
    """Return a verdict dict for one image. {'status': 'skipped'} when the
    screen is disabled (local dev / flag off) — the human review queue is
    still the publish gate either way."""
    if not getattr(settings, 'SAFESEARCH_ENABLED', False):
        return {'status': 'skipped'}

    from google.cloud import vision
    try:
        response = _client().safe_search_detection(
            image=vision.Image(content=image_bytes)
        )
    except Exception as exc:
        # A THROWN client failure (grpc PERMISSION_DENIED, quota, network,
        # auth) must follow the same fail-open policy as an in-response
        # error: never hard-fail the upload on infrastructure — the human
        # review queue remains the publish gate. Without this, every
        # image/video upload 500s the moment Vision hiccups.
        logger.warning(
            'SafeSearch client call failed: %s', str(exc)[:300],
            extra={'safesearch_failed': True},
        )
        return {'status': 'error', 'detail': str(exc)[:200]}
    if getattr(response.error, 'message', ''):
        # Vision API failure: don't hard-fail the upload on infrastructure —
        # record the failure; the human reviewer remains the gate.
        #
        # Logged at WARNING with the same 'SafeSearch' marker as the thrown-
        # failure path above so a single log-based metric alerts on both. This
        # path used to return silently, which made a dead NSFW/CSAM screen
        # indistinguishable from a clean pass for as long as it stayed broken.
        logger.warning(
            'SafeSearch response carried an error: %s',
            response.error.message,
            extra={'safesearch_failed': True},
        )
        return {'status': 'error', 'detail': response.error.message}

    ann = response.safe_search_annotation
    verdict = {cat: getattr(ann, cat).name for cat in _REPORT_CATEGORIES}
    blocked = any(
        _LIKELIHOOD_ORDER.index(verdict[cat]) >= _BLOCK_AT
        for cat in _BLOCK_CATEGORIES
        if verdict[cat] in _LIKELIHOOD_ORDER
    )
    verdict['status'] = 'blocked' if blocked else 'ok'
    return verdict


class HashMatcher:
    """CSAM hash-match seam. match() returns None for no-hit, or a dict
    describing the hit (vendor payload) — a truthy return blocks the upload
    and records a hash_match_hit audit."""

    def match(self, phash):
        raise NotImplementedError


class NullMatcher(HashMatcher):
    """Dormant default until a vendor is onboarded (owner action)."""

    def match(self, phash):
        return None


def get_matcher():
    return NullMatcher()
