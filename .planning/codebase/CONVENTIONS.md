# Coding Conventions

**Analysis Date:** 2026-01-11

## Naming Patterns

**Files:**
- snake_case for all Python files: `settings.py`, `urls.py`, `manage.py`
- Standard Django naming for entry points: `wsgi.py`, `asgi.py`

**Functions:**
- snake_case: `main()` in `manage.py`
- Descriptive names: `execute_from_command_line()`

**Variables:**
- UPPER_SNAKE_CASE for constants/settings: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `BASE_DIR`
- snake_case for regular variables

**Types:**
- Not applicable (no type hints in current codebase)

## Code Style

**Formatting:**
- 4-space indentation (PEP 8 standard)
- No explicit formatter configured
- Line length appears reasonable (no violations)

**Quotes:**
- Single quotes for strings: `'django.contrib.admin'`
- Triple double-quotes for docstrings: `"""Django's command-line utility..."""`

**Semicolons:**
- Not used (Python convention)

**Linting:**
- Not configured (no .flake8, .pylintrc, pyproject.toml)

## Import Organization

**Order (observed in `manage.py`):**
1. Standard library imports: `import os`, `import sys`
2. Third-party imports: `from django.core.management import...`
3. Local imports: None yet

**Grouping:**
- Blank line between groups
- Standard imports first, then Django imports

**Path Aliases:**
- Not used

## Error Handling

**Patterns:**
- try/except with specific exceptions in `manage.py`
- Informative error messages with suggestions

**Error Types:**
- ImportError handling for Django setup
- Django's default exception handling elsewhere

## Logging

**Framework:**
- Not configured (Django defaults)

**Patterns:**
- Not established yet

## Comments

**When to Comment:**
- Django-generated comments explain configuration options
- Section headers for settings groups

**Docstrings:**
- Module-level docstrings present: `manage.py`, `settings.py`
- Function docstrings: `main()` has `"""Run administrative tasks."""`

**Style:**
- Hash (#) followed by single space
- Contextual comments for Django configuration

**TODO Comments:**
- None found in current codebase

## Function Design

**Size:**
- Small functions observed (main() is ~15 lines)

**Parameters:**
- No complex functions to analyze yet

**Return Values:**
- No custom functions to analyze yet

## Module Design

**Exports:**
- Standard Django patterns
- WSGI/ASGI expose `application` variable

**Barrel Files:**
- `__init__.py` files are empty (standard for Django)

---

*Convention analysis: 2026-01-11*
*Update when patterns change*
