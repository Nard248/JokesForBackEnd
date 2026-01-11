# Project State

## Current Status

**Project:** Jokes For
**Milestone:** 1 - MVP Launch
**Phase:** 11 - Frontend Foundation (COMPLETE)
**Status:** Ready for Phase 12

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
- [x] **Phase 08: Collections COMPLETE**
- [x] **Phase 09: Daily Joke COMPLETE**
- [x] **Phase 10: Sharing COMPLETE**
- [x] **Phase 11: Frontend Foundation COMPLETE**
  - 11-01: React + Vite + TypeScript + TailwindCSS v4 + shadcn/ui
  - 11-02: React Router + TanStack Query + Zustand
  - 11-03: Axios HTTP client with JWT interceptors
  - 11-04: Shell layout (Header/Footer) + Playwright E2E

### Upcoming
1. Phase 12: Frontend Features (API integration, search UI, collections UI, etc.)

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
| 2026-01-11 | Tone-based share card templates | Different themes for dad-jokes, dark, puns vs default |
| 2026-01-11 | Text change detection for share images | Track _original_text to avoid unnecessary regeneration |
| 2026-01-11 | Pre-generate share images on save | Performance over on-demand generation |
| 2026-01-11 | TailwindCSS v4 CSS-first config | New @theme directive approach, no tailwind.config.js |
| 2026-01-11 | shadcn/ui canary for React 19 + Tailwind v4 | Compatibility with latest versions |
| 2026-01-11 | oklch color space for theme colors | Perceptually uniform color adjustments |
| 2026-01-11 | Path aliases (@/*) in both tsconfigs | Satisfies both TypeScript and shadcn tooling |
| 2026-01-11 | React Router 7.x with createBrowserRouter | Modern declarative routing with nested route support |
| 2026-01-11 | Two-store pattern (TanStack Query + Zustand) | Server state vs client state separation |
| 2026-01-11 | TanStack Query 5-min stale time | Optimal balance between freshness and performance |
| 2026-01-11 | Provider composition pattern | Clean App.tsx with single Providers wrapper |
| 2026-01-11 | Access token in memory (Zustand) | XSS protection vs localStorage |
| 2026-01-11 | Raw axios for refresh endpoint | Prevents infinite interceptor loop |
| 2026-01-11 | Subscriber queue for concurrent 401s | One refresh call, queued retries |
| 2026-01-12 | lucide-react for icons | Consistent, tree-shakeable, replaces emojis |
| 2026-01-12 | Pixel 5 for mobile E2E tests | Chromium-based, avoids WebKit install |
| 2026-01-12 | Ref guard for AuthProvider | Handles React StrictMode double-mount |

---

## Active Issues

None tracked yet.

---

## Session Notes

**2026-01-12 (morning):**
- Executed 11-04-PLAN.md (Shell Layout and E2E Testing)
- Created Header component with nav, auth state, mobile menu
- Created Footer component with links and branding
- Built creative HomePage with floating jokes, gradient shapes, animations
- Configured Playwright with chromium + mobile projects, 10 passing tests
- Fixed infinite refresh bug in AuthProvider (raw axios + ref guard)
- Checkpoint iteration: replaced emojis with lucide icons, added visual polish
- **11-04 complete** (4/4 plans for Phase 11)
- **Phase 11: Frontend Foundation COMPLETE**
- User feedback for Phase 12: Focus on API integrations, clear public vs protected features

**2026-01-11 (night, latest):**
- Executed 11-03-PLAN.md (API Client Configuration)
- Installed Axios and created HTTP client with JWT interceptors
- Implemented refresh token queue pattern for concurrent 401 handling
- Created typed API helpers for auth, jokes, daily-joke, collections endpoints
- Built Zustand auth store with user/token state and actions
- Created TanStack Query mutations for login/register/logout
- Added AuthProvider that checks session on mount via token refresh
- Updated Layout to display auth state with login/logout controls
- **11-03 complete** (3/4 plans for Phase 11)

**2026-01-11 (night):**
- Executed 11-02-PLAN.md (Routing and State Management)
- Installed React Router 7.x and configured nested routes with layout wrapper
- Created stub pages for all routes (Home, Daily, Collections, Settings, Login, Register, 404)
- Installed TanStack Query with DevTools and configured optimized QueryClient
- Installed Zustand and created UI store for mobile menu state
- Established two-store pattern: TanStack Query for server state, Zustand for client state
- Built responsive Layout component with mobile menu toggle
- **11-02 complete** (2/4 plans for Phase 11)

**2026-01-11 (night):**
- Executed 11-01-PLAN.md (Project Initialization)
- Initialized React + Vite + TypeScript frontend project at /Users/narekmeloyan/WebstormProjects/jokes-for-frontend/
- Configured TailwindCSS v4 with CSS-first @theme directive (playful purple color scheme)
- Set up shadcn/ui canary with Button component
- Created project structure (app/, components/, features/, hooks/, lib/, types/)
- Configured path aliases (@/*) for clean imports
- Resolved npm native module issues (oxide, lightningcss)
- **11-01 complete** (1/4 plans for Phase 11)

**2026-01-11 (night):**
- Executed 10-03-PLAN.md (Share Analytics)
- Created ShareEvent model with joke/user/platform fields for tracking share button clicks
- Built public share page at /jokes/{id}/share/ with full OG meta tags (og:title, og:description, og:image, og:url, etc.)
- Added Twitter Card support (summary_large_image)
- Created POST /api/v1/jokes/{id}/share/ endpoint for recording share events
- AllowAny permission allows tracking both authenticated and anonymous shares
- **10-03 complete** (3/3 plans for Phase 10)
- **Phase 10: Sharing COMPLETE**

**2026-01-11 (night):**
- Executed 10-02-PLAN.md (Share Cards Infrastructure)
- Installed CairoSVG and created 4 themed SVG templates (base, dad_joke, dark_humor, pun)
- Added share_image ImageField to Joke model with auto-generation on save
- Implemented text change detection via _original_text to avoid unnecessary regeneration
- Added share_image_url to JokeSerializer and JokeListSerializer with absolute URLs
- **10-02 complete** (2/3 plans for Phase 10)

**2026-01-11 (night):**
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

1. Plan Phase 12 - Frontend Features (with focus on API integration + public/protected distinction)

---

*Last updated: 2026-01-12*
