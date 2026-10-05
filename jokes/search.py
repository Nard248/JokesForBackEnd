"""Input rules shared by the search API and internal search callers."""

import re
import unicodedata

from rest_framework.exceptions import ValidationError

MAX_SEARCH_QUERY_LENGTH = 200
MAX_SEARCH_TERMS = 32


def normalize_search_query(query_text):
    """Bound work before PostgreSQL parses the preserved websearch expression."""
    if query_text is None:
        return ''
    if not isinstance(query_text, str):
        raise ValidationError({'q': 'Enter a text search query.'})
    # Tabs/newlines are harmless whitespace; reject NUL and other controls
    # before passing strings to the DB driver. Preserve non-Latin text/joiners.
    if any(unicodedata.category(char) == 'Cc' and char not in '\t\r\n' for char in query_text):
        raise ValidationError({'q': 'Search contains an unsupported control character.'})
    if len(query_text) > MAX_SEARCH_QUERY_LENGTH:
        raise ValidationError({'q': f'Use at most {MAX_SEARCH_QUERY_LENGTH} characters.'})
    normalized = ' '.join(query_text.split())
    if len(re.findall(r'\w+', normalized, flags=re.UNICODE)) > MAX_SEARCH_TERMS:
        raise ValidationError({'q': f'Use at most {MAX_SEARCH_TERMS} search terms.'})
    return normalized
