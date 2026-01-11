# Project State

## Current Status

**Project:** Jokes For
**Milestone:** 1 - MVP Launch
**Phase:** 06 - Authentication (IN PROGRESS)
**Status:** Phase 06-02 complete, auth endpoints configured, migrations applied

---

## Quick Context

Jokes For is a global humor discovery platform - a search engine for jokes. Users find personalized jokes by age, culture, language, tone, and context. MVP focuses on search, daily joke, collections, and sharing features.

**Tech Stack:**
- Backend: Django 5.x + DRF + PostgreSQL
- Frontend: React + Vite (at `/Users/narekmeloyan/WebstormProjects/`)
- Auth: JWT with Google OAuth

---

## Progress

### Completed
- [x] Project initialized
- [x] Codebase mapped
- [x] PROJECT.md created
- [x] ROADMAP.md created (12 phases)
- [x] Phase directories created
- [x] **Phase 01: Foundation COMPLETE**
- [x] **Phase 02: Data Models COMPLETE**
- [x] **Phase 03: Content Seeding COMPLETE**
- [x] **Phase 04: Search Engine COMPLETE**
- [x] **05-01**: DRF setup (djangorestframework, drf-spectacular, django-cors-headers, serializers)
- [x] **05-02**: API viewsets and routing (JokeViewSet, lookup viewsets, /api/v1/, /api/docs/)
- [x] **Phase 05: API Core COMPLETE**
- [x] **06-01**: Authentication setup (dj-rest-auth, simplejwt, allauth, JWT settings)
- [x] **06-02**: Auth endpoints and migrations (URL routing, GoogleLogin view, database setup)

### Current Phase
**Phase 06: Authentication** - IN PROGRESS (2/? plans done)

### Upcoming
1. Complete Phase 06: Any remaining auth tasks
2. Phase 07: User Preferences
3. Phase 08: Collections

---

## Blockers

None currently.

---

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-11 | React + Vite over Next.js | Simpler setup, avoids SSR complexity, user preference |
| 2026-01-11 | PostgreSQL full-text search | Built-in, free, sufficient for MVP scale |
| 2026-01-11 | Web-only MVP | Reduce scope, prove retention before mobile |
| 2026-01-11 | English-first | Humor doesn't translate; prove product first |
| 2026-01-11 | 100-200 jokes for dev | Sufficient for testing, scale to 5k+ for launch |
| 2026-01-11 | PROTECT on_delete for required FKs | Prevents accidental deletion of referenced lookup data |
| 2026-01-11 | Slugs on all lookup tables | URL-friendly identifiers for API filtering |
| 2026-01-11 | Explicit PKs in fixtures | Deterministic FK references for reproducible seeding |
| 2026-01-11 | Management command for jokes | Better M2M handling than loaddata |
| 2026-01-11 | PageNumberPagination with 20 per page | Simple, frontend-friendly, good balance |
| 2026-01-11 | URL path versioning (/v1/) | Explicit versioning, easy to manage |
| 2026-01-11 | Throttle 100/hr anon, 1000/hr user | Conservative start, adjustable |
| 2026-01-11 | joke_format param instead of format | Avoid DRF content negotiation conflict |
| 2026-01-11 | HttpOnly cookies for JWT storage | XSS protection vs localStorage |
| 2026-01-11 | 15min access, 1day refresh tokens | Short-lived access with rotation limits breach impact |
| 2026-01-11 | Email-only login (no username) | Simpler UX, matches PROJECT.md requirement |

---

## Active Issues

None tracked yet.

---

## Session Notes

**2026-01-11 (afternoon):**
- Executed 06-01-PLAN.md (Authentication Setup)
- Installed dj-rest-auth 7.0.2, djangorestframework-simplejwt 5.5.1, django-allauth 65.13.1
- Configured JWT auth with HttpOnly cookies, refresh rotation, token blacklisting
- Set up email-based login with Google OAuth provider
- Updated allauth settings to non-deprecated format (ACCOUNT_LOGIN_METHODS, ACCOUNT_SIGNUP_FIELDS)
- **Phase 06: Plan 01 COMPLETE**

**2026-01-11 (late evening):**
- Executed 05-02-PLAN.md (API Viewsets and Routing)
- Created JokeViewSet with list/retrieve/random actions and search integration
- Built 6 lookup viewsets for reference data
- Configured URL routing at /api/v1/ with DRF DefaultRouter
- Added Swagger UI at /api/docs/ and ReDoc at /api/redoc/
- Fixed format param conflict by renaming to joke_format
- **Phase 05: API Core COMPLETE**

**2026-01-11 (late evening):**
- Executed 05-01-PLAN.md (DRF Setup)
- Installed djangorestframework 3.16.1, drf-spectacular 0.29.0, django-cors-headers 4.9.0
- Configured REST_FRAMEWORK with pagination, throttling, versioning, OpenAPI
- Created 9 serializers for all models (7 lookup + JokeSerializer + JokeListSerializer)
- **Phase 05: Plan 01 COMPLETE**

**2026-01-11 (evening):**
- Executed 04-01-PLAN.md (Search Infrastructure)
- Added django-pgtrigger for automatic search vector updates
- Created SearchVectorField with GIN index on Joke model
- Built JokeManager.search() with full-text search and filter support
- Backfilled search vectors for all 137 jokes
- **Phase 04: Search Engine COMPLETE**

**2026-01-11 (afternoon):**
- Executed 03-01-PLAN.md (Content Seeding)
- Created lookup_data.json with 27 records (Format, AgeRating, Tone, ContextTag, Language, CultureTag, Source)
- Built seed_jokes management command with --count and --clear options
- Curated 137 jokes with full M2M relationships and diverse coverage
- **Phase 03: Content Seeding COMPLETE**

**2026-01-11:**
- Executed 02-01-PLAN.md (Data Models)
- Created jokes app with 8 models: Joke, Format, AgeRating, Tone, ContextTag, Language, CultureTag, Source
- Configured admin with filters, search, prepopulated slugs
- **Phase 02: Data Models COMPLETE**

**2026-01-10:**
- Initialized project with /gsd:new-project
- Created comprehensive roadmap with 12 phases
- Executed Phase 01: Foundation (3 plans)
- **Phase 01: Foundation COMPLETE**

---

## Next Actions

1. Execute Phase 06-02: Auth endpoints and migrations
2. Complete Phase 06
3. Then: Phase 07 - User Preferences

---

*Last updated: 2026-01-11*
