"""Sentry before_send hook for PII scrubbing.

Factored into its own module so it can be unit-tested without a real DSN.
Applied as the before_send callback in settings.py inside the SENTRY_DSN guard.
"""
from JokesForProject.observability.redaction import redact_mapping


def scrub_event(event: dict, hint: dict | None) -> dict:
    """Scrub PII and secrets from a Sentry event before it is transmitted.

    Applies redact_mapping to request.headers, request.cookies, request.data,
    and the top-level extra dict. This is a defense-in-depth measure: Sentry's
    send_default_pii=False already omits user PII, but JWT cookies and the
    verification 'code' can leak via the request body even with that flag off.

    Returns the (mutated) event unchanged in structure so Sentry can still
    group and display it.
    """
    request = event.get('request', {})
    if request:
        if 'headers' in request:
            request['headers'] = redact_mapping(request['headers'])
        if 'cookies' in request:
            request['cookies'] = redact_mapping(request['cookies'])
        if 'data' in request:
            request['data'] = redact_mapping(request['data'])

    if 'extra' in event:
        event['extra'] = redact_mapping(event['extra'])

    return event
