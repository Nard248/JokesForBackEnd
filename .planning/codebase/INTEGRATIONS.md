# External Integrations

**Analysis Date:** 2026-01-11

## APIs & External Services

**Payment Processing:**
- Not detected

**Email/SMS:**
- Not detected

**External APIs:**
- Not detected

## Data Storage

**Databases:**
- SQLite3 - Local file-based development database
  - Connection: Configured in `JokesForProject/settings.py` lines 76-81
  - Client: Django ORM (built-in)
  - File: `db.sqlite3` (in project root, generated at runtime)

**File Storage:**
- Not detected

**Caching:**
- Not detected

## Authentication & Identity

**Auth Provider:**
- Django built-in authentication
  - Implementation: `django.contrib.auth` in `JokesForProject/settings.py`
  - Session management: Django sessions middleware

**OAuth Integrations:**
- Not detected

## Monitoring & Observability

**Error Tracking:**
- Not detected

**Analytics:**
- Not detected

**Logs:**
- None configured (stdout only)

## CI/CD & Deployment

**Hosting:**
- Not configured

**CI Pipeline:**
- Not detected (no `.github/workflows/`, `Jenkinsfile`, `.travis.yml`)

## Environment Configuration

**Development:**
- Required env vars: None currently required
- Secrets location: Hardcoded in `JokesForProject/settings.py` (needs improvement)
- Mock/stub services: None

**Staging:**
- Not configured

**Production:**
- Not configured

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None

---

*Integration audit: 2026-01-11*
*Update when adding/removing external services*
