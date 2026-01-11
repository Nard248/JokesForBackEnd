# Jokes For - Development Roadmap

## Milestone 1: MVP Launch

**Goal:** Deliver a functional joke search engine with user accounts, collections, and daily joke features.

**Success Criteria:**
- Weekly retention (D7) > 20%
- 10,000 Monthly Active Users
- Average user saves 5+ jokes
- Search queries per session > 2

---

## Domain Expertise

**Required Knowledge Areas:**
- PostgreSQL full-text search configuration and optimization
- Django REST Framework best practices
- JWT authentication implementation
- React + Vite project setup and configuration
- Collaborative filtering basics for recommendations

**Research Phases:** 4, 6, 9, 11 (marked below)

---

## Phase Overview

| Phase | Name | Research | Status | Dependencies |
|-------|------|----------|--------|--------------|
| 01 | Foundation | — | Complete (3/3) | — |
| 02 | Data Models | — | Complete (1/1) | 01 |
| 03 | Content Seeding | — | Complete (1/1) | 02 |
| 04 | Search Engine | Likely | Complete (1/1) | 02 |
| 05 | API Core | — | Complete (2/2) | 02 |
| 06 | Authentication | Likely | Complete (3/3) | 05 |
| 07 | User Preferences | — | pending | 06 |
| 08 | Collections | — | pending | 06 |
| 09 | Daily Joke | Likely | pending | 07 |
| 10 | Sharing | — | pending | 05 |
| 11 | Frontend Foundation | Likely | pending | 05 |
| 12 | Frontend Features | — | pending | 11, 04, 06, 07, 08, 09, 10 |

---

## Phases

### Phase 01: Foundation
**Directory:** `.planning/phases/01-foundation/`
**Research:** Unlikely

**Objective:** Secure Django configuration, PostgreSQL setup, and project structure.

**Scope:**
- Move SECRET_KEY to environment variables
- Configure DEBUG from environment
- Set up python-dotenv for environment management
- Create .gitignore with Python/Django patterns
- Generate requirements.txt with pinned dependencies
- Configure PostgreSQL database connection:
  - Install psycopg2-binary
  - Create `jokesfor` database on local PostgreSQL
  - Configure settings.py with DATABASE settings
  - Local credentials: postgres/6969 on localhost:5432
- Set up ALLOWED_HOSTS configuration
- Create .env.example template

**Deliverables:**
- Secure settings.py configuration
- .gitignore file
- requirements.txt with all dependencies
- .env.example template (with DB_* variables)
- PostgreSQL database `jokesfor` configured and connected

---

### Phase 02: Data Models
**Directory:** `.planning/phases/02-data-models/`
**Research:** Unlikely

**Objective:** Design and implement the Joke model with rich metadata.

**Scope:**
- Create `jokes` Django app
- Implement Joke model with fields:
  - text (TextField)
  - setup/punchline (optional, for two-part jokes)
  - format (one-liner, setup-punchline, short-story)
  - age_rating (kid-safe, teen, adult, family-friendly)
  - humor_type (clean, dark, dad-jokes, puns, sarcasm)
  - context tags (wedding, work, school, presentation, icebreaker)
  - language (default: en)
  - culture/region tags
  - source attribution
  - created_at, updated_at timestamps
- Create initial migrations
- Set up Django admin for Joke management

**Deliverables:**
- jokes app with Joke model
- Database migrations
- Admin interface for jokes

---

### Phase 03: Content Seeding
**Directory:** `.planning/phases/03-content-seeding/`
**Research:** Unlikely

**Objective:** Populate database with 100-200 curated jokes for development.

**Scope:**
- Create management command for bulk joke import
- Source/generate initial joke dataset (mix of public domain + AI-generated)
- Ensure diverse coverage across:
  - All humor types
  - All age ratings
  - Multiple contexts
  - Various formats
- Create fixture file for reproducible seeding

**Deliverables:**
- `python manage.py seed_jokes` command
- JSON fixture with 100-200 jokes
- Verified data with proper metadata

---

### Phase 04: Search Engine
**Directory:** `.planning/phases/04-search-engine/`
**Research:** Likely

**Objective:** Implement PostgreSQL full-text search with filters.

**Scope:**
- Configure PostgreSQL full-text search
- Create search vectors on Joke model
- Implement search index (GIN index)
- Build search query API with:
  - Full-text search on joke content
  - Filter by context
  - Filter by age rating
  - Filter by humor type
  - Filter by format
  - Filter by language
- Implement search ranking/relevance
- Add search result pagination

**Research Topics:**
- PostgreSQL ts_vector and ts_query
- Django SearchVector, SearchQuery, SearchRank
- GIN index optimization
- Trigram similarity for typo tolerance

**Deliverables:**
- Full-text search implementation
- Filter system
- Search API endpoint
- Performance-optimized queries

---

### Phase 05: API Core
**Directory:** `.planning/phases/05-api-core/`
**Research:** Unlikely

**Objective:** Set up Django REST Framework foundation.

**Scope:**
- Install and configure Django REST Framework
- Create base API configuration (versioning, pagination, throttling)
- Implement Joke serializers
- Create Joke viewsets/views:
  - List jokes (with search/filter)
  - Retrieve single joke
  - Random joke endpoint
- Set up API documentation (drf-spectacular or similar)
- Configure CORS for frontend access

**Deliverables:**
- DRF configuration
- Joke API endpoints
- API documentation
- CORS configuration

---

### Phase 06: Authentication
**Directory:** `.planning/phases/06-authentication/`
**Research:** Likely

**Objective:** Implement JWT authentication with social login options.

**Scope:**
- Install djangorestframework-simplejwt
- Configure JWT settings (access/refresh tokens)
- Create User model extensions if needed
- Implement authentication endpoints:
  - Registration (email/password)
  - Login
  - Token refresh
  - Password reset
- Add Google OAuth integration
- Add Apple OAuth integration (optional for MVP)
- Implement guest mode (anonymous browsing)

**Research Topics:**
- SimpleJWT configuration best practices
- Google OAuth2 flow with django-allauth
- Apple Sign-In implementation
- Secure token storage recommendations for frontend

**Deliverables:**
- JWT authentication system
- Registration/login endpoints
- Google OAuth integration
- Guest mode support

---

### Phase 07: User Preferences
**Directory:** `.planning/phases/07-user-preferences/`
**Research:** Unlikely

**Objective:** User preference system for personalization.

**Scope:**
- Create UserPreference model:
  - preferred_humor_types (multi-select)
  - preferred_age_rating
  - preferred_contexts (multi-select)
  - notification_enabled
  - notification_time
  - language preference
- Implement preference onboarding flow (3-5 questions)
- Create preference API endpoints:
  - Get preferences
  - Update preferences
  - Onboarding completion status

**Deliverables:**
- UserPreference model
- Preference API endpoints
- Onboarding flow support

---

### Phase 08: Collections
**Directory:** `.planning/phases/08-collections/`
**Research:** Unlikely

**Objective:** Personal joke library and collections feature.

**Scope:**
- Create Collection model (folders)
- Create SavedJoke model (junction table)
- Implement collection API endpoints:
  - Create/update/delete collections
  - Add/remove jokes from collections
  - List user's saved jokes
  - List jokes in a collection
  - Search within saved jokes
- Default "Favorites" collection

**Deliverables:**
- Collection and SavedJoke models
- Collection management API
- Save/unsave joke functionality

---

### Phase 09: Daily Joke
**Directory:** `.planning/phases/09-daily-joke/`
**Research:** Likely

**Objective:** Personalized "Joke of the Day" with basic recommendations.

**Scope:**
- Create DailyJoke model to track delivered jokes
- Implement joke selection algorithm:
  - Based on user preferences
  - Avoid recently shown jokes
  - Basic collaborative filtering (users who liked X also liked Y)
- Create daily joke API endpoint
- Implement push notification infrastructure (optional for MVP)
- Schedule daily joke generation (Celery task or cron)

**Research Topics:**
- Collaborative filtering algorithms
- Django-celery-beat for scheduled tasks
- Push notification services (OneSignal, Firebase)

**Deliverables:**
- Daily joke selection algorithm
- Daily joke API endpoint
- Notification infrastructure (basic)

---

### Phase 10: Sharing
**Directory:** `.planning/phases/10-sharing/`
**Research:** Unlikely

**Objective:** Joke sharing and rating features.

**Scope:**
- Create JokeRating model (thumbs up/down or 1-5 scale)
- Implement rating API endpoints
- Create shareable joke URLs
- Implement share card generation (image with branding)
- Track share events for analytics
- Copy-to-clipboard API support

**Deliverables:**
- Rating system
- Shareable URLs
- Share card generation
- Share analytics tracking

---

### Phase 11: Frontend Foundation
**Directory:** `.planning/phases/11-frontend-foundation/`
**Research:** Likely
**Location:** `/Users/narekmeloyan/WebstormProjects/`

**Objective:** Set up React + Vite project with core infrastructure.

**Scope:**
- Initialize React + Vite project
- Configure TypeScript
- Set up project structure:
  - components/
  - pages/
  - hooks/
  - services/
  - utils/
  - types/
- Configure API client (axios or fetch wrapper)
- Set up routing (React Router)
- Configure state management (React Query or Zustand)
- Set up authentication context
- Configure environment variables
- Basic responsive layout/shell

**Research Topics:**
- Vite configuration best practices
- React Query vs SWR vs Zustand for state
- JWT token management in React
- Mobile-first responsive design patterns

**Deliverables:**
- React + Vite project structure
- API client configuration
- Routing setup
- Auth context
- Base layout component

---

### Phase 12: Frontend Features
**Directory:** `.planning/phases/12-frontend-features/`
**Research:** Unlikely

**Objective:** Implement all MVP UI features.

**Scope:**
- Search page with filters
- Search results display
- Joke detail view
- User registration/login flows
- Preference onboarding UI
- Daily joke panel/widget
- Collections management UI
- Saved jokes library
- Share functionality
- Rating UI
- Settings page
- Responsive mobile design

**Deliverables:**
- Complete MVP user interface
- All P0 features functional
- Mobile-responsive design

---

## Dependencies Graph

```
01-foundation
    └── 02-data-models
            ├── 03-content-seeding
            ├── 04-search-engine ─────────────────────────────┐
            └── 05-api-core                                   │
                    ├── 06-authentication                     │
                    │       ├── 07-user-preferences           │
                    │       │       └── 09-daily-joke ────────┤
                    │       └── 08-collections ───────────────┤
                    ├── 10-sharing ───────────────────────────┤
                    └── 11-frontend-foundation                │
                            └── 12-frontend-features ◄────────┘
```

---

## Risk Areas

1. **PostgreSQL Full-Text Search Performance** - May need optimization for scale
2. **OAuth Integration Complexity** - Google/Apple have different requirements
3. **Recommendation Algorithm** - Collaborative filtering needs sufficient user data
4. **Frontend State Management** - JWT refresh token handling can be tricky

---

*Roadmap created: 2026-01-11*
*Milestone: MVP (Phase 1)*
