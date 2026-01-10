# Jokes For

## What This Is

A global humor discovery platform - the world's best joke search engine. Users find personalized jokes tailored by age, culture, language, tone, and context. Unlike social media's chaotic feeds that require weeks of passive scrolling, Jokes For enables active discovery through intelligent search and filters for people who NEED jokes for specific purposes.

## Core Value

**The "search engine for jokes"** - a utility that people return to when they need humor for a specific purpose (speeches, presentations, classroom, social media). Prove utility and retention first; creator economy and brand integrations come only after proving core value.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- [x] Django project scaffolding — existing
- [x] Codebase mapping and documentation — existing

### Active

<!-- Current scope. Building toward these (MVP Phase 1). -->

**Joke Search Engine (P0):**
- [ ] Full-text search with PostgreSQL
- [ ] Context filters (wedding, work, school, presentation, icebreaker)
- [ ] Age filters (kid-safe, teen, adult, family-friendly)
- [ ] Humor type filters (clean, dark, dad jokes, puns, sarcasm)
- [ ] Language filter (English + 2-3 key markets)
- [ ] Format filter (one-liner, setup-punchline, short story)

**Daily Joke Panel (P0):**
- [ ] Personalized "Joke of the Day" based on preferences
- [ ] Preference onboarding flow (3-5 questions)
- [ ] Push notifications (optional, configurable timing)

**Joke Library & Collections (P0):**
- [ ] Save jokes to personal library
- [ ] Create custom collections (folders)
- [ ] Browse and search within library

**Sharing (P0-P1):**
- [ ] Copy joke to clipboard
- [ ] Native share to social platforms
- [ ] Branded share card (image with Jokes For branding)
- [ ] Rate jokes (thumbs up/down or laugh scale)

**User Accounts (P0):**
- [ ] Registration (email/password, Google, Apple)
- [ ] Guest mode
- [ ] Preference management
- [ ] Notification settings

**Content Infrastructure (P0):**
- [ ] Joke database with rich metadata (tags, age rating, language, culture, format)
- [ ] PostgreSQL full-text search index
- [ ] Basic recommendation engine (collaborative filtering)
- [ ] 5,000+ curated jokes (start with 100-200 for dev)

**REST API (P0):**
- [ ] Django REST Framework API for frontend
- [ ] JWT authentication
- [ ] Joke CRUD endpoints
- [ ] Search and filter endpoints
- [ ] User preference endpoints

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Mobile apps (iOS/Android) — Web-only MVP; mobile is Phase 2+ to reduce complexity
- Creator profiles and uploads — Phase 2; need users before creators matter
- Monetization tools (subscriptions, tips, packs) — Phase 2; prove retention first
- Brand accounts and campaigns — Phase 3; need 100K+ MAU for B2B relevance
- API/Enterprise features — Phase 3; premature without scale
- AI joke generation — P2 feature; focus on curation first
- Multi-language beyond English — Start English-only, add languages when core is proven

## Context

**Business Model:** Multi-stream revenue planned for later phases:
- Premium subscriptions ($2.99-$5.99/month) — Phase 2
- Creator marketplace fees (15-20%) — Phase 2
- Branded humor campaigns (B2B) — Phase 3
- API licensing — Phase 3

**Target Users (MVP focus):**
- Speech givers (wedding toasts, presentations)
- Teachers needing classroom icebreakers
- Managers wanting meeting openers
- Social media creators needing captions
- Parents seeking kid-safe humor

**Success Criteria (Phase 1 gate to Phase 2):**
- Weekly retention (D7) > 20%
- 10,000 Monthly Active Users
- Average user saves 5+ jokes
- Search queries per session > 2
- Viral coefficient > 0.3

**Content Strategy:**
- 100-200 jokes for development/testing
- Mix of public domain + AI-generated (human-curated)
- Scale to 5,000+ for public launch
- Rich metadata: tags, age rating, language, culture, format, context

**Reference Documents:**
- Business Plan: `/Users/narekmeloyan/PycharmProjects/JokesForProject/Docs/Business Docs/`
- Feature Spec: `Jokes_For_Feature_List.pdf`

## Constraints

- **Tech Stack (Backend)**: Django 5.x + Django REST Framework + PostgreSQL — existing project at `/Users/narekmeloyan/PycharmProjects/JokesForProject/`
- **Tech Stack (Frontend)**: React + Vite — separate project at `/Users/narekmeloyan/WebstormProjects/`
- **Solo Developer**: Building with Claude assistance
- **Budget**: Prefer free/open-source tools; minimize paid services
- **Database**: PostgreSQL with full-text search (not Elasticsearch initially)

**Local Development Database:**
- Host: localhost
- Port: 5432 (default)
- Username: `postgres`
- Password: `6969`
- Database name: `jokesfor` (to be created)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Separate backend/frontend | API-first architecture enables future mobile apps | — Pending |
| Django REST Framework | Standard Django ecosystem, good docs, fits existing setup | — Pending |
| React + Vite (not Next.js) | Simpler setup, avoids SSR complexity, user preference | — Pending |
| PostgreSQL full-text search | Built-in, free, sufficient for MVP scale | — Pending |
| Web-only MVP | Reduce scope, prove retention before mobile investment | — Pending |
| English-first | Humor doesn't translate; prove product before localization | — Pending |
| Curation before AI | Content quality > quantity; AI generation is P2 | — Pending |

---
*Last updated: 2026-01-11 after initialization*
