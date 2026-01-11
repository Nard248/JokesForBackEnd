# Project State

## Current Status

**Project:** Jokes For
**Milestone:** 1 - MVP Launch
**Phase:** 10 - Sharing (IN PROGRESS)
**Status:** 1/3 plans complete, executing Phase 10

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
- [x] **Phase 05: API Core COMPLETE**
- [x] **Phase 06: Authentication COMPLETE**
- [x] **Phase 07: User Preferences COMPLETE**
- [x] **08-01**: Collection and SavedJoke models (models, migration, signals, admin)
- [x] **08-02**: Collections API endpoints (serializers, ViewSets, routes)
- [x] **Phase 08: Collections COMPLETE**
- [x] **09-01**: Celery infrastructure setup (celery, redis, django-celery-beat)
- [x] **09-02**: DailyJoke model and recommendation algorithm
- [x] **09-03**: Celery tasks and Daily Joke API endpoints
- [x] **Phase 09: Daily Joke COMPLETE**
- [x] **10-01**: JokeRating model and rating API endpoints

### Upcoming
1. Phase 10: Sharing (2 more plans - share cards, share analytics)
2. Phase 11: Frontend Foundation
3. Phase 12: Frontend Features

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
| 2026-01-11 | Custom EmailOnlyRegisterSerializer | dj-rest-auth default requires username at import time |
| 2026-01-11 | Console EMAIL_BACKEND for dev | No SMTP needed, switch to real backend for production |
| 2026-01-11 | settings.AUTH_USER_MODEL for UserPreference | Flexibility over direct User import |
| 2026-01-11 | post_save signal for UserPreference auto-create | Ensures every user has preferences |
| 2026-01-11 | Separate read/write serializers for preferences | Nested for display, PK fields for updates |
| 2026-01-11 | GenericViewSet for preferences API | Custom actions only, no standard CRUD |
| 2026-01-11 | CASCADE on_delete for user-owned data | User owns collections/saved jokes, delete with user |
| 2026-01-11 | Separate signal for Favorites auto-create | Clean separation, follows UserPreference pattern |
| 2026-01-11 | raw_id_fields for joke FK in admin | Performance with many jokes |
| 2026-01-11 | Separate read/write serializers for collections | Nested for display, PK fields for updates |
| 2026-01-11 | Default collection delete protection | Prevent users from deleting their Favorites |
| 2026-01-11 | Reuse Joke.objects.search() for saved joke search | Consistency with main search, no code duplication |
| 2026-01-11 | Content-based filtering for MVP recommendations | Simpler than collaborative, no cold-start problem |
| 2026-01-11 | 30-day recency window for joke exhaustion prevention | Balances variety with small dataset |
| 2026-01-11 | Pre-generate + on-demand fallback pattern | Scheduled task at night, API fallback if missed |

---

## Active Issues

None tracked yet.

---

## Session Notes

**2026-01-11 (night, latest):**
- Executed 10-01-PLAN.md (Joke Rating System)
- Created JokeRating model with user/joke FKs, binary rating (1/-1), unique_together constraint
- Added POST /api/v1/jokes/{id}/rate/ for thumbs up/down voting
- Added GET /api/v1/jokes/{id}/my-rating/ for retrieving user's current rating
- Both endpoints return aggregate joke_score via Sum aggregate
- **10-01 complete** (1/3 plans for Phase 10)

**2026-01-11 (night, later):**
- Executed 09-03-PLAN.md (Celery Task and Daily Joke API)
- Created generate_daily_jokes Celery task for batch processing
- Created generate_daily_joke_for_user for on-demand fallback
- Built DailyJokeViewSet with today() and history() endpoints
- Registered at /api/v1/daily-jokes/
- **Phase 09: Daily Joke COMPLETE** (3/3 plans)

**2026-01-11 (night, later):**
- Executed 09-02-PLAN.md (DailyJoke Model and Recommendation Algorithm)
- Created DailyJoke model with user/joke FKs, unique_together on [user, date]
- Built content-based recommendation algorithm in jokes/recommendations.py
- Implemented 30-day recency window and popularity scoring

**2026-01-11 (night, later):**
- Executed 09-01-PLAN.md (Celery Infrastructure Setup)
- Installed celery 5.6.2, redis 7.1.0, django-celery-beat 2.8.1, django-celery-results 2.6.0
- Created JokesForProject/celery.py with Django integration
- Configured Redis broker and result backend in settings.py
- Applied django_celery_beat and django_celery_results migrations

**2026-01-11 (night):**
- Executed 08-02-PLAN.md (Collections API Endpoints)
- Created CollectionSerializer, CollectionCreateSerializer, SavedJokeSerializer, SavedJokeCreateSerializer
- Built CollectionViewSet (ModelViewSet) with CRUD + jokes() action
- Built SavedJokeViewSet (mixin-based) with create/delete/list + search()
- Registered routes at /api/v1/collections/ and /api/v1/saved-jokes/
- **Phase 08: Collections COMPLETE** (2/2 plans)

**2026-01-11 (night):**
- Executed 08-01-PLAN.md (Collection and SavedJoke Models)
- Created Collection model with user FK, name, is_default flag, timestamps
- Created SavedJoke model with user/joke/collection FKs, note, timestamp
- Added create_default_collection signal for auto-creating "Favorites" collection
- Configured admin with list_display, list_filter, search_fields, raw_id_fields

**2026-01-11 (late evening):**
- Executed 07-02-PLAN.md (Preference API Endpoints)
- Created UserPreferenceSerializer (read with nested) and UserPreferenceUpdateSerializer (write with PK)
- Built UserPreferenceViewSet with me() and complete_onboarding() actions
- Registered routes at /api/v1/preferences/me/ and /api/v1/preferences/complete-onboarding/
- **Phase 07: User Preferences COMPLETE** (2/2 plans)

**2026-01-11 (late evening):**
- Executed 07-01-PLAN.md (UserPreference Model)
- Created UserPreference model with tone/context/rating/language preferences
- Added post_save signal for auto-creation on user signup
- Built admin interface with filters, search, horizontal M2M widgets

**2026-01-11 (evening):**
- Executed 06-03-PLAN.md (Google OAuth & Auth Verification)
- Configured Google OAuth credentials in Cloud Console and created SocialApp
- Fixed email-only registration with custom EmailOnlyRegisterSerializer
- Verified all auth flows: registration, login, token refresh, authenticated access
- All 12 auth endpoints confirmed working
- **Phase 06: Authentication COMPLETE**

---

## Next Actions

1. Execute 10-02-PLAN.md (Share Cards)
2. Execute 10-03-PLAN.md (Share Analytics)
3. Then: Phase 11 - Frontend Foundation
4. Then: Phase 12 - Frontend Features

---

*Last updated: 2026-01-11*
