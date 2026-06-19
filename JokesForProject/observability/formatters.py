"""Cloud Logging JSON formatter + plain dev formatter.

GoogleCloudJsonFormatter emits a single-line JSON object per log record with
Cloud Logging magic keys:

  severity              — maps Python level to Cloud severity
  message               — record.getMessage()
  timestamp             — ISO 8601 UTC (from record.created)
  logging.googleapis.com/trace  — 'projects/<PROJECT>/traces/<32hex>'
                                   (only when a valid trace is bound)
  logging.googleapis.com/spanId — span id from contextvars (when bound)
  logging.googleapis.com/sourceLocation — {file, line, function}

Additionally, get_log_fields() (request_id, user_id, etc.) are merged at the
top level so Cloud Run auto-indexes them into jsonPayload.

The trace resource name format is load-bearing: it is exactly what makes log
entries in Cloud Logging clickable through to the matching Cloud Trace span.
"""
import json
import logging
import re
from datetime import datetime, timezone

# Standard LogRecord attributes that should NOT be copied as extras
_STANDARD_ATTRS = frozenset({
    'args', 'created', 'exc_info', 'exc_text', 'filename', 'funcName',
    'levelname', 'levelno', 'lineno', 'message', 'module', 'msecs', 'msg',
    'name', 'pathname', 'process', 'processName', 'relativeCreated',
    'stack_info', 'thread', 'threadName', 'taskName',
})

# Cloud Logging severity mapping
_SEVERITY: dict = {
    logging.DEBUG: 'DEBUG',
    logging.INFO: 'INFO',
    logging.WARNING: 'WARNING',
    logging.ERROR: 'ERROR',
    logging.CRITICAL: 'CRITICAL',
}

# 32-hex trace-id validator (prevents log injection)
_TRACE_RE = re.compile(r'^[0-9a-fA-F]{32}$')


class GoogleCloudJsonFormatter(logging.Formatter):
    """One-line JSON formatter for Cloud Logging / Cloud Run stdout.

    Reads GOOGLE_CLOUD_PROJECT lazily from django.conf.settings inside format()
    to avoid import-time settings access (safe during settings.py loading).
    """

    def format(self, record: logging.LogRecord) -> str:
        # Lazy import to avoid triggering Django setup at import time
        try:
            from django.conf import settings as _settings
            project_id = getattr(_settings, 'GOOGLE_CLOUD_PROJECT', '')
        except Exception:
            project_id = ''

        from JokesForProject.observability.context import get_log_fields

        # Build the base payload
        payload: dict = {
            'severity': _SEVERITY.get(record.levelno, 'DEFAULT'),
            'message': record.getMessage(),
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'sourceLocation': {
                'file': record.pathname,
                'line': record.lineno,
                'function': record.funcName,
            },
        }

        # Merge request-context fields (request_id, user_id, trace, span, sampled)
        payload.update(get_log_fields())

        # Cloud Logging trace + span linkage (load-bearing for trace correlation)
        trace = payload.pop('trace', None)
        span = payload.pop('span', None)
        payload.pop('sampled', None)  # Not a Cloud Logging magic field

        if trace and _TRACE_RE.match(trace) and project_id:
            payload['logging.googleapis.com/trace'] = (
                f'projects/{project_id}/traces/{trace}'
            )
        if span:
            payload['logging.googleapis.com/spanId'] = span

        # Extra fields set on the record (e.g. via logger.info('x', extra={...}))
        for key, val in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith('_'):
                payload.setdefault(key, val)

        # Exception traceback — included so Error Reporting can group events
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
            record.exc_info = None  # Prevent the base class from appending it

        return json.dumps(payload, default=str)


class PlainFormatter(logging.Formatter):
    """Human-readable formatter for local development (DEBUG=True)."""

    def __init__(self):
        super().__init__(
            fmt='%(asctime)s %(levelname)-8s %(name)s  %(message)s',
            datefmt='%H:%M:%S',
        )
