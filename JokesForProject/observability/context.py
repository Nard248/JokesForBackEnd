"""Request-scoped contextvars for correlation IDs and per-request DB counters.

gunicorn gthread reuses OS threads across requests, so ContextVar is the
correct primitive — both thread-safe and async-safe. All vars MUST be reset
in a finally block (see RequestContextMiddleware) or values leak across
requests on the same worker thread.
"""
import contextvars

# Core request correlation
request_id_var: contextvars.ContextVar = contextvars.ContextVar('request_id', default=None)
trace_var: contextvars.ContextVar = contextvars.ContextVar('trace', default=None)
span_var: contextvars.ContextVar = contextvars.ContextVar('span', default=None)
user_id_var: contextvars.ContextVar = contextvars.ContextVar('user_id', default=None)
sampled_var: contextvars.ContextVar = contextvars.ContextVar('sampled', default=None)

# Per-request DB instrumentation (incremented by the execute_wrapper in
# RequestContextMiddleware; works with DEBUG=False)
db_count_var: contextvars.ContextVar = contextvars.ContextVar('db_count', default=0)
db_time_var: contextvars.ContextVar = contextvars.ContextVar('db_time', default=0.0)

_VARS: dict = {
    'request_id': request_id_var,
    'trace': trace_var,
    'span': span_var,
    'user_id': user_id_var,
    'sampled': sampled_var,
}


def bind_request_context(**kw) -> dict:
    """Set correlation contextvars and return a dict of reset tokens.

    Only recognises keys present in _VARS; unknown keys are silently ignored.
    Pass the returned token dict to clear_request_context() in a finally block.
    """
    return {k: _VARS[k].set(v) for k, v in kw.items() if k in _VARS}


def clear_request_context(tokens: dict | None) -> None:
    """Reset each contextvar to its default using the supplied tokens.

    Safe to call with None or an empty dict (no-op). Must be called in a
    finally block to prevent value leakage across reused gthread worker threads.
    """
    for k, tok in (tokens or {}).items():
        try:
            _VARS[k].reset(tok)
        except (LookupError, ValueError):
            pass


def get_log_fields() -> dict:
    """Return a dict of currently-bound, non-None correlation values.

    Used by GoogleCloudJsonFormatter to merge request context into every log
    line automatically.
    """
    return {k: v.get() for k, v in _VARS.items() if v.get() is not None}


# ── DB stats helpers ────────────────────────────────────────────────────────

def reset_db_stats() -> None:
    """Zero the per-request DB query counter and accumulated time."""
    db_count_var.set(0)
    db_time_var.set(0.0)


def add_db_query(duration_ms: float) -> None:
    """Increment query counter and accumulate duration (milliseconds)."""
    db_count_var.set(db_count_var.get() + 1)
    db_time_var.set(db_time_var.get() + duration_ms)


def get_db_stats() -> dict:
    """Return {'db_query_count': int, 'db_time_ms': float} for the current request."""
    return {
        'db_query_count': db_count_var.get(),
        'db_time_ms': round(db_time_var.get(), 2),
    }
