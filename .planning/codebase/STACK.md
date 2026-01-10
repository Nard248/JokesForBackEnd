# Technology Stack

**Analysis Date:** 2026-01-11

## Languages

**Primary:**
- Python 3.11 - All application code

**Secondary:**
- None detected

## Runtime

**Environment:**
- Python 3.11.0
- Virtual environment at `.venv/`

**Package Manager:**
- pip 24.3.1
- No lockfile (requirements.txt missing)

## Frameworks

**Core:**
- Django 5.2.10 - Web framework

**Testing:**
- None configured

**Build/Dev:**
- Django's built-in development server

## Key Dependencies

**Critical:**
- Django 5.2.10 - Web framework, admin, auth, ORM
- asgiref 3.11.0 - ASGI adapter for async support
- sqlparse 0.5.5 - SQL parsing for Django

**Infrastructure:**
- SQLite3 - Default database (built into Python)

## Configuration

**Environment:**
- No .env files detected
- Configuration via `JokesForProject/settings.py`
- Environment variable: `DJANGO_SETTINGS_MODULE=JokesForProject.settings`

**Build:**
- No build configuration (Django project, no compilation needed)

## Platform Requirements

**Development:**
- macOS/Linux/Windows (any platform with Python 3.11+)
- No external dependencies beyond Python

**Production:**
- WSGI server (Gunicorn, uWSGI) via `JokesForProject/wsgi.py`
- ASGI server (Daphne, Hypercorn) via `JokesForProject/asgi.py`
- Production database (PostgreSQL/MySQL recommended)

---

*Stack analysis: 2026-01-11*
*Update after major dependency changes*
