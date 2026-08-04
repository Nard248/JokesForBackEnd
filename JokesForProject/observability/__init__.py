# Observability package — structured logging, request-context correlation,
# PII redaction, and Cloud Logging JSON formatting for the JokesFor backend.
#
# Import-light: no Django app loading at module level so settings.py can
# import the formatter at configuration time.
from JokesForProject.observability.context import (
    add_db_query,
    bind_request_context,
    clear_request_context,
    get_db_stats,
    get_log_fields,
    reset_db_stats,
)

__all__ = [
    'bind_request_context',
    'clear_request_context',
    'get_log_fields',
    'reset_db_stats',
    'add_db_query',
    'get_db_stats',
]
