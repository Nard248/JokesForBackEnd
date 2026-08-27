# JokesFor — Complete End-to-End User Journey Catalog (key: `user-journeys`)

Synthesized 2026-08-25 from the fourteen analyzer reports in this directory (be-architecture, be-api-surface, be-auth-session, be-media-pipeline, be-compliance-moderation, be-billing-tips-paywall, be-tests-quality, fe-architecture-routes, fe-data-layer, fe-tests-quality, infra-ops, local-dev-runbook, known-gaps-risk-register, ios-api-readiness), the design specs in `/Users/narekmeloyan/PycharmProjects/JokesForProject/Docs/superpowers/specs/`, and direct reads of `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/app/routes.tsx` plus targeted greps of the FE pages/components (`SettingsPage`, `ProfilePage`, `LibraryPage`, `JokeDetailPage`, `FlowCanvasPage`, `CreatorProfilePage`, `CreatorHubPage`, `SubmissionDetailPage`, `DailyJokePage`, `PackDetailPage`, `ExplorePage`, `SearchPage`, `FavoritesPage`, `CollectionsPage`, `TrendingPage`, `FlowPage`, `BillingPage`, `LandingPage`, `FlowJokeCard`, `NotificationsPanel`, `AppealButton`, `ReportJokeButton`, `BlockButton`, `FlowAppShell`).

Code wins over docs everywhere. Where an *expected* behavior is questionable from a product standpoint it is flagged inline with **⚠ QUESTIONABLE** so the test pipeline can decide whether to assert the current behavior or file it as a defect.

Prod URLs: backend `https://jokesforbackend-332865216810.us-east1.run.app`, frontend `https://jokesforfront.web.app`. All BE endpoints below are relative to `/api/v1/` unless they start with `/` and are outside the API (e.g. `/jokes/<id>/share/`, `/sitemap.xml`, `/readyz`, `/admin/`).

---

## 0. Actors

| Actor | Definition (from code) |
|---|---|
| **Anonymous visitor** | No JWT; `allowed_tiers` = `{tier_1}`; paywall ledger = signed cookie `jf_anon_reads` (10/day soft wall); can read, search, view share pages, reveal (cookie), share, view creator profiles, packs; cannot save/react/report/upload. |
| **New registrant** | Person on `/register`; must supply DOB ≥13; with `EMAIL_VERIFICATION_REQUIRED=true` (prod) becomes an **inactive** user with no tokens until the 6-digit code is verified. |
| **Unverified user** | `is_active=False` user holding no tokens; login → 400; resend/verify only. |
| **Free reader (verified, authenticated)** | Active user, no `Subscription` (or `free`/`canceled`/`past_due`); 10 distinct `JokeView`s per UTC day; mystery box 3/day; history 30 days. |
| **Paid reader** | `Subscription.status ∈ {active, trialing}` on `supporter`/`creator_pro`; `free_joke_reads_per_day=None` → never locked; history 90/365 days; mystery box 10/20. Prod: **dormant** (Stripe test keys only, placeholder plans, blank `stripe_price_id`). |
| **Creator** | Any authenticated user can open `/create` and submit; **`IsCreator`** (insights) = ≥1 `JokeSubmission(status='published')`; **tippable creator** = ≥1 non-removed `Joke.creator` row. Demo: `demo.creator@jokesfor.dev` / `DemoCreator!2026` (local seed). |
| **Tipped creator** | Creator who has received `Tip(status='succeeded')` rows (needs Stripe enabled + webhook). |
| **Moderator / staff** | Django `is_staff` user with session login at `/admin/` (no superuser exists locally; `createsuperuser` required). Actions: approve/publish, reject (change-form), take down, dismiss, restore, uphold/reverse appeals, toggle `show_mature`, push plans to Stripe. |
| **Search-engine / social bot** | Non-JS fetcher hitting `/jokes/<id>/share/`, `/sitemap.xml`, `robots.txt`, FE deep routes (Firebase SPA rewrite). |
| **Cloud Scheduler / ops caller** | Shared-secret caller of `POST /api/v1/internal/run-digests/` (`X-Digest-Token`); uptime probes of `/readyz`; Stripe webhook deliverer. |

---

## 1. Summary table

| ID | Journey | Actor | Area | Prio | Local? |
|---|---|---|---|---|---|
| J-001 | Landing page visit + try-it reveal + CTAs | Anonymous | discovery/landing | P0 | yes |
| J-002 | Authenticated user hits `/` → redirected to Today hub | Free reader | discovery/landing | P1 | yes |
| J-003 | Anonymous browse/search jokes (paginated tier_1 feed) | Anonymous | discovery/search | P0 | yes |
| J-004 | Anonymous joke detail + reveal + 10/day cookie soft-wall | Anonymous | reading/paywall | P0 | yes |
| J-005 | Anonymous trending page | Anonymous | discovery/trending | P1 | yes |
| J-006 | Anonymous daily joke page | Anonymous | reading/daily | P1 | yes |
| J-007 | Anonymous visits protected route → login redirect with returnTo | Anonymous | auth/routing | P0 | yes |
| J-008 | Anonymous visits `/library` (public route, auth-only data) | Anonymous | routing gap | P2 | yes |
| J-009 | Legal pages, `/cookies` alias, consent banner | Anonymous | legal/consent | P1 | yes |
| J-010 | Unknown path → NotFoundPage; legacy redirects | Anonymous | routing | P2 | yes |
| J-011 | Bot fetches share page for a tier_1 joke (OG/JSON-LD) | Bot | seo/share | P1 | yes |
| J-012 | Bot fetches share page for tier_2 / removed / missing joke | Bot | seo/share | P1 | yes |
| J-013 | Bot fetches sitemap.xml / robots.txt; FE prebuild sitemap | Bot | seo | P1 | partial |
| J-014 | Reader shares a joke (copy link + ShareEvent) | Anonymous/Free reader | social/share | P2 | yes |
| J-020 | Email registration (gated) → verify code → onboarding | New registrant | auth/register | P0 | yes |
| J-021 | Registration rejected: under-13, future DOB, missing DOB, dup email, password mismatch | New registrant | auth/register | P0 | yes |
| J-022 | Verify-email failure modes: wrong code ×5 → 429, expired, unknown email, resend throttle | Unverified | auth/verify | P1 | yes |
| J-023 | Registration email send failure → 502 → resend recovers | New registrant | auth/verify | P2 | yes |
| J-024 | Unverified user tries to log in | Unverified | auth/login | P1 | yes |
| J-025 | Login with email/password, returnTo, logout | Free reader | auth/login | P0 | yes |
| J-026 | Session persistence, access expiry auto-refresh, rotation/blacklist | Free reader | auth/session | P0 | yes |
| J-027 | Google OAuth sign-up (new user with DOB) | New registrant | auth/oauth | P1 | no |
| J-028 | Google OAuth edge cases: existing user, dob_required, under-13, cancelled, email collision | New registrant | auth/oauth | P1 | partial |
| J-029 | Forgot password → reset link → set new password → login | Free reader | auth/password | P1 | yes |
| J-030 | Change password from Settings | Free reader | auth/password | P1 | yes |
| J-031 | CSRF enforcement on cookie-auth mutations; Bearer bypass | Free reader | auth/security | P0 | yes |
| J-032 | Anonymous IP throttle 100/h; user 1000/h | Anonymous | auth/security | P2 | yes |
| J-033 | Legacy ungated registration (`EMAIL_VERIFICATION_REQUIRED=false`) | New registrant | auth/register | P2 | yes |
| J-040 | Onboarding `/flow`: vibes ≥3 → formats → ritual → finish | Free reader | onboarding | P0 | yes |
| J-041 | Onboarding skip / revisit | Free reader | onboarding | P2 | yes |
| J-042 | Settings: preferences, public identity (display name/handle), blocked users | Free reader | settings | P1 | yes |
| J-043 | Profile page: stats, activity, achievements, humor DNA | Free reader | profile | P1 | yes |
| J-050 | Today hub `/flow-canvas` (streak, daily, tomorrow, mystery box, packs, taste, jokesters, history) | Free reader | home | P0 | yes |
| J-051 | Explore with format/category chips | Free reader | discovery/explore | P1 | yes |
| J-052 | Search with query, filters, load more | Free reader | discovery/search | P1 | yes |
| J-053 | Text joke detail (authenticated): JokeView with source, reactions, save, report, share, dwell | Free reader | reading/detail | P0 | yes |
| J-054 | Media joke detail (image/GIF/video/audio) incl. locked dims-only | Free reader | reading/media | P1 | partial |
| J-055 | Free reader paywall: 10 reads → locked, already-read stays open, nudge, CTA, midnight reset | Free reader | paywall | P0 | yes |
| J-056 | Paid reader: unlimited reads, daily-reads null limits, larger quotas | Paid reader | paywall/billing | P1 | yes (DB seed) |
| J-057 | Daily joke (authenticated): same joke all day, issue label, exempt from paywall, history, tomorrow teaser | Free reader | reading/daily | P1 | yes |
| J-058 | Mystery box roll ×3 → 429 | Free reader | ritual/mystery | P1 | yes |
| J-059 | Streak: increment, freeze/unfreeze, at-risk, monthly refresh | Free reader | ritual/streak | P1 | yes |
| J-060 | Packs: list/featured/detail, progress, completion, in-progress list | Free reader | reading/packs | P1 | yes |
| J-061 | Reactions toggle/switch | Free reader | engagement | P1 | yes |
| J-062 | Like/dislike rating (API only; FE unused) | Free reader | engagement | P2 | yes |
| J-063 | Favorites add/remove/stats/tone filter | Free reader | library/favorites | P1 | yes |
| J-064 | Saved jokes + collections (create, save, duplicates, delete default, detail, search) | Free reader | library/collections | P1 | yes |
| J-065 | Recently viewed (API; FE hook unused) | Free reader | library | P2 | yes |
| J-066 | Content-tier gating (anon/minor/adult; `show_mature` admin-only) | Anonymous/Free reader/Staff | compliance/tiers | P1 | yes |
| J-067 | Audience telemetry (impression/reveal/dwell/watch) → creator insights | Free reader | telemetry | P1 | yes |
| J-070 | Creator profile view + follow/unfollow + `followed_you` notification | Free reader/Anonymous | social/follows | P1 | yes |
| J-071 | Block a creator (hide jokes, sever follows, profile 404) and unblock | Free reader | moderation/block | P1 | yes |
| J-072 | Report a joke (dedup returns existing) | Free reader | moderation/report | P1 | yes |
| J-073 | Tip a creator: dormant vs enabled → Stripe checkout → webhook → summary | Free reader / Tipped creator | tips | P1 | partial |
| J-074 | Notifications inbox: bell badge, panel, mark all read | Free reader | inbox | P1 | yes |
| J-080 | Creator hub: drafts list, status tabs, unseen dot, appeals strip | Creator | creator/hub | P1 | yes |
| J-081 | New text joke: format picker → editor autosave → submit → moderator approve → published | Creator + Staff | creator/authoring | P0 | yes |
| J-082 | Submit incomplete draft → per-format 400s; pending draft not editable | Creator | creator/authoring | P1 | yes |
| J-083 | Image joke: upload JPEG/PNG/WebP (→ WebP), 1–6 images, submit, publish with media share card | Creator + Staff | creator/media | P1 | partial |
| J-084 | GIF upload routed through video pipeline | Creator | creator/media | P2 | yes |
| J-085 | Video joke upload with limits (60s / 30MB / 1080p) and busy 429 | Creator | creator/media | P1 | yes |
| J-086 | Audio joke upload (→ AAC m4a) | Creator | creator/media | P2 | yes |
| J-087 | SafeSearch blocks an upload (422) / fail-open on Vision error | Creator | creator/screening | P1 | partial |
| J-088 | Media upload throttle 30/h | Creator | creator/media | P2 | yes |
| J-089 | Moderator rejects submission → `joke_rejected` notice → creator edits & resubmits | Creator + Staff | creator/moderation | P1 | yes |
| J-090 | Delete a draft (unlinked assets removed) | Creator | creator/authoring | P2 | yes |
| J-091 | Creator insights page (period switch; non-creator 403) | Creator | creator/insights | P1 | yes |
| J-092 | Submission detail page states (draft/pending/published/rejected) | Creator | creator/authoring | P2 | yes |
| J-100 | Staff triage: reports queue → take down joke → notice → hidden everywhere → media quarantined | Staff + Creator | moderation/takedown | P0 | yes |
| J-101 | Creator appeals a takedown (from notification / hub) incl. window, duplicate, throttle | Creator | appeals | P1 | yes |
| J-102 | Staff upholds appeal → media purged, creator notified | Staff + Creator | appeals | P1 | yes |
| J-103 | Staff reverses takedown appeal → joke live again, media released, card regenerated | Staff + Creator | appeals | P1 | yes |
| J-104 | Rejection appeal → reverse returns submission to draft | Creator + Staff | appeals | P2 | yes |
| J-105 | Staff restores removed jokes (admin action) | Staff | moderation | P2 | yes |
| J-106 | Staff flips `is_removed` directly in JokeAdmin (silent takedown) | Staff | moderation | P2 | yes |
| J-107 | Lapsed quarantine purge (14 days, request-triggered) | Ops/Creator | moderation/retention | P2 | yes |
| J-108 | Staff dismisses / marks resolved reports | Staff | moderation | P2 | yes |
| J-110 | Billing page with Stripe dormant (503 → unavailable state) | Free reader | billing | P1 | yes |
| J-111 | Upgrade: plans → checkout → Stripe → webhook → active subscription → unlimited reads | Free reader → Paid reader | billing | P1 | partial |
| J-112 | Manage subscription: portal session; 409 active-subscription conflict | Paid reader | billing | P2 | partial |
| J-113 | Stripe webhook lifecycle: signature, idempotency, updated/deleted/invoice events | Stripe (ops) | billing/webhook | P1 | yes |
| J-114 | Entitlements / my-subscription defaults for free users | Free reader | billing | P2 | yes |
| J-120 | GDPR data export (zip) | Free reader | gdpr | P1 | yes |
| J-121 | Delete account (password vs OAuth confirm) → cascade → logged out | Free reader | gdpr | P0 | yes |
| J-130 | Cloud Scheduler triggers daily digests (dormant 404 vs token 200; idempotent; milestones) | Scheduler | email/digest | P1 | yes |
| J-131 | Email unsubscribe link (GET confirm, POST flip, RFC 8058) | Free reader | email | P2 | yes |
| J-133 | Health probes `/healthz` and `/readyz` | Ops | ops/health | P1 | partial |
| J-134 | OpenAPI schema / Swagger / Redoc | Developer | ops/docs | P2 | yes |
| J-135 | CORS preflight from SPA origin | Ops | ops/cors | P1 | yes |
| J-136 | Cold start on prod (scale-from-zero + Neon resume) | Ops | ops/perf | P2 | no |
| J-140 | Legacy `/legacy/*` subtree | Free reader | legacy | P2 | yes |
| J-141 | Mobile responsive shell (bottom tab bar, streak chip, nudge placement) | Anonymous/Free reader | responsive | P1 | yes |

---

## 2. Journey details

Conventions: **Pre** = preconditions; **Steps** = ordered user/system actions; **Expected** = what should happen (sanity-checked); **Pages** = FE routes; **Endpoints** = BE calls; **Local** = testable on the local full stack per `local-dev-runbook.md` (`DATABASE_URL=`, console email, `DYLD_FALLBACK_LIBRARY_PATH`, FE with `VITE_USE_MOCKS=false VITE_USE_REAL_CREATE=true`); **Prod-only** = why parts cannot be verified locally.

### Discovery / landing / SEO

#### J-001 — Landing page visit + try-it reveal + CTAs
- Actor: Anonymous · Area: discovery/landing · **P0** · Local: yes
- Pre: no `jokesfor-auth` in sessionStorage.
- Steps: (1) GET `/`. (2) Observe hero card with blurred punchline. (3) Click "Reveal the punchline" (`data-testid=try-it-reveal`). (4) Click "Start reading free" / "Sign in".
- Expected: `LandingPage` renders (marketing header/footer, **not** FlowAppShell); `<Seo>` emits WebSite+SearchAction and Organization JSON-LD; hero punchline reveals client-side from a curated static joke (no API call, no paywall consumption); reveal button becomes disabled after one reveal; trust line "Free · no card · 10 fresh jokes a day."; all CTAs → `/register`, "Sign in" → `/login`; footer contains `/privacy`, `/terms`, `/cookie-policy` links; no fabricated social-proof numbers; page is mobile-first responsive. App boot fires `GET auth/csrf/` (200) and `POST auth/token/refresh/` (401 for anon) — proves real mode.
- Pages: `/` · Endpoints: `auth/csrf/`, `auth/token/refresh/` (boot only)
- Prod-only: none.

#### J-002 — Authenticated user hits `/`
- Actor: Free reader · **P1** · Local: yes
- Pre: valid session (sessionStorage `jokesfor-auth.isAuthenticated=true` or refresh cookie).
- Steps: (1) Navigate to `/`.
- Expected: `<Navigate to="/flow-canvas" replace/>` from inside `LandingPage` with no landing flash (store rehydrates synchronously). ⚠ QUESTIONABLE: if only the refresh cookie exists (sessionStorage cleared, e.g. new tab), the landing renders first and stays until the user navigates, because `isAuthenticated` is false until `AuthProvider` finishes; after bootstrap the page does not re-check. Verify the observed behavior.
- Pages: `/` → `/flow-canvas`.

#### J-003 — Anonymous browse/search jokes
- Actor: Anonymous · **P0** · Local: yes
- Pre: DB seeded (local: 304 jokes).
- Steps: (1) GET `/search` (no query). (2) Type a query (debounced). (3) Toggle format/theme/category chips. (4) Click "Load more".
- Expected: `GET jokes/?page=1&page_size=30` returns `{count,next,previous,results}` with **at most 10 items** (`page_size` ignored — ⚠ documented gap); only `tier_1`, non-removed jokes; each item has `is_locked`; query `q` uses Postgres FTS ranked by relevance; unknown `vibe` → 400 `Unknown vibe`; multiple format chips joined as `joke_format=a,b` return **0 results** (⚠ BE does not comma-split `joke_format`; `tones`/`context_tags` are split); "Load more" requests `page=2`; FlowJokeCards render with setup visible and payoff blurred until reveal; anon reveal path = J-004.
- Pages: `/search` · Endpoints: `jokes/` (list), `vibes/` (chips), `jokes/daily-reads/`.

#### J-004 — Anonymous joke detail + reveal + 10/day cookie soft-wall
- Actor: Anonymous · **P0** · Local: yes
- Pre: fresh cookie jar.
- Steps: (1) Open `/jokes/<id>?source=search`. (2) Reveal punchline on card (in feed or detail). (3) Repeat for 10 distinct jokes. (4) Open an 11th unseen joke. (5) Open one of the first 10 again. (6) Clear cookies / wait past midnight UTC.
- Expected: `GET jokes/<id>/?source=search` returns full joke (`is_locked:false`), sets `Set-Cookie: jf_anon_reads` (signed, HttpOnly, 48h, date-scoped); `GET jokes/daily-reads/` → `{limit:10, used:n, remaining:10-n, over:false, reset_at:<next midnight UTC ISO>}`; feed reveal calls `POST jokes/<id>/reveal/` → 200 with counters (`used` increments only for new ids); after 10 distinct ids `over:true`; 11th unseen joke → `is_locked:true`, `punchline:null`, `lines:null` (`text:null` for oneliner/story/observ), `setup` kept, media dims-only, no cookie append; already-consumed joke stays unlocked; detail page locked hero CTA → `/register` (anon); `DailyReadsNudge` is **authed-only** so anon sees only the card-level lock; tampered/yesterday cookie → ledger treated as empty (`used:0`, never 500); clearing cookies resets the cap (⚠ soft wall by design, R-SEC-6); JSON-LD on the detail page never contains a locked punchline; anon cap is hard-coded 10 (not plan-driven).
- Pages: `/jokes/:id`, `/search` · Endpoints: `jokes/<id>/`, `jokes/<id>/reveal/`, `jokes/daily-reads/`, `jokes/<id>/reactions/` (GET, `my_reaction:null`).

#### J-005 — Anonymous trending page
- Actor: Anonymous · **P1** · Local: yes
- Steps: (1) GET `/trending`. (2) Switch period 24h/week/month.
- Expected: `GET jokes/trending/?period=today|week|month` → paginated `{rank, joke, likes, shares, comments:0, trending_since}` for jokes with recent likes/shares/saves (empty on a cold DB — test data must seed ratings/shares); `tags/trending/`, `tags/rising/`, `themes/popular/`, `users/top-jokesters/` each `{results:[...]}`; no email addresses in any name field; `avatar_url` always null on jokesters; `growth_percent` always 0 on trending tags. ⚠ Trending ignores block relationships and tiers only via list serializer (aggregate).
- Pages: `/trending` · Endpoints: `jokes/trending/`, `tags/trending/`, `tags/rising/`, `themes/popular/`, `users/top-jokesters/`.

#### J-006 — Anonymous daily joke page
- Actor: Anonymous · **P1** · Local: yes
- Steps: (1) GET `/daily`.
- Expected: `GET daily-jokes/today/` → `{joke, date}` with a random tier_1 joke, `is_locked:false` (no paywall context), **no** `issue_label`/`id`/`delivered_at` for anon; history section hidden or empty (history is auth-only → 401 swallowed); save button → `/login`. `<Seo>` present.
- Pages: `/daily` · Endpoints: `daily-jokes/today/`, `daily-jokes/history/` (401 anon).

#### J-007 — Anonymous visits protected route
- Actor: Anonymous · **P0** · Local: yes
- Steps: (1) GET `/favorites?x=1` (or any ProtectedRoute: `/profile`, `/settings`, `/settings/billing`, `/collections`, `/create`, `/create/insights`, `/flow`, `/flow-canvas`, `/explore`). (2) Log in.
- Expected: spinner while `isLoading`; then `<Navigate to="/login?returnTo=%2Ffavorites%3Fx%3D1" replace/>`; after successful login `LoginPage` navigates to `returnTo` (`/favorites?x=1`); with no `returnTo` → `/flow-canvas`. ⚠ `GuestOnlyRoute` does not validate `returnTo` (client-side only; low risk).
- Pages: any protected route, `/login`.

#### J-008 — Anonymous visits `/library`
- Actor: Anonymous · **P2** · Local: yes
- Steps: (1) Tap "Library" in the mobile bottom tab bar (or GET `/library`) while logged out.
- Expected (product-sane): a sign-in prompt or redirect. **Current code**: route is public, `LibraryPage` calls `useCollections`/`useSavedJokes` unconditionally → `GET collections/`, `GET saved-jokes/` return 401 → empty/erroring page (⚠ documented gap; pipeline should assert no crash and file the UX defect).
- Pages: `/library` · Endpoints: `collections/`, `saved-jokes/` (401).

#### J-009 — Legal pages, `/cookies` alias, consent banner
- Actor: Anonymous · **P1** · Local: yes
- Steps: (1) Fresh browser, load any page. (2) Click "Cookie policy" link in banner. (3) Accept or Reject. (4) Reload. (5) GET `/privacy`, `/terms`, `/cookie-policy`, `/childrens-privacy`, `/cookies`.
- Expected: `ConsentBanner` (region named /cookie consent/) shows when `localStorage.jokesfor-consent` is absent; cookie-policy link is a plain `<a href="/cookie-policy">`; Accept writes `{version:1, analytics:true, ts}` and calls `initAnalytics()` **only if** the current user is an adult (≥18 DOB) — anon accept never initializes Firebase; Reject writes `analytics:false`; banner hidden on reload; `/cookies` → `/cookie-policy` (replace); each legal page renders via `LegalDocPage` with `<Seo>`. ⚠ All four docs render a "DRAFT — pending counsel review" banner (R-CMP-1) — the launch-gate test "no DRAFT text" is expected to fail today. ⚠ Analytics never re-initializes on later loads even with stored consent (R-CMP-8). ⚠ FlowAppShell pages carry no legal links (R-CMP-6).
- Pages: `/privacy`, `/terms`, `/cookie-policy`, `/childrens-privacy`, `/cookies`.

#### J-010 — Unknown path and legacy redirects
- Actor: Anonymous · **P2** · Local: yes
- Steps: GET `/does-not-exist`; GET `/submit`, `/drafts`, `/onboarding`, `/cookies`.
- Expected: `NotFoundPage` for unknown; `/submit`→`/create/new`, `/drafts`→`/create`, `/onboarding`→`/flow`, `/cookies`→`/cookie-policy` (all `replace`); on Firebase Hosting every deep route returns `index.html` with HTTP 200 (SPA rewrite) — so HTTP status is 200 even for the 404 page (⚠ SEO nuance). `/create/new/setup` resolves to EditorPage new-mode (not captured by `:draftId`).
- Pages: `*`, redirects.

#### J-011 — Bot fetches share page for a tier_1 joke
- Actor: Search/social bot · **P1** · Local: yes (share card PNG needs cairo; local media URL 404s)
- Pre: live tier_1 joke with `share_image` (run `backfill_share_cards --apply` locally with `DYLD_FALLBACK_LIBRARY_PATH`).
- Steps: (1) `GET /jokes/<id>/share/` with a scraper UA (no JS).
- Expected: 200 `share.html`; `og:title` = first 60 chars of setup-or-text, `og:description` ≤160 chars, **never the punchline in meta/JSON-LD**; `og:image` = absolute `share-cards/joke-<id>.png` with 1200×630; `og:url` and `<link rel=canonical>` = `FRONTEND_URL/jokes/<id>`; Twitter `summary_large_image`; JSON-LD `CreativeWork` with escaped `<>&`; `<meta http-equiv=refresh>` + `location.replace` bounce humans to the SPA; media jokes embed the poster/image derivative in the card (never the mp4; audio → text card with "Audio" badge); non-GET → 405. ⚠ For two-part text jokes the HTML **body** renders `joke.text` = "setup punchline" (punchline visible to body-reading scrapers). ⚠ Prod: ~300 seed jokes have blank `share_image` until backfill is run (R-OPS-10) → `og:image` absent.
- Endpoints: `/jokes/<id>/share/`.

#### J-012 — Bot fetches share page for tier_2 / removed / missing joke
- Actor: Bot · **P1** · Local: yes
- Steps: GET `/jokes/<tier2_id>/share/` anonymously; GET `/jokes/<removed_id>/share/`; GET `/jokes/999999/share/`.
- Expected: tier_2 (or tier_3) → 200 `share_redirect.html`: only meta-refresh/JS redirect to `FRONTEND_URL/jokes/<id>`, `robots noindex`, no OG image/description/JSON-LD/text; removed or nonexistent → 404 (default manager). Adult opted-in viewer (needs `show_mature`, admin-only) gets the full page.
- Endpoints: `/jokes/<id>/share/`.

#### J-013 — Sitemap / robots / FE prebuild
- Actor: Bot · **P1** · Local: partial
- Steps: (1) `GET /sitemap.xml` on backend. (2) `GET https://jokesforfront.web.app/robots.txt`, `/sitemap.xml`. (3) `npm run build` on FE.
- Expected: BE sitemap = `application/xml` urlset whose every `<loc>` starts with `FRONTEND_URL`; static routes `/`, `/daily`, `/trending`, 4 legal pages; `/jokes/<id>` only for non-removed tier_1 (cap 20000, `lastmod=updated_at`); `/creators/<id>` only for creators with ≥1 attributed live tier_1 joke; `/packs/<slug>` only for published packs within window; POST → 405. FE `robots.txt` disallows private routes and points at `https://jokesforfront.web.app/sitemap.xml`; prebuild `gen-sitemap.mjs` fetches `<VITE_API_URL origin>/sitemap.xml` and writes `public/sitemap.xml`, **fail-soft** (warning, exit 0) when unreachable. ⚠ Hosted sitemap is stale between FE deploys by design.
- Prod-only: hosted `/sitemap.xml` on Firebase reflects the last build; Search Console submission is an owner action.
- Endpoints: `/sitemap.xml`; FE `public/robots.txt`.

#### J-014 — Reader shares a joke
- Actor: Anonymous or Free reader · **P2** · Local: yes
- Steps: (1) On a FlowJokeCard or `/jokes/:id`, click Share/Copy link.
- Expected: clipboard gets `{BACKEND_ORIGIN}/jokes/<id>/share/`; in real mode + authenticated, `POST jokes/<id>/share/ {platform:'copy'}` fires (fire-and-forget) → 201 `{status:'recorded', share_url, joke_id}` and a `ShareEvent` row; anonymous POST also allowed (user null) but FE only fires it when authenticated; unknown platform → stored as `other`. Share counts feed trending and creator insights `shares_breakdown`.
- Endpoints: `jokes/<id>/share/`.

### Authentication / account

#### J-020 — Email registration (gated) → verify → onboarding
- Actor: New registrant · **P0** · Local: yes (console email prints `Your code: NNNNNN`)
- Pre: `EMAIL_VERIFICATION_REQUIRED=true` (prod), fresh email.
- Steps: (1) GET `/register` (GuestOnlyRoute). (2) Fill email, password ×2, DOB (≥13), optional step-2 fields. (3) Submit. (4) Land on `/verify-email?email=<email>`. (5) Enter the 6-digit code. (6) Land on `/flow`.
- Expected: `POST auth/registration/ {email,password1,password2,date_of_birth}` → 201 `{detail:'Verification code sent to your email.', email}`; **no** JWT cookies, no `access`; user `is_active=False`, `username=email`, `profile.date_of_birth` stored; signal creates `UserPreference`, `UserProfile`, default "Favorites" collection; one `EmailVerification` row (sha256 code, TTL 10 min) and one `EmailMessageLog(template=verification_code, status=sent)`; audit `registration` success; FE does **not** set auth state and navigates to `/verify-email?email=…`; `/verify-email` without `?email=` → `/register`. `POST auth/verify-email/ {email, code}` → 200 `{user:{id,email}}` + `Set-Cookie` both JWT cookies (no `access` in body); FE then `POST auth/token/refresh/` → access token, `GET auth/user/`, optional `PATCH auth/user/` with first name from `location.state`, `setAuth`, navigate `/flow`. Terms/Privacy acceptance is copy-only (no consent record server-side — ⚠ known). Client-side DOB check shows "You must be at least 13 years old to use Jokes For." before any request.
- Pages: `/register`, `/verify-email`, `/flow` · Endpoints: `auth/registration/`, `auth/verify-email/`, `auth/token/refresh/`, `auth/user/`, `auth/csrf/`.

#### J-021 — Registration rejected
- Actor: New registrant · **P0** · Local: yes
- Steps: submit with (a) DOB 12 years ago, (b) DOB today/future, (c) DOB missing, (d) email already registered (any case), (e) password mismatch, (f) weak password.
- Expected: (a) 400 `{date_of_birth:['You must be at least 13 years old to use Jokes For.']}` and **no user row**; FE shows inline error, no navigation, no OAuth redirect; (b) 400 `['Enter a valid date of birth.']`; (c) 400 `['This field is required.']`; (d) 400 `{email:['A user is already registered with this e-mail address.']}` (enumerating by design); (e) 400 `{password2:["The two password fields didn't match."]}`; (f) 400 `{password1:[...]}` from Django validators (min 8, common, numeric, similarity). Exactly-13 succeeds.
- Endpoints: `auth/registration/`.

#### J-022 — Verify-email failure modes
- Actor: Unverified · **P1** · Local: yes
- Steps: (1) Wrong code ×5 then correct. (2) Wait >10 min then submit. (3) Unknown email. (4) Non-6-digit code. (5) Resend 4× within 15 min. (6) Verify an already-active email.
- Expected: wrong → 400 `{code:['Incorrect code.']}` with `attempts+1`; 6th attempt (even correct) → 429 `{detail:'Too many attempts. Request a new code.'}`; expired → 400 `['This code has expired. Request a new one.']`; unknown email → same 400 `Incorrect code.` shape (anti-enumeration); bad pattern → 400 field error on `code`; resend → always 200 `{detail:'If that email needs verification, a new code has been sent.'}`, emails only inactive users, invalidates prior codes, 4th within 15 min → 429 regardless of case/whitespace variants; already active → 400 `{detail:'This email is already verified. Please log in.'}` and FE routes to `/login`. FE treats 429 as locked-until-resend. ⚠ Resend does not catch `EmailSendError` → 500 if provider down (gap #1 in be-auth-session).
- Endpoints: `auth/verify-email/`, `auth/resend-verification/`.

#### J-023 — Registration email send failure
- Actor: New registrant · **P2** · Local: yes (fault-inject backend)
- Steps: register while the mail backend raises; then resend.
- Expected: 502 `{detail:"We couldn't send your code right now…", email}`; inactive user + unconsumed code exist; audit `registration` failure `email_send_failed`; FE → `/verify-email?email=…&sendFailed=1`; resend later recovers the account.
- Endpoints: `auth/registration/`, `auth/resend-verification/`.

#### J-024 — Unverified user tries to log in
- Actor: Unverified · **P1** · Local: yes
- Expected: `POST auth/login/` → 400 `{non_field_errors:['Unable to log in with provided credentials.']}` (allauth backend rejects inactive; the "User account is disabled." branch is unreachable per be-auth-session; local-dev-runbook claims the latter — **assert on 400 + non_field_errors, not the exact message**); no cookies; audit `login` failure with hashed identifier; password reset ignores inactive users (200, no email).
- Endpoints: `auth/login/`.

#### J-025 — Login, returnTo, logout
- Actor: Free reader · **P0** · Local: yes (`demo.creator@jokesfor.dev` / `DemoCreator!2026` after seed)
- Steps: (1) `/login` → email+password → submit. (2) Observe navigation. (3) ProfileMenu → Logout.
- Expected: `POST auth/login/ {email,password}` → 200 `{access, refresh:'', user:{pk,username,email,first_name,last_name,date_of_birth}}` + `Set-Cookie jokes-access-token` (15 min) and `jokes-refresh-token` (1 day, Path=/, HttpOnly, Secure in prod, SameSite=None in prod / Lax locally); FE `setAuth`, refetches CSRF, navigates to `returnTo` or `/flow-canvas`; wrong password → 400 same message + audit failure; `/login` while authenticated → redirect (GuestOnlyRoute). Logout: `POST auth/logout/` (Bearer + CSRF header + refresh cookie) → 200 `{detail:'Successfully logged out.'}`, both cookies cleared, refresh token blacklisted; FE clears store + query cache and navigates `/`; subsequent `POST auth/token/refresh/` with the old cookie → 401 blacklisted. Without refresh cookie logout → 401 `Refresh token was not included in cookie data.` (cookies still cleared). ⚠ API login success is not audited and `last_login` never updates (SESSION_LOGIN=False).
- Pages: `/login`, `/flow-canvas`, `/` · Endpoints: `auth/login/`, `auth/logout/`, `auth/csrf/`.

#### J-026 — Session persistence and refresh
- Actor: Free reader · **P0** · Local: yes
- Steps: (1) Log in, reload tab. (2) Open a new tab. (3) Let 15 min pass (or forge expired access), call an API. (4) Replay an old refresh token.
- Expected: reload → Zustand rehydrates `jokesfor-auth` from sessionStorage synchronously (`isAuthenticated` true, Bearer attached immediately), then `AuthProvider` does `GET auth/csrf/` → `POST auth/token/refresh/` (cookie) → `GET auth/user/` and overwrites user/token; new tab (no sessionStorage) → same bootstrap from the refresh cookie → authenticated; no cookie → `isLoading=false`, anonymous, no retry loop. Expired access → 401 → single-flight `POST auth/token/refresh/` (concurrent 401s queued, one refresh), originals replayed with new Bearer; refresh → 200 `{access, access_expiration}` (no `refresh` in body), rotated cookies; reused/rotated refresh → 401 `Token is blacklisted`; refresh failure clears the in-memory token but ⚠ **does not** clear the store/redirect (user appears logged in with dead token until explicit logout — known gap). Deactivated user with valid access → 401 `user_inactive`.
- Endpoints: `auth/token/refresh/`, `auth/user/`, `auth/csrf/`.

#### J-027 — Google OAuth sign-up (new user)
- Actor: New registrant · **P1** · Local: **no** (Google consent screen, real code exchange)
- Pre: `VITE_GOOGLE_CLIENT_ID`; BE `SocialApp` client id matches (`setup_social_app`); `GOOGLE_OAUTH_CALLBACK_URL` == SPA redirect URI.
- Steps: (1) `/register` → enter DOB ≥13 → "Continue with Google". (2) Google consent. (3) Redirect to `/auth/google/callback?code=…`. (4) Land on `/flow` (stashed returnTo).
- Expected: FE stashes DOB in `sessionStorage.auth.signupDob` and returnTo `/flow`; callback page POSTs exactly once (StrictMode-safe) `auth/google/ {code, redirect_uri, date_of_birth}`; BE ignores body `redirect_uri` (uses `GOOGLE_OAUTH_CALLBACK_URL`); new user created **active immediately** (no email verification), unusable password, DOB persisted, `SocialAccount` linked; 200 `{access, refresh:'', user}` + cookies; navigate to returnTo. Google users skip J-020's verification.
- Pages: `/register`, `/auth/google/callback`, `/flow` · Endpoints: `auth/google/`.
- Prod-only: Google account + consent UI; local can only assert bogus code → 400.

#### J-028 — Google OAuth edge cases
- Actor: New registrant / Free reader · **P1** · Local: partial (bogus code → 400; other branches need a valid code)
- Cases & expected: existing linked Google user without DOB → 200 login, DOB unchanged; new identity **without DOB** → 400 `{code:'dob_required', detail}` and no User/SocialAccount rows → FE sends to `/register` with notice, code not reused; DOB <13 → 400 `{date_of_birth:[…]}` and no rows; `?error=access_denied` → "Sign-in cancelled…" with links to `/login` and `/`; local email/password account with the same email → 400 `{non_field_errors:['User is already registered with this e-mail address.']}` (⚠ product decision: no auto-link); neither code nor access_token → 400; bogus code → 400 `Failed to exchange code…`. Login page path clears any stashed DOB.
- Endpoints: `auth/google/`.

#### J-029 — Forgot / reset password
- Actor: Free reader · **P1** · Local: yes (`FRONTEND_URL=http://localhost:5173`, console email)
- Steps: (1) `/forgot-password` → email → submit. (2) Open emailed link `/reset-password?uid=…&token=…`. (3) Set new password. (4) Log in with it.
- Expected: `POST auth/password/reset/ {email}` → 200 `{detail:'Password reset e-mail has been sent.'}` for known, unknown and inactive emails alike (email sent only for active); link = `FRONTEND_URL/reset-password?uid=<b36>&token=<key>` (never `/password/reset/confirm`); `ForgotPasswordPage` branches on `uid&token`; `POST auth/password/reset/confirm/ {uid,token,new_password1,new_password2}` → 200; bad token → 400 `{token:['Invalid value']}`; token valid 3 days; old password no longer works; ⚠ other sessions are **not** revoked (no blacklist on reset).
- Pages: `/forgot-password`, `/reset-password`, `/login` · Endpoints: `auth/password/reset/`, `auth/password/reset/confirm/`, `auth/login/`.

#### J-030 — Change password in Settings
- Actor: Free reader · **P1** · Local: yes
- Expected: `POST auth/password/change/ {old_password,new_password1,new_password2}` → 200 `{detail:'New password has been saved.'}`; missing/wrong old → 400 `{old_password:[…]}`; cookie-auth needs `X-CSRFToken`; existing refresh tokens keep working (`LOGOUT_ON_PASSWORD_CHANGE=False`).
- Pages: `/settings` · Endpoints: `auth/password/change/`.

#### J-031 — CSRF enforcement (cookie path) vs Bearer bypass
- Actor: Free reader (API contract) · **P0** · Local: yes
- Steps: (1) `GET auth/csrf/`. (2) Cookie-only POST without header. (3) Same with header. (4) Bearer POST without header. (5) Cookie POST with foreign `Origin`.
- Expected: `GET auth/csrf/` → 200 `{csrfToken}` + `csrftoken` cookie; cookie-only mutation without `X-CSRFToken` → 403 `{detail:'CSRF Failed: …'}`; with matching header+cookie → 2xx; Bearer header → no CSRF check ever; foreign Origin over HTTPS → 403 `Origin checking failed`; `auth/token/refresh/`, `auth/token/verify/`, `auth/csrf/`, `email/unsubscribe/`, `internal/run-digests/`, `billing/webhook` are never CSRF-checked; FE interceptor on 403 containing "CSRF" refetches the token and replays **exactly once**. Prod depends on `JWT_COOKIE_SAMESITE=None` (R-SEC-3).
- Endpoints: `auth/csrf/`, any mutating endpoint (e.g. `jokes/<id>/reveal/`, `auth/user/` PATCH).
- Prod-only: cross-site (`Origin: https://jokesforfront.web.app`) + `Secure; SameSite=None` cookies only meaningful over HTTPS cross-eTLD+1.

#### J-032 — Rate limits
- Actor: Anonymous · **P2** · Local: yes (`cache.clear()` to reset)
- Expected: 101st anonymous DRF request from one IP within an hour → 429 `{detail:'Request was throttled…'}` with `Retry-After` (applies to login, register, jokes, even Stripe webhook); authenticated 1001st → 429; scoped: `media-upload` 30/h, `appeals` 10/day, `tips-checkout` 30/h, `creator_insights` 120/h, `verification_resend` 3/15min per email; counters in DB cache table `jokesfor_cache` (shared across instances); no `X-RateLimit-*` headers. ⚠ Login brute-force protection is only the 100/h IP throttle (`throttle_scope='dj_rest_auth'` inert). ⚠ No scoped throttles on reports/reactions/favorites/reveal.
- Endpoints: any.

#### J-033 — Legacy ungated registration
- Actor: New registrant · **P2** · Local: yes (`EMAIL_VERIFICATION_REQUIRED=false`)
- Expected: `POST auth/registration/` → 201 `{access, refresh, user}` (⚠ refresh in body here, unlike login) + both cookies; user active; FE detects `'access' in data`, logs in, navigates `/flow`.

### Onboarding / preferences / profile

#### J-040 — Onboarding `/flow`
- Actor: Free reader (just verified) · **P0** · Local: yes
- Steps: (1) Step 1 pick vibes; try Continue with 2 selected, then with 3+. (2) Step 2 pick ≥1 format. (3) Step 3 ritual (notification time/days, streak-saver toggle). (4) Finish.
- Expected: `GET vibes/` returns an unpaginated array of active vibes; <3 selected → error "Pick at least 3 vibes to continue." and no request; ≥3 → `PUT users/me/vibes/ {slugs}` → 200 array of `{vibe, weight, created_at}` (3–12 slugs; unknown slug → 400); step 2 requires ≥1 format (client-only); Finish → `PATCH users/me/preferences/` including `onboarding_completed:true` then navigate `/flow-canvas` (replace). ⚠ BE `UserPreferencesView` only persists `humor_types`, `notifications{}`, `privacy{}`, `theme`; `onboarding_completed`, `notification_time`, `streak_saver_enabled`, `tones` sent by FE are **silently dropped** (fe-data-layer finding 7); `POST preferences/complete-onboarding/` exists but FE never calls it; the streak-saver toggle is visual-only (R-FE-4). No onboarding-complete guard exists, so nothing blocks the app if skipped.
- Pages: `/flow`, `/flow-canvas` · Endpoints: `vibes/`, `users/me/vibes/` (GET/PUT), `users/me/preferences/` (PATCH), `formats/`.

#### J-041 — Onboarding skip / revisit
- Actor: Free reader · **P2** · Local: yes
- Expected: Skip on any step → `/flow-canvas` (replace) without saving; `/onboarding` → `/flow`; revisiting `/flow` shows current vibes from `GET users/me/vibes/`.

#### J-042 — Settings: preferences, identity, blocked users
- Actor: Free reader · **P1** · Local: yes
- Steps: (1) `/settings`. (2) Edit display name (60 chars) and handle. (3) Toggle notification/privacy prefs, theme. (4) View blocked users, unblock one. (5) Follow link to `/settings/billing`.
- Expected: `GET users/me/profile/` → `{name, username, display_name, handle, email, bio, avatar_url, member_since, is_premium, stats{jokes_saved,jokes_shared,collections,days_active}, humor_dna[]}`; `PATCH users/me/profile/` → display_name truncated to 50; handle must match `^[a-z0-9_]{3,30}$` else 400; taken handle → 400 `That handle is already taken.`; `""` clears handle; `GET/PATCH users/me/preferences/` → `{humor_types, notifications{daily_joke,trending_alerts,collection_updates,email_digest}, privacy{public_profile,show_activity,share_analytics}, theme}`; `GET users/me/blocks/` → `{results:[{id,name,username,avatar_url}]}`; `DELETE users/<id>/block/` → 204 idempotent + audit `unblock`. ⚠ `notifications.email_digest` writes `UserPreference.notification_email_digest`, which the digest engine **does not read** (it reads `UserProfile.email_digest_opt_in`, default True) — the in-app toggle does not control digest emails. ⚠ No avatar upload endpoint. ⚠ DOB and email are immutable (no API).
- Pages: `/settings` · Endpoints: `users/me/profile/`, `users/me/preferences/`, `users/me/blocks/`, `users/<id>/block/` (DELETE).

#### J-043 — Profile page
- Actor: Free reader · **P1** · Local: yes
- Expected: `/profile` shows real stats from `users/me/profile/`, `GET users/me/activity/?limit=8` → `{results:[{id:'rating_N'|'save_N'|'fav_N'|'share_N', type, description, created_at}]}` (⚠ non-numeric `limit` → 500), `GET users/me/achievements/` → all 12 seeded achievements with `unlocked`/`unlocked_at` (requires `seed_achievements`); no fabricated numbers; humor DNA = top 4 tones.
- Pages: `/profile` · Endpoints: `users/me/profile/`, `users/me/activity/`, `users/me/achievements/`.

### Reading / home / ritual

#### J-050 — Today hub `/flow-canvas`
- Actor: Free reader · **P0** · Local: yes (real backend required even in mock mode — many hooks bypass adapters)
- Steps: (1) Land on `/flow-canvas` after login/onboarding. (2) Reveal today's joke. (3) Roll mystery box. (4) Open featured pack. (5) Check streak chip, tomorrow teaser, taste profile, top jokesters, JOTD history, "For You".
- Expected: `GET daily-jokes/today/` (auth) → `{id, joke (never locked), date, delivered_at, created_at, issue_label /^Vol\. [IVX]+ · No\. \d{3}$/}`; `GET daily-jokes/tomorrow/` → `{date, issue_label, preview (≤12 words + …), format}` (404 tolerated); `GET users/me/streak/` → `{current_count,longest_count,last_active_date,freeze_days_available,freezes_used_total,started_at,last_14_days[14],streak_at_risk_today}`; `GET mystery-box/status/` → `{rolls_used_today, rolls_remaining_today, max_per_day:3}`; `GET packs/featured/` (404 when none); `GET users/me/packs/in-progress/` array; `GET users/me/taste-profile/?period=month` → `{period, jokes_read, jokes_saved, peak_read_hour, top_vibe, top_themes, top_categories, top_formats, daily_reads_28d[28]}`; `GET users/top-jokesters/`; `GET jokes/daily-reads/` drives lock state; `DailyReadsNudge` appears when `over:true`. ⚠ `GET daily-jokes/history/` returns a **bare array** but FE reads `.results` → JOTD history grid always empty (fe-data-layer finding 2). ⚠ "For You" `useJokeSearch({vibe, page_size:3})` is never enabled (`hasSearchParams` ignores `vibe`) → fallback copy always shown (finding 3). Both are defects the pipeline should surface.
- Pages: `/flow-canvas` · Endpoints: `daily-jokes/today/`, `daily-jokes/tomorrow/`, `daily-jokes/history/`, `users/me/streak/`, `mystery-box/status/`, `mystery-box/roll/`, `packs/featured/`, `users/me/packs/in-progress/`, `users/me/taste-profile/`, `users/top-jokesters/`, `jokes/daily-reads/`, `jokes/` (For You, never fired), `saved-jokes/` (save).

#### J-051 — Explore with chips
- Actor: Free reader · **P1** · Local: yes
- Expected: `/explore` (protected) builds `GET jokes/?page=1&page_size=30&ordering=-created_at[&joke_format=…][&tones=a,b]`; results ≤10 (cap); single format chip works; **two format chips → 0 results** (⚠ finding 5); category chips (tones) comma-split correctly; cards render via FlowJokeCard with `source="explore"`; opening a card → `/jokes/:id?source=explore`.
- Pages: `/explore` · Endpoints: `jokes/`.

#### J-052 — Search with query
- Actor: Free reader · **P1** · Local: yes
- Expected: `/search?q=coffee` seeds the input; `GET jokes/?q=coffee&page=1&page_size=30` → FTS results ordered by rank; "Load more" bumps `page`; page resets to 1 when query/filters change; authenticated reveals enqueue telemetry `reveal` (no reveal POST) and detail opens log `JokeView(source='search')`.
- Pages: `/search` · Endpoints: `jokes/`.

#### J-053 — Text joke detail (authenticated)
- Actor: Free reader · **P0** · Local: yes
- Steps: (1) Open `/jokes/<id>?source=daily`. (2) React (lol → hmm → hmm again). (3) Save. (4) Report. (5) Share. (6) Stay >1s and navigate away.
- Expected: `GET jokes/<id>/?source=daily` → full `JokeSerializer` (`id,text,setup,punchline,lines,media[],format{},age_rating{},language{},source{},tones[],context_tags[],themes[],categories[],culture_tags[],share_image_url,is_locked,created_at,updated_at`); when delivered unlocked a `JokeView(source='daily')` row is created (60 s debounce per user+joke; unknown source → `other`); JSON-LD `CreativeWork` `url=https://jokesforfront.web.app/jokes/<id>`; `GET jokes/<id>/reactions/` → `{my_reaction, counts{lol,crying,hmm,eyeroll}}`; `POST jokes/<id>/react/ {reaction:'lol'}` → my_reaction lol; `hmm` → switched; `hmm` again → `my_reaction:null` and count decremented; Save → `POST saved-jokes/ {joke}` → 201 (duplicate → 400 `already saved`); Report button (`ReportJokeButton`) → `POST reports/ {joke, reason, description?}` → 201, second while pending → 200 same report; Share → clipboard backend share URL + `POST jokes/<id>/share/`; dwell telemetry enqueued (`useDwell`), reveal telemetry on unlocked mount; tier_2 joke for a minor/non-opted adult → 404; blocked creator's joke → 404. ⚠ Reporting a **removed** joke → 400 (default manager) — acceptable.
- Pages: `/jokes/:id` · Endpoints: `jokes/<id>/`, `jokes/<id>/reactions/`, `jokes/<id>/react/`, `saved-jokes/`, `reports/`, `jokes/<id>/share/`, `telemetry/events`.

#### J-054 — Media joke detail
- Actor: Free reader · **P1** · Local: partial (files written to `./media` but **no `/media/` route** → image/poster URLs 404 in the local browser; use prod GCS or assert JSON only)
- Expected: unlocked media joke → `media:[{kind,url,poster_url,width,height,duration_ms,is_gif}]` in position order; image format shows 1–6 images; video/GIF renders mp4 (`is_gif` → looping, muted, no audio track) with poster; audio renders player; watch telemetry `{type:'watch', watch_ms, watch_pct}` enqueued; locked → `media:[{kind,width,height}]` only (no URLs), `punchline:null`; creator public profile always dims-only; removed joke → 404 / `media:[]`. Share card for media jokes embeds the derivative/poster.
- Pages: `/jokes/:id` · Endpoints: `jokes/<id>/`, `telemetry/events`.
- Prod-only: GCS public URLs; real `storage.googleapis.com` serving.

#### J-055 — Free reader paywall
- Actor: Free reader · **P0** · Local: yes (freezegun-style: seed 10 `JokeView` rows or open 10 jokes)
- Steps: (1) Open 9 distinct jokes → check daily-reads. (2) Open the 10th. (3) Open an 11th unseen joke; also view feed cards. (4) Re-open one of the 10. (5) Click the locked CTA. (6) Cross midnight UTC.
- Expected: `GET jokes/daily-reads/` → `{limit:10, used:n, remaining:10-n, over:false, reset_at:<next 00:00 UTC ISO>}` exactly those keys; after 10 distinct detail opens/reveals `over:true, remaining:0`; 11th joke `is_locked:true` with stripped payoff and dims-only media, **no** JokeView logged; feed/list/random/trending/saved/favorites/collections/packs/mystery/recently-viewed all inject paywall state; already-consumed jokes stay unlocked; FlowJokeCard soft-locks unrevealed cards when `remaining<=0` (optimistic decrement, session `revealedIds`, reconciled on refetch); `DailyReadsNudge` shows linking to `/settings/billing`; detail-page CTA → `/settings/billing` (authed); daily editorial joke (`daily-jokes/today/`) stays unlocked; telemetry `reveal` also consumes a read (creates JokeView); after midnight UTC `used:0` and previously locked jokes unlock; admin edit of free plan `free_joke_reads_per_day` changes cap without deploy; `limit:null`/404 from daily-reads → FE shows no paywall UI. ⚠ `past_due`/`canceled` subscribers are treated as free immediately (product decision to confirm).
- Pages: `/flow-canvas`, `/search`, `/jokes/:id`, `/settings/billing` · Endpoints: `jokes/daily-reads/`, `jokes/<id>/`, `jokes/`, `telemetry/events`.

#### J-056 — Paid reader
- Actor: Paid reader · **P1** · Local: yes via DB (create `Subscription(status='active', plan=supporter)`); end-to-end via Stripe is J-111
- Expected: `GET jokes/daily-reads/` → `{limit:null, used:n, remaining:null, over:false, reset_at}`; 50+ JokeViews today still `is_locked:false`; `GET billing/entitlements` → `plan:'supporter'`, `limits.free_joke_reads_per_day:null`, `mystery_box_rolls_per_day:10`, `daily_joke_history_days:90`; `GET billing/my-subscription` → `status:'active'`; `users/me/profile/.is_premium:true`; mystery box 429 only after 10 rolls (creator_pro 20); history back to 90 days. ⚠ FE mystery-box roll caches `max_per_day:3` regardless of plan until next status fetch.
- Endpoints: `jokes/daily-reads/`, `billing/entitlements`, `billing/my-subscription`, `mystery-box/roll/`, `daily-jokes/history/`.

#### J-057 — Daily joke (authenticated)
- Actor: Free reader · **P1** · Local: yes
- Expected: `GET daily-jokes/today/` twice same day → same joke id, `delivered_at` set after first call, `issue_label` present; joke never locked even when over cap; joke selected within allowed tiers via `get_personalized_joke`; regenerated if the joke was removed; `GET daily-jokes/tomorrow/` lazily creates tomorrow's row (401 anon); `GET daily-jokes/history/` → **bare array** limited to `daily_joke_history_days` (free 30) excluding removed jokes (⚠ no tier filter / no paywall context on history); `/daily` save button → `POST saved-jokes/`. ⚠ FE `/daily` history grid empty (finding 2).
- Pages: `/daily`, `/flow-canvas` · Endpoints: `daily-jokes/today/`, `daily-jokes/tomorrow/`, `daily-jokes/history/`, `saved-jokes/`.

#### J-058 — Mystery box
- Actor: Free reader · **P1** · Local: yes
- Expected: `POST mystery-box/roll/` → 200 `{joke (paywall ctx), rolls_remaining_today:2, source_vibe|null}` + `MysteryBoxRoll` row; pool = caller's vibes' recipes ∩ allowed tiers − blocked creators − rolled today − saved; 4th roll → 429 `{detail, rolls_used_today:3, rolls_remaining_today:0, max_per_day:3}`; empty pool → 404; status reflects `rolls_used_today`; resets next UTC day.
- Pages: `/flow-canvas` · Endpoints: `mystery-box/status/`, `mystery-box/roll/`.

#### J-059 — Streak
- Actor: Free reader · **P1** · Local: yes (time control via DB)
- Expected: first `JokeView` of the day → `current_count+1`, `StreakDay(today,'read')`, `last_active_date=today`; second view same day → unchanged; gap of N days with freezes available → gap days `frozen`, freezes decremented, count continues; without freezes → `missed`, count resets to 1; new calendar month → `freeze_days_available=2`; `POST users/me/streak/freeze/` → 400 if 0 freezes or already read today, else today `frozen`; `POST users/me/streak/freeze/remove/` refunds; second remove → 400 `No freeze to remove for today.`; `streak_at_risk_today` true when not read today and hour ≥20 UTC; FlowAppShell streak chip visible on desktop when `current_count>0`, hidden at ≤1023px. ⚠ FE `useFreezeStreak/useUnfreezeStreak` hooks are unused by pages (freeze UI absent).
- Endpoints: `users/me/streak/`, `users/me/streak/freeze/`, `users/me/streak/freeze/remove/`.

#### J-060 — Packs
- Actor: Free reader (list/detail also anon) · **P1** · Local: yes (4 seeded packs)
- Expected: `GET packs/` lists only `is_published` within `publish_at/expires_at` window with `user_progress` (null anon); `GET packs/<slug>/` embeds `jokes:[{order, joke}]` filtered by tier and `is_removed=False`, paywall ctx applied; `GET packs/featured/` first featured or 404; `/packs/:slug` "Start" navigates to `/jokes/<first>?source=pack`; `POST packs/<slug>/progress/ {entry_order}` → `{last_read_entry, completed_at, is_complete}` (max order → complete; lower → clears; -1 → 400; unpublished → 404); `GET users/me/packs/in-progress/` lists started-unfinished packs and drops completed ones; sitemap lists published packs. ⚠ FE ignores the progress response body and its `PackProgress` type differs (harmless).
- Pages: `/packs/:slug`, `/flow-canvas`, `/jokes/:id?source=pack` · Endpoints: `packs/`, `packs/<slug>/`, `packs/featured/`, `packs/<slug>/progress/`, `users/me/packs/in-progress/`.

#### J-061 — Reactions
- Actor: Free reader · **P1** · Local: yes — see J-053; anonymous POST → 401; invalid reaction → 400 `{error}`; counts feed creator insights `reactions_breakdown` and digest milestones.

#### J-062 — Rating like/dislike (API-only)
- Actor: Free reader · **P2** · Local: yes
- Expected: `POST jokes/<id>/rate/ {rating:1}` → 200 `{rating:1, created:true, joke_score}`; `-1` → `created:false`; `2` → 400 `{error:'Rating must be 1 (like) or -1 (dislike)'}`; `GET jokes/<id>/my-rating/` → `{rating:null, joke_score}` when none; anon → 401. Likes drive trending and `tags/trending`. FE defines but never calls these.

#### J-063 — Favorites
- Actor: Free reader · **P1** · Local: yes
- Expected: `POST favorites/ {joke}` → 201 full `{id, joke{…}, favorited_at}`; duplicate → 400; `GET favorites/?tones=puns&ordering=-popularity` filtered by tier/removed with paywall ctx; `GET favorites/stats/` → `{total_count, top_tone, this_week_count}`; `DELETE favorites/<id>/` → 204; FE remove = `GET favorites/` then DELETE by favorite id (⚠ silently skipped if not on page 1); removed jokes vanish from the list.
- Pages: `/favorites` · Endpoints: `favorites/`, `favorites/<id>/`, `favorites/stats/`.

#### J-064 — Saved jokes and collections
- Actor: Free reader · **P1** · Local: yes
- Steps: (1) `/collections` → create "Puns". (2) Create "Puns" again. (3) Save a joke into it; save again. (4) Save the same joke to a collection owned by another user. (5) Open `/collections/:id`. (6) Delete the default Favorites collection. (7) `/library` search saved. (8) Unsave.
- Expected: `POST collections/ {name}` → 201; duplicate name → 400 `You already have a collection with this name.`; `POST saved-jokes/ {joke, collection, note?}` → 201; duplicate → 400 `This joke is already saved in this collection.`; foreign collection → 400 `{collection:[…]}`; `GET collections/<id>/jokes/` paginated with paywall ctx and tier/removed filters; `DELETE collections/<id>/` of `is_default` → 400 `Cannot delete the default Favorites collection.`; `GET saved-jokes/search/?q=` (missing → 400); `DELETE saved-jokes/<id>/` → 204; `GET collections/trending/` (anon OK) never leaks emails. ⚠ `GET saved-jokes/` plain list has no tier filter (tier_2 saved earlier stays visible).
- Pages: `/collections`, `/collections/:id`, `/library` · Endpoints: `collections/`, `collections/<id>/`, `collections/<id>/jokes/`, `saved-jokes/`, `saved-jokes/<id>/`, `saved-jokes/search/`, `collections/trending/`.

#### J-065 — Recently viewed (API)
- Actor: Free reader · **P2** · Local: yes
- Expected: `GET users/me/recently-viewed/?limit=20` → array `{joke (paywall ctx), source, revealed_punchline, viewed_at}` newest first, tier/removed filtered, `limit` max 100 (non-int → 20). FE hook `useRecentlyViewed` exists but no page uses it.

#### J-066 — Content-tier gating
- Actor: Anonymous / minor / adult / Staff · **P1** · Local: yes (admin toggle needs superuser)
- Expected: anon, DOB-null user, 17-year-old, or adult with `show_mature=False` → only `tier_1` on every read path (`jokes/`, detail 404 for tier_2, random, trending, saved search, favorites, collections, packs, mystery box, recently viewed, daily selection, creator profile, share page redirect shell, sitemap); adult (`profile.is_adult`) + `show_mature=True` → tier_1+tier_2; `tier_3` never served; UGC published with `age_rating.min_age>=18` becomes `tier_2`. ⚠ **`show_mature` has no API/UI — only Django admin `UserPreferenceAdmin` can enable it**, so tier_2 UGC is effectively invisible to all API users in prod (be-compliance finding 1). ⚠ DOB immutable after signup.
- Endpoints: all read endpoints; `/admin/jokes/userpreference/`.

#### J-067 — Audience telemetry
- Actor: Free reader (adult, consented, real mode) · **P1** · Local: yes
- Steps: (1) Accept analytics consent as an adult. (2) Scroll 10 cards. (3) Reveal, dwell >1s, watch a video. (4) Hide the tab.
- Expected (contract): `POST telemetry/events` (no trailing slash, Bearer) with `{events:[{joke,type,source,value?,scroll_pct?,watch_ms?,watch_pct?}]}` ≤50 → 202 `{accepted:N}`; impressions deduped per user/joke/day; `reveal` sets `revealed_punchline` (creates JokeView → consumes a read); dwell <500 ms dropped, clamped to 600000; watch same clamps; float `value` skipped; anon → 401. Gate: real mode AND token AND authed AND adult AND `consent.analytics`; minors/anon/non-consenting send nothing. ⚠ **Prod expectation: FE prefers `navigator.sendBeacon` on every flush → no Authorization/X-CSRFToken → cookie path → 403 CSRF → events silently lost** (fe-data-layer finding 1). The pipeline should assert both the BE contract (via fetch/Bearer) and the observed beacon 403.
- Endpoints: `telemetry/events`.

### Social / creators / tips / inbox

#### J-070 — Creator profile + follow
- Actor: Free reader (viewer) + Anonymous · **P1** · Local: yes (`seed_demo_creator`)
- Steps: (1) GET `/creators/<id>` anon. (2) Log in, Follow, Unfollow. (3) As the creator, open the bell.
- Expected: `GET creators/<id>/profile/` → `{id, display_name, handle, published_jokes, follower_count, is_following (null anon/self), jokes[≤10 JokeListSerializer: text ≤100 chars, slug strings, dims-only media, share_image_url], jokes_pagination{count,next,previous}}`; user with zero visible jokes → 404 `Creator not found or has no published jokes.`; FE `normalizeProfileJoke` converts slug strings to objects; `<Seo>` + ProfilePage JSON-LD; anon Follow/Tip → `/login`; `POST follows/<id>/` → 201 `{is_following:true, follower_count}` (repeat 200; self → 400 `You cannot follow yourself.`); creator receives `followed_you` notification (actor `{id,name,username}`, no email); `DELETE follows/<id>/` → 204; `GET follows/<id>/status/`; `GET follows/<id>/followers/`, `GET users/me/following/` paginated 10 (auth). `TipsReceived` shows `GET creators/<id>/tips/summary/` `{count,total_cents}` (succeeded only, `{0,0}` for unknown). ⚠ `JokeListSerializer.text` truncation can expose short two-part punchlines on the public profile (outside paywall by design).
- Pages: `/creators/:creatorId` · Endpoints: `creators/<id>/profile/`, `follows/<id>/`, `follows/<id>/status/`, `creators/<id>/tips/summary/`, `notifications/`.

#### J-071 — Block / unblock
- Actor: Free reader · **P1** · Local: yes
- Steps: (1) On `/creators/<B>` click Block (`BlockButton`). (2) Browse feed, open B's joke by id, open B's profile, try to follow. (3) `/settings` → Blocked users → Unblock.
- Expected: `POST users/<B>/block/` → 201 `{status:'blocked'}` (idempotent), Follow rows in both directions deleted, audit `block`; self-block → 400 `Cannot block yourself.`; unknown → 404; thereafter B's jokes absent from `jokes/` list/search/random/reveal/mystery pool/recommendations, `creators/<B>/profile/` → 404 for A (and A's for B — symmetric), `POST follows/<B>/` → 400 `You cannot follow this user.`, follower lists hide each other; FE invalidates `['creator-profile']`, `['jokes']`; `GET users/me/blocks/` lists B; `DELETE` → 204 + audit `unblock`. ⚠ Trending, packs, collections/trending, top-jokesters do not apply blocks; historical notifications from B remain.
- Pages: `/creators/:creatorId`, `/settings` · Endpoints: `users/<id>/block/`, `users/me/blocks/`, `jokes/`, `creators/<id>/profile/`, `follows/<id>/`.

#### J-072 — Report a joke
- Actor: Free reader · **P1** · Local: yes — see J-053. Expected: reasons ∈ `offensive|inappropriate|spam|copyright|harassment|other` (else 400); first → 201 `{joke, reason, description}` + audit `content_report`; second while pending → 200 with the existing report (one `ContentReport` row); anon → 401; removed joke → 400. ⚠ No reporter acknowledgement/outcome notification (R-CMP-5); no scoped throttle; no DB uniqueness (R-MOD-1 wants a non-201 — already 200 at view level).
- Endpoints: `reports/`.

#### J-073 — Tip a creator
- Actor: Free reader (sender) / Tipped creator · **P1** · Local: partial (`.env` has `sk_test_` → checkout session creatable; webhook needs `stripe listen`; hosted Checkout page is external)
- Steps: (1) On `/creators/<id>` click Tip (authed, not self) → pick $1/$3/$5/$10. (2) Dormant vs enabled. (3) Complete Stripe Checkout (test card 4242). (4) Webhook `checkout.session.completed` arrives. (5) View `TipsReceived` and `GET users/me/tips/`.
- Expected: `TipButton` hidden when `is_following === null` (anon/self); anon → `/login`; dormant (`STRIPE_SECRET_KEY` unset, **prod today**) → `POST tips/checkout/` 503 `{code:'billing_unavailable'}` → button flips to disabled "coming soon"; enabled → 200 `{checkout_url, tip_id}` with `Tip(status='pending', stripe_checkout_session_id)` and `window.location.href = checkout_url`; validation: amount ∉ {100,300,500,1000} → 400 `invalid_amount`; missing creator → `creator_required`; self → `self_tip`; target without non-removed `Joke.creator` rows → `not_a_creator`; joke by another creator → `joke_creator_mismatch`; unknown creator → 404; 31st/h → 429. Webhook with `metadata.type='tip'`, `mode='payment'`, `payment_status='paid'` → `Tip.status='succeeded'`, `stripe_payment_intent_id`, `completed_at`; redelivery no-op; `unpaid` stays pending; summary `{count,total_cents}` counts succeeded only; `GET users/me/tips/` paginated newest first with `creator_name` (never email). After Checkout, Stripe redirects to `BILLING_SUCCESS_URL` (⚠ defaults to `localhost:5173/billing/success`; FE has **no** `/billing/success` route → NotFoundPage, R-BIL-8). ⚠ Abandoned checkouts leave eternal `pending` Tips; no refunds; no Tip admin; account deletion cascades Tip rows.
- Pages: `/creators/:creatorId`, `/login` · Endpoints: `tips/checkout/`, `billing/webhook`, `creators/<id>/tips/summary/`, `users/me/tips/`.
- Prod-only: Stripe hosted Checkout UI; live-mode money.

#### J-074 — Notifications inbox
- Actor: Free reader / Creator · **P1** · Local: yes
- Expected: FlowAppShell bell badge from `GET notifications/unread-count/` (`{count}`, shows "9+" above 9); panel lists `GET notifications/` (20/page newest first: `{id, verb, read, created_at, data, actor{id,name,username}|null, joke{id,preview}|null}`); verbs rendered: `followed_you`, `joke_published`, `joke_removed` (reason + "Appeal by <deadline>" + `AppealButton jokeId`), `joke_rejected` (reason + AppealButton submissionId), `appeal_resolved` (approved/reviewed); `POST notifications/mark-read/` → `{marked:N}` and badge → 0; anon → 401; self-actions never notify. ⚠ No per-item read/delete; no email/push transport.
- Pages: any FlowAppShell page (bell) · Endpoints: `notifications/`, `notifications/unread-count/`, `notifications/mark-read/`.

### Creator authoring

#### J-080 — Creator hub
- Actor: Creator (any authed user) · **P1** · Local: yes (`VITE_USE_REAL_CREATE=true`)
- Expected: `/create` → `GET jokes/my-drafts/?page_size=100` → paginated `JokeSubmissionListSerializer` rows (draft/pending/published/rejected of the caller, quarantined assets `url:null`) — ⚠ only **10** shown (cap); status tabs filter client-side; "+" in shell shows unseen-change dot (`jokesfor-creator` localStorage) when a status changed since last visit; appeals strip from `GET users/me/appeals/` (hidden when none; 404 mapped to `[]` ⚠ masks routing regressions); buttons → `/create/new`, `/create/insights`; draft card click → `/create/:draftId` (draft) or `/create/:draftId/view`.
- Pages: `/create` · Endpoints: `jokes/my-drafts/`, `users/me/appeals/`.

#### J-081 — New text joke → submit → approve → published
- Actor: Creator + Staff · **P0** · Local: yes (needs superuser + `DYLD_FALLBACK_LIBRARY_PATH` for the share card on approve)
- Steps: (1) `/create/new` pick "Setup / Punchline". (2) `/create/new/setup-punchline` → editor creates a draft. (3) Type setup; autosave. (4) Add punchline, tones, age rating. (5) Submit. (6) Staff: `/admin/jokes/jokesubmission/` → select pending → "Approve and publish". (7) Creator: bell, `/create`, `/jokes/<new id>`, `/creators/<me>`.
- Expected: catalogs `GET formats/` (paginated, `required_fields/forbidden_fields`), `age-ratings/`, `tones/`, `context-tags/`, `culture-tags/`, `languages/` (⚠ each capped at 10 rows); `POST jokes/my-drafts/ {format:'setup-punchline'}` → 201 `status:'draft'` with default age_rating (lowest min_age) and language `en`; `{}` → 400 `format required`; unknown format → 400; `PATCH jokes/my-drafts/<id>/ {setup}` → 200 even when incomplete (`skip_format_validation`); `useBlocker` warns on unsaved navigation; `POST jokes/my-drafts/<id>/submit/` → 200 `{id, status:'pending'}` (FE re-GETs detail); admin `approve_and_publish` → new `Joke(creator=user, status published, content_tier tier_1 or tier_2 if min_age≥18)`, M2M + media copied, share card generated, `submission.status='published'`, `published_joke` set, `joke_published` notification; the joke now appears in `jokes/` feed, `/creators/<id>` (creator profile now 200), sitemap; creator becomes `IsCreator` (insights) and tippable. Alternative one-shot `POST jokes/submit/` creates pending directly (legacy pages). ⚠ No automated text moderation; no audit row for approval.
- Pages: `/create/new`, `/create/new/:formatSlug`, `/create/:draftId`, `/admin/jokes/jokesubmission/`, `/jokes/:id` · Endpoints: `formats/`, `age-ratings/`, `tones/`, `context-tags/`, `culture-tags/`, `languages/`, `jokes/my-drafts/`, `jokes/my-drafts/<id>/`, `jokes/my-drafts/<id>/submit/`, `jokes/submit/`, `/admin/`.

#### J-082 — Incomplete draft submit / editing rules
- Actor: Creator · **P1** · Local: yes
- Expected: submit a setup-only draft → 400 per-format field errors (e.g. `punchline`); image draft with 0 or 7 media → 400 on `media`; video draft with an image asset → 400; pending submission `PATCH` → 400 `Can only edit drafts or rejected submissions.`; another user's draft → 404; `PUT` is a silent no-op (⚠); `media_asset_ids` with someone else's asset → 400 `One or more media assets were not found.`; duplicates → `Duplicate media attachments.`
- Endpoints: `jokes/my-drafts/<id>/`, `jokes/my-drafts/<id>/submit/`.

#### J-083 — Image joke
- Actor: Creator + Staff · **P1** · Local: partial (upload/processing works; browser preview URLs 404 locally)
- Steps: (1) `/create/new/image` → editor accepts `image/jpeg,image/png,image/webp`. (2) Upload 1–6 images. (3) Write setup. (4) Submit → approve.
- Expected: `POST media/uploads/ (multipart file, kind=image)` → 201 `{id (uuid), kind:'image', url …/media-assets/<id>/image.webp, poster_url:null, width,height ≤1600, duration_ms:null, is_gif:false, created_at}`; EXIF stripped, orientation baked, re-encoded WebP q82; >10MB → 400 `Image exceeds the 10MB limit.`; >4096px → 400; non-image → 400 `Not a valid image.`; HEIC → 400 (JPEG/PNG/WebP only); `safesearch` `skipped` locally / verdict in prod; audit `media_upload`; orphan assets >24h swept; `PATCH my-drafts/<id>/ {media_asset_ids:[…]}` links positions; `text` backfilled from `setup`; on approve `JokeMedia` copied with positions and a **media share card** (image embedded) generated; unlocked readers get URLs; profile always dims-only.
- Pages: `/create/new/image`, `/create/:draftId` · Endpoints: `media/uploads/`, `jokes/my-drafts/<id>/`, `jokes/my-drafts/<id>/submit/`, `/admin/`.
- Prod-only: GCS storage and public URL serving; Vision screening.

#### J-084 — GIF upload
- Actor: Creator · **P2** · Local: yes (ffmpeg present)
- Expected: `.gif` (content-type `image/gif` or `.gif` name) with `kind=image` or `video` → processed as video: `kind:'video'`, `is_gif:true`, `video.mp4` with no audio track, `poster.jpg`; >15MB → 400 `GIF exceeds the 15MB limit.`; ⚠ `kind=audio` + `.gif` → 400 `This looks like a video`. Reader side: GIF renders looping/muted; ⚠ WCAG stop-on-tap not implemented (R-FE-7).

#### J-085 — Video joke
- Actor: Creator · **P1** · Local: yes
- Expected: valid MP4/MOV/WebM ≤30MB, ≤60s, ≤1080p×1.2 px → 201 `kind:'video'`, width≤1280, height≤720, `duration_ms`, `video.mp4` (H.264/AAC faststart, fps≤30), `poster.jpg`; >60s → 400 `Clips must be 60 seconds or shorter.` before ffmpeg; >1080p → 400 before transcode; >30MB → 400 without probe; non-media → 400 `Not a valid media file.`; no video track → 400; unsupported container → 400; forged duration >62s post-encode → 400; per-worker encode slot busy → 429 `Media processing is busy — try again in a moment.` + `Retry-After: 30`; ffmpeg missing → 400 `Could not read this media file.` (no 500); one video per draft, ≤60000 ms enforced at submit; watch telemetry on playback. Cloud Run rejects >32MiB bodies at ingress (413) before Django.
- Endpoints: `media/uploads/`.

#### J-086 — Audio joke
- Actor: Creator · **P2** · Local: yes
- Expected: MP3/M4A/AAC/FLAC/OGG… ≤10MB, ≤60s → 201 `kind:'audio'`, `audio.m4a`, `duration_ms`, `poster_url:null`, `safesearch {'status':'not_applicable'}`; file with a video stream → 400 `This looks like a video — upload it as a video joke.`; MP3 with cover art passes; share card = text card with "Audio" badge.

#### J-087 — SafeSearch screening
- Actor: Creator · **P1** · Local: partial (mock `jokes.media_screening._client`; real Vision is prod-only; `SAFESEARCH_ENABLED=true` in prod)
- Expected: adult or violence ≥ LIKELY → 422 `{file:['This image was rejected by automated content screening.']}` (video: `This clip was rejected…` if any of poster+2 frames blocked), audit `safesearch_block` outcome `blocked`, no asset/file stored; racy/medical/spoof only inform (upload 201, verdict stored, shown in admin `safesearch_flags`); Vision exception/error → 201 with `safesearch.status='error'` (**fail-open**, ⚠ R-MOD-2); disabled → `skipped`; CSAM matcher is `NullMatcher` (⚠ R-CMP-3). FE shows the 422 message in the editor.
- Endpoints: `media/uploads/`.

#### J-088 — Upload throttle
- Actor: Creator · **P2** · Local: yes — 31st upload within an hour → 429 with `Retry-After`.

#### J-089 — Rejection → notice → edit & resubmit
- Actor: Creator + Staff · **P1** · Local: yes
- Steps: (1) Staff opens pending submission change form, sets `status=rejected` + `rejection_reason`, saves. (2) Creator sees bell + `/create/:id/view`. (3) Edits and resubmits.
- Expected: pre/post_save signal emits exactly one `joke_rejected` notification `{submission_id, rejection_reason}` (re-save while rejected → none; bulk `update()` bypasses signal ⚠); `SubmissionDetailPage` rejected state shows reason, edit link and `AppealButton submissionId`; `PATCH my-drafts/<id>/` allowed while rejected; `POST …/submit/` → pending again; media retained (no quarantine). ⚠ No admin "Reject" action (free-text status edit); no SLA.
- Pages: `/create/:draftId/view`, `/create/:draftId`, `/admin/jokes/jokesubmission/<id>/change/` · Endpoints: `notifications/`, `jokes/my-drafts/<id>/`, `jokes/my-drafts/<id>/submit/`.

#### J-090 — Delete a draft
- Actor: Creator · **P2** · Local: yes — `DELETE jokes/my-drafts/<id>/` → 204; attached assets not linked elsewhere are deleted with files; others' → 404.

#### J-091 — Creator insights
- Actor: Creator · **P1** · Local: yes (`seed_demo_creator` gives non-zero data)
- Expected: `/create/insights` → `GET creators/me/insights/?period=month|week|all` → `{period, is_creator, overview{published_jokes, reach, views, impressions, unique_reach, open_rate, payoff_rate, avg_read_seconds, read_rate, completion_rate, reactions, favorites, saves, shares, peak_read_hour, daily_reach_28d[28], followers, follower_growth_28d}, reactions_breakdown, shares_breakdown, source_mix, top_jokes[≤10], audience{top_themes,top_categories,top_formats}, suggestions[peak_hour, what_resonates, consistency]}`; `bogus` period → `month`; non-creator → 403 `You must have at least one published joke…` (FE shows empty/insight-locked state, no retry on 401/403); anon → 401; 121st/h → 429; creator sees own tier_2 jokes; rates null with zero denominators. ⚠ Reach/payoff/read-time stay near zero in prod because telemetry beacons 403 (J-067).
- Pages: `/create/insights` · Endpoints: `creators/me/insights/`.

#### J-092 — Submission detail states
- Actor: Creator · **P2** · Local: yes — `/create/:draftId/view`: draft → redirects/edit; pending → "under review" banner; published → published banner (⚠ "View public" link omitted, R-FE-4); rejected → reason + edit + appeal.

### Moderation / appeals (staff)

#### J-100 — Staff triage: reports → take down
- Actor: Staff + Creator (+ readers) · **P0** · Local: yes (superuser; `DYLD_FALLBACK_LIBRARY_PATH`)
- Steps: (1) Reader files reports (J-072) on a live media joke. (2) Staff logs in at `/admin/` (session auth → `login` audit). (3) `/admin/jokes/contentreport/` → select → "Take down reported joke". (4) Creator opens bell. (5) Anyone fetches the joke.
- Expected: `Joke.is_removed=True`, `removed_at=now`; share card file deleted and `share_image=''`; all pending/reviewed reports on the joke → `resolved`; creator notification `joke_removed` `{reason:<most common report reason>, appeal_deadline:removed_at+14d ISO}`; each linked `MediaAsset` not shared with another live joke → `quarantine()` (files moved to `quarantine/<uuid>/<random16>/<basename>`, `quarantined_at` set, JokeMedia links kept); shared assets untouched; audit `content_takedown` per joke + `media_quarantined`; thereafter the joke is absent/404 on detail, list, search, random, trending, saved, favorites, collections, packs, daily history, recently viewed, data export, share page (404), sitemap; serializers emit `media:[]`, `share_image_url:null` if traversed; creator hub still lists the submission as published; tips `not_a_creator` if it was the creator's only joke. NotificationsPanel shows "A joke was removed — Reason: … Appeal by <date>" with an Appeal button.
- Pages: `/admin/jokes/contentreport/`, bell, `/jokes/:id` · Endpoints: `/admin/`, `reports/`, `notifications/`, `jokes/<id>/`, `/jokes/<id>/share/`, `/sitemap.xml`.

#### J-101 — Creator appeals a takedown
- Actor: Creator · **P1** · Local: yes
- Steps: (1) From the `joke_removed` notice click Appeal → reason → submit. (2) Submit again. (3) Try on a joke removed 15 days ago; on another user's joke; on a live joke. (4) File 11 appeals in a day.
- Expected: `POST appeals/ {joke_id, reason_text}` → 201 `{id, action_type:'takedown', status:'pending', reason_text, target_type:'joke', target_id, target_preview(60), created_at, resolved_at:null, resolution_note}`; audit `appeal_filed`; lazy `purge_lapsed_quarantine()` runs; duplicate pending → 400 (also on DB race); >14 days → 400 window message; not-owned or missing → 404 (indistinguishable); not removed → 400; `removed_at` null (admin direct flip) → 400 `not eligible`; both/neither ids → 400; 11th/day → 429; `GET users/me/appeals/` paginated caller-only; hub appeals strip shows pending/resolved counts; admin `AppealAdmin` queue shows it pending-first with `hours_open` (red ≥36h, `?overdue=yes` filter).
- Pages: bell → `AppealButton`, `/create` · Endpoints: `appeals/`, `users/me/appeals/`.

#### J-102 — Staff upholds appeal
- Actor: Staff + Creator · **P1** · Local: yes
- Expected: admin action "Uphold" on pending appeals → quarantined assets **purged** (row + files) unless still shared with a live joke or a sibling joke has its own pending appeal; `status='upheld'`, `resolver`, `resolved_at`; audit `appeal_upheld`; creator notification `appeal_resolved {outcome:'upheld', action_type}` rendered "Your appeal was reviewed — The original decision stands."; joke stays removed; drafts/export show the asset gone.
- Endpoints: `/admin/jokes/appeal/`, `notifications/`.

#### J-103 — Staff reverses takedown appeal
- Actor: Staff + Creator · **P1** · Local: yes
- Expected: "Reverse" → assets `release()`d back to `media-assets/<uuid>/<basename>`, `is_removed=False`, `removed_at=null`, share card regenerated (media card), `status='reversed'`, audit `appeal_reversed`, notification `appeal_resolved {outcome:'reversed'}` ("Your appeal was approved — The decision was reversed."); `GET jokes/<id>/` → 200 with media URLs; share page 200 again; sitemap lists it. ⚠ Original reports stay `resolved` (not reopened).

#### J-104 — Rejection appeal
- Actor: Creator + Staff · **P2** · Local: yes
- Expected: `POST appeals/ {submission_id}` on a `rejected` submission → 201 `action_type:'rejection'`; draft/pending submission → 400; window anchored on `updated_at`+14d (⚠ owner edits extend it); reverse → `submission.status='draft'`, `rejection_reason` starts with `Appeal reversed on`, notification `appeal_resolved reversed action_type rejection`; creator can edit/resubmit.

#### J-105 — Staff restores removed jokes
- Actor: Staff · **P2** · Local: yes — `JokeAdmin.restore_jokes`: releases quarantined assets, `is_removed=False, removed_at=null`, regenerates cards; ⚠ no notification, no audit row.

#### J-106 — Staff flips `is_removed` directly
- Actor: Staff · **P2** · Local: yes — change-form tick: share card blanked (model `save()`), joke hidden from all read paths, but **no** notice, no report resolution, no quarantine (media stays at public paths), `removed_at` null → creator's appeal → 400 `not eligible`. ⚠ QUESTIONABLE: DSA statement-of-reasons is bypassed; pipeline should document as a defect (be-compliance gap 3).

#### J-107 — Lapsed quarantine purge
- Actor: Ops / any uploader · **P2** · Local: yes (time-travel via DB)
- Expected: asset quarantined >14 days, linked only to removed jokes with no pending appeal → purged (row+files) + one audit `media_purged` on the next `POST media/uploads/` or `POST appeals/`; 13 days, pending appeal, or live-joke link → kept. ⚠ No cron: zero traffic = no purge (by design).

#### J-108 — Staff dismisses / resolves reports
- Actor: Staff · **P2** · Local: yes — `ContentReportAdmin` actions "Dismiss" / "Mark resolved" update status without touching the joke; ⚠ not audited; reporter never notified.

### Billing

#### J-110 — Billing page, Stripe dormant
- Actor: Free reader · **P1** · Local: yes (`STRIPE_SECRET_KEY=` empty)
- Expected: `/settings/billing` loads `GET billing/plans` (public; ⚠ prod serves "Supporter (PLACEHOLDER)" $5 / "Creator Pro (PLACEHOLDER)" $15), `GET billing/my-subscription` (`status:'free'`, `stripe_customer_id:''`), `GET billing/entitlements`; clicking Upgrade → `POST billing/checkout-session {plan_slug}` → 503 `{detail:'Billing is not configured.', code:'billing_unavailable'}` → FE `isBillingUnavailable` renders the unavailable/dormant state; anon → 401 before the dormant check; `POST billing/webhook` → 200 `{detail:'billing_dormant'}` with no `ProcessedStripeEvent`. Mock mode shows "(demo) Would redirect…" overlay instead.
- Pages: `/settings/billing` · Endpoints: `billing/plans`, `billing/my-subscription`, `billing/entitlements`, `billing/checkout-session`, `billing/webhook`.

#### J-111 — Upgrade to a paid plan
- Actor: Free reader → Paid reader · **P1** · Local: partial (`sk_test_` present but plans have blank `stripe_price_id` → 422 until "Push to Stripe" from admin; webhook via `stripe listen`; Checkout page external)
- Steps: (1) `/settings/billing` → Upgrade Supporter. (2) Stripe Checkout with test card. (3) Redirect to `BILLING_SUCCESS_URL`. (4) Webhook `checkout.session.completed` then `customer.subscription.created/updated`. (5) Reload `/settings/billing`, open 11+ jokes.
- Expected: unknown slug → 404; blank `stripe_price_id` → 422 `This plan is not yet available for purchase.`; valid → 200 `{url}` and `window.location.href=url`; Stripe Customer created lazily (creates `Subscription(status='free')`); webhook (valid signature) upserts `Subscription(plan, status='active', stripe_subscription_id, stripe_customer_id, current_period_*)`, `UserProfile.is_premium=True`; `my-subscription.status='active'`; `daily-reads.limit=null`; previously locked jokes unlock; entitlements reflect plan limits. ⚠ Success/cancel URLs are static settings defaulting to localhost and FE has no `/billing/success|cancel` routes → NotFoundPage after payment (R-BIL-8; access still granted by webhook). ⚠ Dahlia API moved `current_period_*` to items → may stay null (R-BIL-5). ⚠ `STRIPE_WEBHOOK_SECRET` must be set with the key (R-BIL-2).
- Pages: `/settings/billing`, `/billing/success` (404) · Endpoints: `billing/checkout-session`, `billing/webhook`, `billing/my-subscription`, `billing/entitlements`, `jokes/daily-reads/`.
- Prod-only: live keys, hosted Checkout UI, real prices.

#### J-112 — Manage subscription
- Actor: Paid reader · **P2** · Local: partial
- Expected: "Manage" → `POST billing/portal-session` → 200 `{url}` (redirect); no customer → 404 `No billing account found.`; dormant → 503; Upgrade while `active/trialing/past_due` → 409 `{code:'active_subscription', portal_url?}` → FE redirects to portal; `customer.subscription.deleted` → plan free, `status='canceled'`, `is_premium=false`, paywall re-engages.

#### J-113 — Stripe webhook lifecycle
- Actor: Stripe (ops) · **P1** · Local: yes (construct_event mocked or `stripe listen`)
- Expected: invalid `Stripe-Signature` → 400 `Invalid signature.`; valid → 200 `{received:true}`; duplicate `event.id` → no-op 200; handler exception → 500 (transaction rolled back so Stripe retry reprocesses); `customer.subscription.updated` with a known `price.id` → plan/status/period mirrored; `deleted` → free/canceled; `invoice.paid` on `past_due` → `active`; `invoice.payment_failed` → `past_due`, `is_premium=false`, 200, and ⚠ **no dunning email** (template `payment_failed` unregistered, exception swallowed); `checkout.session.completed` with `mode='payment'` and no tip metadata → ignored (no downgrade); unknown types recorded + 200; webhook is subject to the anon IP throttle (⚠ >100 events/h from one Stripe IP → 429). ⚠ Out-of-order events overwrite newer state (R-BIL-4).
- Endpoints: `billing/webhook`.

#### J-114 — Entitlements / subscription defaults
- Actor: Free reader · **P2** · Local: yes — `GET billing/my-subscription` no row → `{plan_slug:'free', plan_name:'Free', status:'free', current_period_end:null, cancel_at_period_end:false, stripe_customer_id:''}`; `GET billing/entitlements` → `{plan:'free', features{creator_analytics:true, daily_joke_preview:false, mature_content_addon:false}, limits{mystery_box_rolls_per_day:3, submissions_per_day:5, daily_jokes_per_day:1, daily_joke_history_days:30, free_joke_reads_per_day:10}}`, no `usage` key; `GET billing/plans` anon → active+public plans ordered by `sort_order`. ⚠ `submissions_per_day`, `daily_jokes_per_day`, `daily_joke_preview`, `mature_content_addon` are never enforced (R-BIL-3).

### GDPR / account lifecycle

#### J-120 — Data export
- Actor: Free reader · **P1** · Local: yes
- Expected: Settings "Download my data" → `GET users/me/data-export/` → 200 `application/zip`, `Content-Disposition: attachment; filename="jokes-for-data-export.zip"`, containing `jokes-for-data-export.json` with `export_meta, account, profile, preferences, collections, saved_jokes, favorites, ratings, reactions, daily_jokes, views[≤5000], streak, streak_days, submissions, media_assets, reports_filed, blocks, achievements, vibes, pack_progress, mystery_rolls, share_events, email_logs`; removed jokes excluded from saved/favorites; quarantined assets `url:null, status:'quarantined'`; audit `data_export`; anon → 401; FE triggers a blob download. ⚠ Omits DOB, handle/display_name, appeals, notifications, follows, tips/subscription, telemetry, published jokes (R-CMP-10 / Art. 15 gaps).
- Pages: `/settings` · Endpoints: `users/me/data-export/`.

#### J-121 — Delete account
- Actor: Free reader (password) / Google user · **P0** · Local: yes
- Steps: (1) Settings → Delete account → type DELETE (+ password). (2) Confirm. (3) Observe redirect to `/`. (4) Try old token / refresh.
- Expected: password user: `DELETE users/me/ {}` → 400 `{password:['This field is required.']}`; wrong → 400 `Incorrect password.`; correct → 204; OAuth user: `{confirm:'nope'}` → 400 `{confirm:['Type DELETE to confirm account deletion.']}`; `{confirm:'DELETE'}` → 204 (FE sends both `confirm` and `password`); atomic: outstanding refresh tokens blacklisted, all owned `MediaAsset` files (incl. quarantined) and avatar deleted, `EmailMessageLog`/`EmailVerification` purged, media-format jokes left without media → `is_removed=True`, text jokes survive with `creator=NULL`, user cascade (Follow, UserBlock, Appeal, Notification recipient, Subscription, Tip rows deleted); audit `account_delete` with `actor=None`, `metadata.actor_email_hash`; FE clears store → `/`; old access → 401 `User not found`; refresh → 401. ⚠ Server does not clear cookies; ⚠ Stripe customer/subscription untouched and Tip financial rows deleted (be-compliance gap 5); ⚠ no grace period / email confirmation; admin `auth.User` delete bypasses this cascade.
- Pages: `/settings`, `/` · Endpoints: `users/me/` (DELETE), `auth/user/`, `auth/token/refresh/`.

### Email / scheduler / ops

#### J-130 — Cloud Scheduler runs digests
- Actor: Scheduler · **P1** · Local: yes (export `DIGEST_CRON_TOKEN`, console email)
- Steps: (1) POST without header / wrong token / token unset. (2) Correct token. (3) Same call again same day. (4) Creator with ≥10 new reactions.
- Expected: `DIGEST_CRON_TOKEN` empty (**prod today**) or wrong/missing header → **404** (never 401/403), no emails, no audit; correct (even whitespace-padded) → 200 `{digests_sent, milestones_sent, failed, skipped, remaining, locked}` + audit `digest_run`; requires today's editorial joke (else `skipped:true`); one `daily_digest` email per active user with `profile.email_digest_opt_in=True` (setup teaser only, never punchline, `reveal_url=FRONTEND_URL/daily`, `List-Unsubscribe` + `List-Unsubscribe-Post` headers, in-body unsubscribe link); second run same day sends nothing (`EmailMessageLog` ledger); `creator_milestone` when new reactions since last milestone ≥10 (removed jokes excluded, opt-in respected); cap 500 shared; concurrent call → `locked:true`; endpoint absent from `/api/schema/`. ⚠ Templates contain `[COMPANY POSTAL ADDRESS]` (R-CMP-4). ⚠ No Cloud Scheduler job exists; API not enabled (dormant).
- Endpoints: `internal/run-digests/`, `/api/schema/`.
- Prod-only: Cloud Scheduler invocation; Resend delivery.

#### J-131 — Email unsubscribe
- Actor: Free reader (from email) · **P2** · Local: yes
- Expected: `GET email/unsubscribe/?token=<signed>` → 200 HTML confirm page, **no mutation**; `POST` with token in body or query → 200 HTML "You're unsubscribed", `email_digest_opt_in` (or `creator_milestone_opt_in` for `kind=milestone`) → False, idempotent; tampered/expired (>90d)/deleted user → 400 friendly HTML, never 500; token carries no PII. ⚠ No in-app re-subscribe path (settings toggle writes a different field).
- Endpoints: `email/unsubscribe/`.

#### J-133 — Health probes
- Actor: Ops · **P1** · Local: partial
- Expected (code): `GET /healthz` → 200 `{status:'ok'}` even with DB down; `GET /readyz` → 200 `{status:'ready', checks{db{status,latency_ms}, cache{…}}, version}` or 503 `not_ready` with per-check errors; both carry `X-Request-ID` (echoed if supplied). **Prod reality**: exact path `/healthz` returns a Google-edge HTML 404 on all `*.run.app` hosts (GFE reserves it; never reaches Django) — uptime checks must target `/readyz` (R-OPS-2); warm `/readyz` ≈1 s end-to-end (db ≈230 ms TLS connect to Neon each request), cold 5–19 s.
- Endpoints: `/healthz`, `/readyz`.
- Prod-only: GFE anomaly, latency figures.

#### J-134 — API docs
- Actor: Developer · **P2** · Local: yes — `GET /api/schema/` (anon 200 OpenAPI 3, no `/internal/run-digests/`, unique `v1_` operationIds, `jwtHeaderAuth` bearer scheme; ⚠ 49 ops untyped), `/api/docs/` Swagger, `/api/redoc/`, `GET /api/v1/` router root lists 14 prefixes.

#### J-135 — CORS preflight
- Actor: Ops · **P1** · Local: yes — `OPTIONS auth/login/` with `Origin: http://localhost:5173` (or prod `https://jokesforfront.web.app`, `https://jokesfor.net`) and `Access-Control-Request-Headers: content-type,x-csrftoken` → `Access-Control-Allow-Origin` echoes origin, `Access-Control-Allow-Credentials: true`, allow-headers includes `x-csrftoken`; unknown origin → no ACAO header. ⚠ `www.jokesfor.net` fails TLS (infra-ops).

#### J-136 — Cold start (prod)
- Actor: Ops · **P2** · Local: no — after idle (`min-instances=0`, Neon autosuspend) first request 5–12 s app-side (`/readyz` cold 9.9–19 s observed); warm `/api/v1/jokes/` 1.3–1.5 s. Perf tests must distinguish cold vs warm; owner action `--min-instances=1` pending (R-OPS-4).

### Legacy / responsive

#### J-140 — Legacy subtree
- Actor: Free reader · **P2** · Local: yes — `/legacy` (index HomePageLegacy), `/legacy/trending` public; `/legacy/favorites`, `/legacy/drafts`, `/legacy/profile`, `/legacy/settings`, `/legacy/submit` protected; wrapped in legacy `Layout` (DesktopHeader/Sidebar/MobileBottomNav/FAB/Footer with legal links); not linked from nav. ⚠ Legacy drafts adapter POSTs `/jokes/submit/` (creates pending, not draft) and uses a mismatched status enum — legacy-only defect.

#### J-141 — Mobile responsive shell
- Actor: Anonymous / Free reader · **P1** · Local: yes — at 375px: top nav hidden, bottom `<nav aria-label="Primary">` with Today/Explore/Search/Library + Profile (authed) or Sign in (anon); `<main>` has bottom padding `calc(64px + safe-area)`; `DailyReadsNudge` lifted above the tab bar; at 1280px authed with streak>0 the streak chip shows, hidden at 768px; bell badge "9+" above 9; ProfileMenu links `/profile`, `/library`, `/create`, `/settings`, logout → `/`; `useBreakpoint` bands mobile<640, tablet 640–1023, desktop ≥1024.

---

## 3. Feature → journey coverage matrix

| Feature (from brief) | Journeys |
|---|---|
| Landing | J-001, J-002 |
| Register (age gate, consent) | J-020, J-021, J-027, J-028, J-033, J-009 (consent) |
| Email verify | J-020, J-022, J-023, J-024 |
| Login / logout | J-025, J-026, J-024 |
| Google OAuth | J-027, J-028 |
| Password reset / change | J-029, J-030 |
| Onboarding / preferences / vibes | J-040, J-041, J-042 |
| Home feed (Today hub) | J-050 |
| Explore / search / trending | J-003, J-051, J-052, J-005 |
| Joke detail (text + media) | J-053, J-054, J-004 |
| Punchline reveal + daily-read paywall (10/day, lock, midnight reset) | J-004, J-055, J-056, J-057 |
| Favorites / saved / collections / recently viewed | J-063, J-064, J-065 |
| Reactions / ratings | J-061, J-062, J-053 |
| Daily joke | J-006, J-057 |
| Mystery box | J-058 |
| Streaks | J-059 |
| Packs | J-060 |
| Follows | J-070 |
| Creator profile | J-070, J-071 |
| Creator hub / drafts / editor / format picker / submit (text, image, gif, video, audio) | J-080, J-081, J-082, J-083, J-084, J-085, J-086, J-090, J-092 |
| Moderation (report / block) | J-072, J-071 |
| Appeals | J-101, J-102, J-103, J-104 |
| Notifications inbox | J-074 |
| Settings / profile | J-042, J-043 |
| GDPR export / delete | J-120, J-121 |
| Billing checkout / portal / success / cancel | J-110, J-111, J-112, J-113, J-114 |
| Tips | J-073 |
| Creator insights | J-091, J-067 |
| Share page / OG | J-011, J-012, J-014 |
| Sitemap / SEO | J-013, J-010 |
| Legal pages | J-009 |
| 404 | J-010 |
| Health probes | J-133 |
| Admin triage | J-100, J-105, J-106, J-108, J-089, J-081 |
| Content tiers / SafeSearch / retention | J-066, J-087, J-107 |
| Telemetry | J-067 |
| Digest / unsubscribe / scheduler | J-130, J-131 |
| CSRF / throttles / CORS / cold start / docs | J-031, J-032, J-135, J-136, J-134 |
| Legacy / responsive | J-140, J-141 |

---

## 4. Cross-cutting notes for the test pipeline

1. **Local stack prerequisites** (from `local-dev-runbook.md`): `DATABASE_URL=` (empty) to avoid hitting prod Neon; `EMAIL_BACKEND=console`; `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` (cairo) for any `Joke.save()`/approve/backfill; `FRONTEND_URL=http://localhost:5173`; `createsuperuser` for staff journeys; `setup_social_app`, `seed_achievements`, `seed_demo_creator`; ports 8000/5173 currently held by another project; FE `VITE_API_URL=http://localhost:8000/api/v1 VITE_USE_MOCKS=false VITE_USE_REAL_PREFERENCES=true VITE_USE_REAL_CREATE=true --strictPort`.
2. **Local limitations**: no `/media/` route → uploaded images/posters/share cards 404 in the browser (assert JSON + files on disk); Vision/GCS/Resend/Google consent/Stripe-hosted pages/Cloud Scheduler/SameSite=None are prod-only; Stripe test-mode locally needs `stripe listen` and plan price ids.
3. **Throttles** share a DB cache: anonymous suites >100 req/h/IP will 429 — `cache.clear()` between suites or run authenticated.
4. **Time-dependent journeys** (paywall reset, streak gaps, quarantine lapse, appeal windows, daily joke) are deterministic in BE tests via freezegun (canonical instant 2026-07-14T12:00Z); E2E can seed rows with explicit dates.
5. **Prod expectations that currently FAIL and should be tracked as defects, not asserted as correct**: legal DRAFT banner (J-009), telemetry beacon 403 (J-067), daily history empty (J-050/J-057), For You never fires (J-050), multi-format explore 0 results (J-051), page_size cap 10 (J-003/J-080), `/library` anon 401s (J-008), `/billing/success` 404 (J-111/J-073), `/healthz` GFE 404 (J-133), `show_mature` unreachable (J-066), digest toggle mismatch (J-042), dunning email never sends (J-113), postal placeholder (J-130), direct admin flip bypasses DSA notice (J-106), Playwright placeholder spec stale (fe-tests).
6. **Docs vs code** disagreements relevant to journeys: email-verification doc says gate OFF (code/env: ON in prod); Frontend handout says no CSRF (enforced on cookie path); API spec says history paginated (bare array); memory says migrations don't run in deploy (they do); STRIPE_GOLIVE suggests `/billing/success` FE route (does not exist); design doc says BILLING_ENABLED gates (dead flag); local-dev-runbook says inactive login yields "User account is disabled." while be-auth-session traces the allauth path to "Unable to log in with provided credentials." — assert 400 + `non_field_errors` only.

---

## 5. Test-relevant behaviors (GIVEN / WHEN / THEN)

See the structured summary; the canonical list is reproduced there. Highlights per priority:

- P0: landing render + try-it reveal without API; authed `/` → `/flow-canvas`; anon feed ≤10 tier_1 items with `is_locked`; anon 11th joke locked via cookie ledger; protected route → `/login?returnTo`; gated registration 201 without tokens → verify → cookies → `/flow`; under-13 400 with no user row; login 200 + cookies, logout clears + blacklists; reload restores session via refresh cookie; cookie mutation without CSRF → 403; onboarding requires ≥3 vibes then `PUT users/me/vibes/`; Today hub loads streak/daily/mystery/packs; detail open logs one `JokeView` per 60 s with `source`; free user 10 distinct reads then locked, already-read stays open, resets at midnight UTC, daily joke exempt; draft → autosave → submit → admin approve → published + notification + tier derivation; report → admin takedown → hidden everywhere + notice + quarantine; delete account 204 with cascade and blacklisted tokens.
- P1/P2: as enumerated per journey above.
