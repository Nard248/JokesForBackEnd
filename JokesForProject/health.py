from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def healthz(request):
    """Unauthenticated liveness probe for Cloud Run.

    Plain Django view (not DRF) so it bypasses auth, versioning and throttling.
    Does a light DB ping so the probe also surfaces a dead DB pool; returns 503
    in that case so Cloud Run recycles the instance.
    """
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
            cur.fetchone()
    except Exception:
        return JsonResponse({'status': 'db_error'}, status=503)
    return JsonResponse({'status': 'ok'}, status=200)
