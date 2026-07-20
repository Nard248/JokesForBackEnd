"""Per-format validation rules for creator joke submissions.

Single source of truth for which fields are required, forbidden, or
constrained per joke format. Consumed by JokeSubmissionCreateSerializer
(for write-time validation) and FormatSerializer (for read-time schema
disclosure to the creator editor).
"""

FORMAT_RULES = {
    'oneliner': {
        'required':  ['text'],
        'forbidden': ['setup', 'punchline', 'lines'],
    },
    'setup': {
        'required':  ['setup', 'punchline'],
        'forbidden': ['text', 'lines'],
    },
    'knock': {
        'required':  ['lines'],
        'forbidden': ['text', 'setup', 'punchline'],
        'constraints': {
            'min_lines': 4,
            'max_lines': 8,
            'max_line_chars': 200,
        },
    },
    'story': {
        'required':  ['text'],
        'forbidden': ['setup', 'punchline', 'lines'],
        'constraints': {
            'min_text_words': 30,
        },
    },
    'anti': {
        'required':  ['setup', 'punchline'],
        'forbidden': ['text', 'lines'],
    },
    'observ': {
        'required':  ['text'],
        'forbidden': ['setup', 'punchline', 'lines'],
    },
    'image': {
        'required':  ['setup', 'media'],
        'forbidden': ['punchline', 'lines'],
        'constraints': {
            'media_kind': 'image',
            'min_media': 1,
            'max_media': 6,
        },
    },
}


def _is_blank(value):
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def validate_per_format(format_slug, attrs):
    """Validate `attrs` against the rule for `format_slug`.

    Returns a dict mapping field name -> error message. Empty dict means
    valid. Unknown format slugs return `{'format': '...'}`.
    """
    rule = FORMAT_RULES.get(format_slug)
    if rule is None:
        return {'format': f"Unknown format slug '{format_slug}'."}

    errors = {}

    for field in rule['required']:
        if _is_blank(attrs.get(field)):
            errors[field] = f"This field is required for {format_slug} format."

    # A blank value (None / '' / []) for a forbidden field is treated as
    # "not provided" and silently passes. Callers that send explicit blanks
    # (e.g. a serializer clearing a field on PATCH) won't be tripped up.
    for field in rule.get('forbidden', []):
        if field in errors:
            continue
        if not _is_blank(attrs.get(field)):
            errors[field] = f"Not allowed for {format_slug} format."

    constraints = rule.get('constraints', {})

    if {'min_lines', 'max_lines', 'max_line_chars'} & constraints.keys():
        lines = attrs.get('lines')
        if lines is not None and 'lines' not in errors:
            if not isinstance(lines, list):
                errors['lines'] = "Must be a list of strings."
            else:
                min_lines = constraints.get('min_lines')
                max_lines = constraints.get('max_lines')
                max_line_chars = constraints.get('max_line_chars')
                if min_lines is not None and len(lines) < min_lines:
                    errors['lines'] = (
                        f"{format_slug.capitalize()} format requires at least "
                        f"{min_lines} lines."
                    )
                elif max_lines is not None and len(lines) > max_lines:
                    errors['lines'] = (
                        f"{format_slug.capitalize()} format allows at most "
                        f"{max_lines} lines."
                    )
                else:
                    for i, line in enumerate(lines):
                        if not isinstance(line, str) or not line.strip():
                            errors['lines'] = (
                                f"Line {i + 1} must be a non-empty string."
                            )
                            break
                        if max_line_chars is not None and len(line) > max_line_chars:
                            errors['lines'] = (
                                f"Line {i + 1} exceeds {max_line_chars} "
                                "character limit."
                            )
                            break

    if 'min_text_words' in constraints and 'text' not in errors:
        text = attrs.get('text') or ''
        min_words = constraints['min_text_words']
        if len(text.split()) < min_words:
            errors['text'] = (
                f"{format_slug.capitalize()} must be at least {min_words} words."
            )

    if {'media_kind', 'min_media', 'max_media'} & constraints.keys():
        media = attrs.get('media') or []
        if 'media' not in errors:
            min_media = constraints.get('min_media')
            max_media = constraints.get('max_media')
            media_kind = constraints.get('media_kind')
            if min_media is not None and len(media) < min_media:
                errors['media'] = (
                    f"{format_slug.capitalize()} format requires at least "
                    f"{min_media} media attachment(s)."
                )
            elif max_media is not None and len(media) > max_media:
                errors['media'] = (
                    f"{format_slug.capitalize()} format allows at most "
                    f"{max_media} media attachment(s)."
                )
            elif media_kind is not None and any(k != media_kind for k in media):
                errors['media'] = (
                    f"All attachments must be {media_kind} for "
                    f"{format_slug} format."
                )

    return errors
