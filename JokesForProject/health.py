"""Health and readiness probes for Cloud Run.

healthz — lightweight LIVENESS probe.
  Process-only check: a 200 means "don't recycle me". Never touches DB or
  cache. Coupling liveness to an external dependency would cause Cloud Run
  to mass-recycle all healthy instances on a transient Neon blip.

readyz — READINESS probe.
  Verifies that the app can actually serve traffic: performs a fast DB ping
  (SELECT 1) and a cache round-trip (set/get/delete on the jokesfor_cache
  table that DRF throttling depends on). Returns 200 {status: ready} or
  503 {status: not_ready} with a per-dependency breakdown.

Both are plain Django views (not DRF) so they bypass auth, versioning,
throttling, and the new RequestContextMiddleware.
"""
import logging
import os
import time

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

_health_logger = logging.getLogger('jokesfor.health')

# Revision / build identifier injected by Cloud Run (K_REVISION) or baked in
# at build time (GIT_SHA). Falls back to 'unknown' for local dev.
_VERSION = os.getenv('K_REVISION') or os.getenv('GIT_SHA') or 'unknown'


@csrf_exempt
def healthz(request):
    """Unauthenticated liveness probe — process-only, dependency-free.

    Plain Django view (not DRF) so it bypasses auth, versioning and throttling.
    A 200 means "the process is alive, don't recycle me". No DB/cache touch —
    those belong in readyz.
    """
    return JsonResponse({'status': 'ok'}, status=200)


@csrf_exempt
def readyz(request):
    """Unauthenticated readiness probe — verifies DB + cache availability.

    Returns 200 {status: ready, checks: {...}, version: ...} when all
    dependencies are reachable, or 503 {status: not_ready, ...} with a
    per-dependency breakdown when any check fails.

    Emits a structured 'jokesfor.health' INFO line on success (so deploys
    are visible in the log stream) and a WARNING on failure (filterable
    by Cloud Logging log-based metrics / alerts).
    """
    checks: dict = {}
    all_ok = True

    # ── DB check ──────────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
            cur.fetchone()
        checks['db'] = {
            'status': 'ok',
            'latency_ms': round((time.monotonic() - t0) * 1000, 2),
        }
    except Exception as exc:
        checks['db'] = {'status': 'error', 'error': str(exc)}
        all_ok = False

    # ── Cache check ───────────────────────────────────────────────────────────
    t1 = time.monotonic()
    _cache_key = '_readyz_probe'
    try:
        cache.set(_cache_key, '1', timeout=5)
        val = cache.get(_cache_key)
        cache.delete(_cache_key)
        if val != '1':
            raise ValueError('cache round-trip mismatch')
        checks['cache'] = {
            'status': 'ok',
            'latency_ms': round((time.monotonic() - t1) * 1000, 2),
        }
    except Exception as exc:
        checks['cache'] = {'status': 'error', 'error': str(exc)}
        all_ok = False

    payload = {
        'status': 'ready' if all_ok else 'not_ready',
        'checks': checks,
        'version': _VERSION,
    }

    if all_ok:
        _health_logger.info(
            'readyz ok',
            extra={'version': _VERSION, 'checks': checks},
        )
        return JsonResponse(payload, status=200)

    _health_logger.warning(
        'readyz failed',
        extra={'readiness_failed': True, 'checks': checks, 'version': _VERSION},
    )
    return JsonResponse(payload, status=503)
