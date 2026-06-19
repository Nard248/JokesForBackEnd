"""Request-context and access-log middlewares.

WHY NO OPENTELEMETRY:
  OTel BatchSpanProcessor uses a background worker thread that Cloud Run's
  between-request CPU throttling starves (spans buffer and can't flush),
  violating the project's HARD no-worker constraint.  SimpleSpanProcessor
  exports each span synchronously in-band — a blocking Cloud Trace API call
  per request that hits rate limits under load.  Instead, we parse the
  X-Cloud-Trace-Context header Cloud Run already injects, propagate the
  trace_id into structured logs via the 'logging.googleapis.com/trace' key,
  and let Cloud Run / Cloud Logging build the trace timeline for free.
  ZERO new runtime deps; ZERO added per-request network calls.
  (If a future dev ever reintroduces OTel BatchSpanProcessor, traces will
  silently drop on Cloud Run — this comment is the regression guard.)
"""
import logging
import re
import time
import uuid

from django.db import connection

from JokesForProject.observability.context import (
    bind_request_context,
    clear_request_context,
    reset_db_stats,
    add_db_query,
    get_db_stats,
    get_log_fields,
)
from JokesForProject.observability.redaction import mask_ip

_access_logger = logging.getLogger('jokesfor.access')

# 32-hex trace-id validator (prevents log injection via a crafted header)
_TRACE_RE = re.compile(r'^[0-9a-fA-F]{32}$')

# Health / readiness paths — logged at DEBUG (suppress from INFO-level streams)
_QUIET_PATHS = frozenset({'/healthz', '/readyz'})


class RequestContextMiddleware:
    """Bind request-id and Cloud Trace correlation into contextvars.

    Placed immediately after WhiteNoise in MIDDLEWARE so the request_id and
    trace_id are available to every inner middleware and view log line.

    user_id is bound LAZILY after get_response returns (AuthenticationMiddleware
    runs during get_response, so request.user is populated only post-view).

    All contextvars are reset in a finally block to prevent value leakage
    across reused gunicorn gthread worker threads.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ── Generate / propagate request id ──────────────────────────────────
        rid = request.META.get('HTTP_X_REQUEST_ID') or uuid.uuid4().hex
        request.request_id = rid

        # ── Parse X-Cloud-Trace-Context (Cloud Run sets this automatically) ──
        trace_header = request.META.get('HTTP_X_CLOUD_TRACE_CONTEXT', '')
        trace = span = sampled = None
        if trace_header:
            try:
                # Format: TRACE_ID/SPAN_ID;o=SAMPLED
                main, _, flags = trace_header.partition(';')
                raw_trace, _, raw_span = main.partition('/')
                # Validate 32-hex before using (prevents log injection)
                if _TRACE_RE.match(raw_trace):
                    trace = raw_trace
                    span = raw_span or None
                    sampled = (flags == 'o=1')
            except Exception:
                pass  # Malformed header — fall through with no trace

        # ── Bind contextvars (reset in finally to prevent thread-reuse leaks) ─
        bind_kw = {'request_id': rid}
        if trace:
            bind_kw['trace'] = trace
        if span:
            bind_kw['span'] = span
        if sampled is not None:
            bind_kw['sampled'] = sampled

        tokens = bind_request_context(**bind_kw)
        reset_db_stats()

        # ── Install per-request DB query counter ─────────────────────────────
        def _db_wrapper(execute, sql, params, many, context):
            t0 = time.perf_counter()
            try:
                return execute(sql, params, many, context)
            finally:
                add_db_query((time.perf_counter() - t0) * 1000)

        try:
            with connection.execute_wrapper(_db_wrapper):
                response = self.get_response(request)

            # ── Lazy user_id bind (AuthenticationMiddleware has run by now) ──
            try:
                uid = getattr(request, 'user', None)
                if uid and uid.is_authenticated:
                    user_tokens = bind_request_context(user_id=uid.pk)
                    tokens.update(user_tokens)
            except Exception:
                pass

            # Echo request-id to the client so they can report it
            response['X-Request-ID'] = rid

            # ── Optional Sentry tag (no-op when DSN unset) ───────────────────
            try:
                import sentry_sdk
                client = sentry_sdk.get_client()
                if getattr(client, 'is_active', lambda: False)():
                    sentry_sdk.set_tag('request_id', rid)
                    if trace:
                        sentry_sdk.set_tag('cloud_trace_id', trace)
            except Exception:
                pass

            return response

        finally:
            clear_request_context(tokens)
            reset_db_stats()


class AccessLogMiddleware:
    """Emit one structured 'jokesfor.access' log line per request.

    Severity: >=500 ERROR, >=400 WARNING, else INFO.
    Probe paths (/healthz, /readyz) are logged at DEBUG so they don't flood
    INFO-level log streams with Cloud Run's constant liveness checks.

    The formatter merges contextvars (request_id, trace, user_id) so the
    line is fully self-contained even when emitted from this outer middleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        latency_ms = round((time.monotonic() - start) * 1000, 2)

        status = response.status_code
        path = request.path

        # Route template (lower cardinality than raw path for log-based metrics)
        route = path
        try:
            if request.resolver_match:
                route = request.resolver_match.route or path
        except Exception:
            pass

        # Masked client IP from X-Forwarded-For first hop
        client_ip = None
        try:
            xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
            raw_ip = xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')
            if raw_ip:
                client_ip = mask_ip(raw_ip)
        except Exception:
            pass

        # Choose log level by status (and suppress probe paths at INFO)
        if path in _QUIET_PATHS:
            level = logging.DEBUG
        elif status >= 500:
            level = logging.ERROR
        elif status >= 400:
            level = logging.WARNING
        else:
            level = logging.INFO

        db_stats = get_db_stats()
        fields = get_log_fields()

        _access_logger.log(
            level,
            'request',
            extra={
                'method': request.method,
                'path': path,
                'route': route,
                'status': status,
                'latency_ms': latency_ms,
                'client_ip': client_ip,
                'user_id': fields.get('user_id'),
                'request_id': fields.get('request_id'),
                **db_stats,
            },
        )

        return response
