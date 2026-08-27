# JokesFor — End-to-End Test Pipeline (design)

**Date:** 2026-08-25 · **Author:** verification pass · **Status:** designed, then executed (results in `02-`/`03-`)
**Inputs:** the 16 analyzer reports in `./analysis/` (5,076 lines), chiefly `user-journeys.md` (141 journeys, J-001…J-141) and `completeness-critic.md` (16 resolved cross-report contradictions + 6 gaps).

---

## 1. Why this pipeline is shaped this way

The product already has **1,632 automated tests** (834 backend `def test_`, 798 frontend vitest cases) and they are green. That is necessary but *not* sufficient evidence that "the application is good", for three structural reasons this pipeline is built to close:

1. **Everything external is mocked.** The backend suite patches Stripe, Google Vision, GCS, ffmpeg and email; the frontend suite runs in jsdom against `mock-api.ts`. Neither suite has ever exercised the real wire between them. Every FE↔BE contract mismatch is invisible to both suites by construction.
2. **The declared E2E layer is empty.** `playwright.config.ts` is configured, but `e2e/` contains only `example.spec.ts`. There is no executable end-to-end coverage today.
3. **Unit tests assert the code's own assumptions.** They cannot tell you that `PATCH /users/me/preferences/` silently drops six of the nine fields the SPA sends — because both sides are tested against their own idea of the contract.

So the pipeline adds three tiers *above* the existing ones — a live black-box API tier, a real-browser journey tier, and a production tier — and treats the existing suites as the regression floor rather than the proof.

### The discipline this pipeline enforces

For **every** test, two things are written down before it runs:

- **Expected behaviour** — a GIVEN/WHEN/THEN statement of what *should* happen.
- **Sanity verdict** — an explicit answer to "*does that expectation make sense as a product?*", one of:
  - `SENSIBLE` — the expectation is what a reasonable user/operator would want.
  - `QUESTIONABLE` — the code does this, but a user would be surprised; assert current behaviour **and** file a finding.
  - `DEFECT-EXPECTED` — analysis says this is already broken; the test's job is to *prove* it, not to pass.

A test whose sanity verdict is `QUESTIONABLE` or `DEFECT-EXPECTED` that **passes** is not good news — it is a confirmed finding. This distinction is what keeps a green suite from being mistaken for a good product.

---

## 2. Tiers

| Tier | Name | What it proves | Where it runs | Blocking? |
|---|---|---|---|---|
| **T0** | Static & build gates | Code compiles, lints, schema matches models, no un-migrated model drift, prod settings are safe | both repos, local + CI | yes |
| **T1** | Backend suite (834) | Server-side logic incl. time-travel, permissions, webhooks, media pipeline | `manage.py test`, local Postgres | yes |
| **T2** | Frontend suite (798) | Component/route/adapter logic in jsdom | `vitest run` | yes |
| **T3** | **Live API contract** (new) | The real HTTP surface: auth cookies, CSRF, paywall arithmetic, pagination caps, gating, the FE↔BE contract | real `runserver` + real Postgres, `curl`/python client | yes |
| **T4** | **In-browser E2E** (new) | The actual user journeys through the real SPA against the real API — clicks, cookies, redirects, rendering | Chrome automation vs `localhost:5273` → `localhost:8010` | yes |
| **T5** | **Production smoke** | The deployed system serves users: health, cold start, SEO/OG, CORS, schema, security headers | live prod URLs | report-only |

T3 is the tier that finds contract bugs. T4 is the tier that finds journey bugs. T5 is the tier that finds deploy/infra bugs. T1/T2 are the floor.

### Environment for T3/T4

Ports 8000 and 5173 are held by an **unrelated project** (WebViewer-V2 backend/frontend). Rather than kill another project's servers, this run uses **8010 / 5273** and passes the origins explicitly, since backend CORS/CSRF defaults hardcode 5173:

```bash
# Backend (repo root)
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 \
DEBUG=True EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend \
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
FRONTEND_URL=http://localhost:5273 \
CORS_ALLOWED_ORIGINS=http://localhost:5273 CSRF_TRUSTED_ORIGINS=http://localhost:5273 \
.venv/bin/python manage.py runserver 8010

# Frontend (jokes-for-frontend)
VITE_API_URL=http://localhost:8010/api/v1 VITE_USE_MOCKS=false \
VITE_USE_REAL_PREFERENCES=true VITE_USE_REAL_CREATE=true \
npm run dev -- --strictPort --port 5273
```

Preconditions: `manage.py migrate` first (local DB is **8 migrations behind** — Appeal, Tip, DigestRun, MediaAsset.quarantined_at and inbox fields do not exist yet, so appeals/tips/inbox would 500); `seed_achievements`; `createsuperuser` (no superuser exists locally); `demo.creator@jokesfor.dev` / `DemoCreator!2026` already seeded.

Known local blind spots (must be covered in T5 or accepted): Google consent screen, GCS, Vision SafeSearch, Resend delivery, Stripe hosted checkout, Cloud Scheduler, `SameSite=None` cross-site cookies, and `/media/` file serving (no route under `runserver` for uploaded files → assert JSON + on-disk file instead of image rendering).

---

## 3. Test register

Numbering: `T<tier>-<area><nn>`. Each row carries its journey id(s), the expected behaviour, and the sanity verdict.

### T0 — Static & build gates

| ID | Check | Expected behaviour | Sanity |
|---|---|---|---|
| T0-01 | `ruff check .` | Exit 0. GIVEN the CI hard gate, WHEN lint runs, THEN no violations. | SENSIBLE |
| T0-02 | `manage.py check` | Exit 0, 0 issues. | SENSIBLE |
| T0-03 | `makemigrations --check --dry-run` | "No changes detected" — model code and migration files agree. Not in CI; a drift here means prod migrate would miss a column. | SENSIBLE — **should be added to CI** |
| T0-04 | `check --deploy` under `DEBUG=False` | Only the throwaway-SECRET_KEY warning should be security-relevant. Any `security.W*` beyond that is a finding. | SENSIBLE |
| T0-05 | drf-spectacular schema generation warnings | GIVEN 22 `APIView`s without `serializer_class`, WHEN the schema is generated, THEN each emits `W002` and is **omitted from the schema**. | QUESTIONABLE — harmless for the SPA, **blocking for iOS codegen** |
| T0-06 | `npm run lint` (FE) | Exit 0. Note two `react-hooks` v7 rules were demoted to `warn` to make the gate green — warnings are not zero. | QUESTIONABLE — demoted rules hide real hook bugs |
| T0-07 | `tsc -b && vite build` | Build succeeds; sitemap prebuild fetches from prod backend. | SENSIBLE |
| T0-08 | `bandit`, `pip-audit` | Report-only in CI. Record counts; any *new* HIGH is a finding. | QUESTIONABLE — non-blocking security gates drift |

### T1 — Backend suite

| ID | Check | Expected behaviour | Sanity |
|---|---|---|---|
| T1-01 | `manage.py test --noinput` full suite, local Postgres | All 834 pass; record wall-clock (never measured before). | SENSIBLE |
| T1-02 | ffmpeg-gated subset actually ran | GIVEN ffmpeg 8.1.2 is installed, WHEN the suite runs, THEN the 28 `skipUnless(FFMPEG)` tests execute rather than skip. | SENSIBLE — a silent skip means the media pipeline is untested |
| T1-03 | cairo-gated subset actually ran | Same for the 25 share-card renders (needs `DYLD_FALLBACK_LIBRARY_PATH` on macOS). | SENSIBLE |
| T1-04 | Skip census | GIVEN the run, THEN the only skips are the documented `Tone` fixture class-skip. Any other skip is hidden lost coverage. | SENSIBLE |

### T2 — Frontend suite

| ID | Check | Expected behaviour | Sanity |
|---|---|---|---|
| T2-01 | `vitest run` | 798/798 pass. | SENSIBLE |
| T2-02 | Suite runs against mocks only | GIVEN `mock-api.ts`, THEN no test asserts a real backend shape — so green here says nothing about the contract. Record as a **coverage limitation**, not a pass. | QUESTIONABLE — this is the gap T3 exists to close |
| T2-03 | Untested pages census | `FlowCanvasPage`, `FlowPage`, `SubmitJokePage`, `DraftsPage`, `PackDetailPage`, `TrendingPage`, `OnboardingPage`, `ForgotPasswordPage`, `NotFoundPage` have no test file. | QUESTIONABLE — `/flow-canvas` is the authenticated home |

### T3 — Live API contract (new; the core of this pass)

**Auth & session**

| ID | J | Expected behaviour (GIVEN/WHEN/THEN) | Sanity |
|---|---|---|---|
| T3-A01 | J-020 | GIVEN `EMAIL_VERIFICATION_REQUIRED=true`, WHEN `POST /auth/registration/` with valid email+password+DOB, THEN **201, no JWT cookies**, body `{detail, email}`, user row `is_active=False`. | SENSIBLE |
| T3-A02 | J-021 | WHEN DOB implies age < 13, THEN 400 and **no user row is created**. | SENSIBLE — COPPA |
| T3-A03 | J-021 | WHEN `date_of_birth` is omitted / in the future, THEN 400 with a field error. | SENSIBLE |
| T3-A04 | J-022 | WHEN `POST /auth/verify-email/` with the correct 6-digit code, THEN 200 **and JWT cookies are set** and `is_active=True`. | SENSIBLE |
| T3-A05 | J-022 | WHEN a wrong code is posted 5×, THEN the 6th is rejected/throttled rather than allowing unlimited guessing. | SENSIBLE — brute-force guard on a 6-digit secret |
| T3-A06 | J-024 | GIVEN an unverified (`is_active=False`) user, WHEN `POST /auth/login/` with the *correct* password, THEN 400 `non_field_errors` — and the message must be the **generic** "Unable to log in with provided credentials.", never "User account is disabled." | SENSIBLE — a distinct message would be an account-existence oracle. (Two analyzer reports disagreed; the critic resolved it to the generic string.) |
| T3-A07 | J-025 | WHEN login succeeds, THEN `jokes-access-token` + `jokes-refresh-token` cookies are set `HttpOnly`, and `GET /auth/user/` with those cookies returns the user. | SENSIBLE |
| T3-A08 | J-026 | WHEN the access cookie is expired but the refresh cookie is valid, THEN `POST /auth/token/refresh/` re-issues without re-login. | SENSIBLE |
| T3-A09 | J-025 | WHEN `POST /auth/logout/`, THEN cookies are cleared and the refresh token is blacklisted (a replay fails). | SENSIBLE |
| T3-A10 | J-031 | GIVEN cookie auth, WHEN a mutating request omits `X-CSRFToken`, THEN **403**. | SENSIBLE |
| T3-A11 | J-031 | GIVEN the same JWT sent **only** as `Authorization: Bearer`, WHEN a mutating request omits the CSRF header, THEN **200** — the header path is exempt by design. Zero in-repo tests cover this; it is the transport a native app would use. | SENSIBLE, but **untested in-repo** → must be pinned before iOS |
| T3-A12 | J-029 | WHEN password reset is requested, THEN the emailed link is built from `FRONTEND_URL` (not hardcoded prod) and completing it lets the new password log in. | SENSIBLE |
| T3-A13 | J-032 | WHEN >100 anon requests/hour arrive from one IP, THEN 429. | SENSIBLE |

**Reading, paywall & tiers** — the monetization core

| ID | J | Expected behaviour | Sanity |
|---|---|---|---|
| T3-P01 | J-003 | GIVEN anonymous, WHEN `GET /jokes/`, THEN only `tier_1` jokes, page size 10, and every punchline for a locked joke is `null` with `is_locked:true` — the punchline must never be present in the payload. | SENSIBLE — server-side stripping is the only real paywall |
| T3-P02 | J-004 | GIVEN anonymous, WHEN 10 distinct jokes are revealed, THEN the 11th is locked, tracked via the signed `jf_anon_reads` cookie. | SENSIBLE |
| T3-P03 | J-055 | GIVEN a free authenticated user, WHEN 10 distinct reveals are consumed, THEN `GET /daily-reads/` shows `used=10, remaining=0` and the 11th joke returns `is_locked:true`. | SENSIBLE |
| T3-P04 | J-055 | GIVEN the cap is reached, WHEN a joke **already revealed today** is re-opened, THEN it stays unlocked (re-reads are free). | SENSIBLE |
| T3-P05 | J-055 | GIVEN the cap is reached, WHEN the clock crosses midnight UTC, THEN the allowance resets to 10. | SENSIBLE — though a UTC reset means a 4am reset for this user's timezone (+04) |
| T3-P06 | J-057 | GIVEN the cap is reached, WHEN the daily joke is fetched, THEN it is still readable (exempt from the cap). | SENSIBLE |
| T3-P07 | J-056 | GIVEN a subscribed user, WHEN `GET /daily-reads/`, THEN limits are null/unlimited. | SENSIBLE |
| T3-P08 | J-066 | GIVEN any API caller, WHEN they attempt to opt into mature content, THEN there is **no API to do so** — `show_mature` exists in the model but has zero serializer/view references, so `tier_2` content is unreachable for everyone. | **QUESTIONABLE** — content exists that no user can ever see |
| T3-P09 | J-052 | GIVEN a locked joke, WHEN a word that appears **only in its punchline** is searched, THEN the joke is returned (`is_locked:true`, `punchline:null`) — the FTS vector indexes punchlines, so search is an existence oracle over paywalled text. | **QUESTIONABLE** — no content leaks, but the paywall is partially inferable |
| T3-P10 | J-052 | WHEN `ordering=relevance` with an empty `q`, THEN results fall back to `-created_at` silently. | QUESTIONABLE — silent fallback, not an error |
| T3-P11 | J-051 | WHEN `joke_format=setup,oneliner` (comma list, as the Explore UI implies), THEN **0 results** — the filter is exact-match, not a list. | **DEFECT-EXPECTED** |

**Catalog, preferences & the FE↔BE contract** — where the critic predicts breakage

| ID | J | Expected behaviour | Sanity |
|---|---|---|---|
| T3-C01 | J-051 | GIVEN 13 seeded themes and `PAGE_SIZE=10` with no `page_size` override, WHEN `GET /context-tags/`, THEN `count=13` but `results` has 10 — and the FE fetches page 1 only, so **3 themes are permanently unreachable in the UI**. | **DEFECT-EXPECTED** |
| T3-C02 | J-040 | GIVEN a user with tone preferences, WHEN the SPA finishes onboarding (`PATCH /users/me/preferences/` with `humor_types` = *format* slugs), THEN `preferred_tones` is **wiped to empty** (format slugs match no `Tone`) and personalization degrades. | **DEFECT-EXPECTED** — actively destructive |
| T3-C03 | J-040 | WHEN the same PATCH sends `tones`, `languages`, `notification_time/days/enabled`, `streak_saver_enabled`, `onboarding_completed`, THEN all are **silently dropped** (200 OK, nothing persisted); `onboarding_completed` stays `false` forever. | **DEFECT-EXPECTED** — silent success is the worst failure mode |
| T3-C04 | J-040 | GIVEN the drop above, WHEN `GET /users/me/today-status/` is called, THEN it reflects model defaults, never the ritual the user chose. | DEFECT-EXPECTED (consequence of T3-C03) |
| T3-C05 | J-067 | GIVEN cookie-only auth and `navigator.sendBeacon` (which cannot set `X-CSRFToken`), WHEN telemetry posts to `/telemetry/events`, THEN **403** and all audience telemetry is silently lost. Analysis rates this "very likely" but it has never been observed — **verify first**. | **DEFECT-EXPECTED if confirmed** — creator insights would be built on nothing |
| T3-C06 | J-043 | GIVEN a user who has crossed every seeded achievement threshold, WHEN `GET /users/me/achievements/`, THEN **every achievement is still `unlocked:false`** — no code path ever writes a `UserAchievement` row. | **DEFECT-EXPECTED** — a shipped, decorative feature |
| T3-C07 | J-006 | GIVEN anonymous, WHEN `GET /daily-jokes/today/` twice in a row, THEN the joke may differ each time (`order_by('?')` per request) — "daily" is not daily for logged-out users. | **QUESTIONABLE** |
| T3-C08 | J-057 | GIVEN an authenticated user, WHEN the daily joke is fetched twice in a day, THEN it is the **same** joke, with issue label and history. | SENSIBLE |

**Creator authoring & media**

| ID | J | Expected behaviour | Sanity |
|---|---|---|---|
| T3-M01 | J-081 | WHEN a draft is created, autosaved, and submitted, THEN status → `pending` and it is no longer editable. | SENSIBLE |
| T3-M02 | J-082 | WHEN a `knock` draft with 3 lines is submitted, THEN 400 `"Knock format requires at least 4 lines."`; a 29-word `story` → 400 `"Story must be at least 30 words."`. | SENSIBLE |
| T3-M03 | J-083 | WHEN a JPEG/PNG is uploaded, THEN it is normalized to WebP and a `MediaAsset` row + on-disk file exist. | SENSIBLE |
| T3-M04 | J-085 | WHEN a video over 60s / 30MB / 1080p is uploaded, THEN it is rejected with a clear limit error. | SENSIBLE |
| T3-M05 | J-087 | GIVEN Vision credentials are absent locally, WHEN media is uploaded, THEN screening **fails open** (upload succeeds). | **QUESTIONABLE** — fail-open on a CSAM/NSFW gate is a deliberate availability trade-off; must be verified as *closed* in prod |
| T3-M06 | J-088 | WHEN >30 uploads/hour, THEN 429. | SENSIBLE |
| T3-M07 | J-081 | WHEN staff approves a submission, THEN a published joke appears with derived content tier, a share card, and a `joke_published` notification. | SENSIBLE |

**Moderation, appeals, compliance**

| ID | J | Expected behaviour | Sanity |
|---|---|---|---|
| T3-S01 | J-072 | WHEN the same user reports the same joke twice while the first is pending, THEN **200 with the existing report** (not a duplicate 201). | SENSIBLE — though there is no DB uniqueness or scoped throttle behind it |
| T3-S02 | J-100 | WHEN staff takes a joke down, THEN it disappears from feed/search/detail/share and its media is quarantined to an unguessable path. | SENSIBLE |
| T3-S03 | J-101 | WHEN the creator appeals within 14 days, THEN the appeal is accepted once; a duplicate is rejected; after 14 days the window is closed. | SENSIBLE |
| T3-S04 | J-103 | WHEN staff reverses a takedown, THEN the joke is live again, media is released from quarantine, and the share card is regenerated. | SENSIBLE |
| T3-S05 | J-106 | WHEN staff flips `is_removed` directly in Django admin, THEN the joke is hidden **without** a DSA notice or appeal right being created. | **QUESTIONABLE** — a compliance bypass reachable from the admin UI |
| T3-S06 | J-071 | WHEN a user blocks a creator, THEN that creator's jokes vanish from the blocker's feed, follows are severed, and the profile 404s. | SENSIBLE |
| T3-S07 | J-120/121 | WHEN a user exports their data, THEN a zip with their content is returned; WHEN they delete their account, THEN 204, cascade, and tokens blacklisted. | SENSIBLE |

**Billing & tips**

| ID | J | Expected behaviour | Sanity |
|---|---|---|---|
| T3-B01 | J-110 | GIVEN `STRIPE_SECRET_KEY` unset locally, WHEN billing endpoints are called, THEN 503 `billing_dormant` and the UI shows an unavailable state. | SENSIBLE |
| T3-B02 | J-111 | GIVEN prod (`sk_test_…` **is** set — billing is live in test mode, correcting an earlier "dormant" claim), WHEN `POST /billing/checkout-session {plan_slug:'supporter'}`, THEN **422** ("not yet available") because `stripe_price_id` is blank — not 503. | QUESTIONABLE — a plan visible in the UI that cannot be bought |
| T3-B03 | J-073 | WHEN `POST /tips/checkout/` with a valid tier in prod, THEN a real test-mode `checkout.stripe.com` URL is returned. | SENSIBLE |
| T3-B04 | J-113 | WHEN a webhook arrives with a bad signature, THEN 400; WHEN the same event id is replayed, THEN it is idempotent. | SENSIBLE |
| T3-B05 | J-111 | GIVEN prod returns to `/settings/billing?checkout=success`, WHEN the SPA loads it, THEN **no success acknowledgement is rendered** — `BillingPage` never reads the query param. | QUESTIONABLE — user pays and gets no confirmation |

**SEO, share, ops**

| ID | J | Expected behaviour | Sanity |
|---|---|---|---|
| T3-O01 | J-011 | WHEN a bot fetches `/jokes/<id>/share/`, THEN per-joke OG/Twitter tags, canonical URL and JSON-LD are served; a human is redirected into the SPA. | SENSIBLE |
| T3-O02 | J-011 | WHEN the joke is locked/paywalled, THEN the punchline appears in **neither** the OG description nor the JSON-LD. | SENSIBLE — this leak was fixed in `04e1b2f`; it must stay fixed |
| T3-O03 | J-012 | WHEN the share page is requested for a `tier_2`, removed, or missing joke, THEN redirect (not a 404 that leaks existence). | SENSIBLE |
| T3-O04 | J-013 | WHEN `/sitemap.xml` is fetched, THEN it lists crawlable frontend routes and excludes gated ones. | SENSIBLE |
| T3-O05 | J-133 | WHEN `/healthz` is fetched **through the public Cloud Run URL**, THEN it returns 200 — it currently returns a Google-edge HTML 404. | **DEFECT-EXPECTED** (F-001) |
| T3-O06 | J-133 | WHEN `/readyz` is fetched, THEN 200 with per-dependency db/cache latencies. | SENSIBLE |
| T3-O07 | J-135 | WHEN the SPA origin sends a CORS preflight, THEN it is allowed with credentials. | SENSIBLE |

### T4 — In-browser E2E journeys

Driven in a real Chrome against the real local stack. Each records: screenshot, console errors, and the network calls that fired.

| ID | J | Journey | Expected behaviour | Sanity |
|---|---|---|---|---|
| T4-01 | J-001 | Anonymous landing | Landing renders, "try it" reveal works with no API call, CTAs route to register/login. | SENSIBLE |
| T4-02 | J-003/004 | Anon browse → detail → reveal | Feed of tier_1 jokes; opening one and revealing works; punchline arrives only on reveal. | SENSIBLE |
| T4-03 | J-004 | Anon paywall wall | After 10 reveals the 11th shows the lock UI + register CTA. | SENSIBLE |
| T4-04 | J-007 | Protected route while anon | `/flow-canvas` redirects to `/login?returnTo=…` and returns there after login. | SENSIBLE |
| T4-05 | J-020 | Register → verify → onboarding | Age-gated form → 201 → verify screen → code accepted → lands in `/flow` onboarding. | SENSIBLE |
| T4-06 | J-040 | Onboarding 3 steps | ≥3 vibes required; formats; ritual; finish → lands on the hub. **Watch whether anything persists** (T3-C02/C03). | DEFECT-EXPECTED at the persistence step |
| T4-07 | J-050 | Today hub | Streak, daily joke, mystery box, packs, taste, jokesters, history all render with real data. | SENSIBLE |
| T4-08 | J-051/052 | Explore + Search | Chips filter; query returns results; load-more paginates. | SENSIBLE |
| T4-09 | J-053 | Authed joke detail | Reveal, react, save, share, report are all wired; one `JokeView` per 60s. | SENSIBLE |
| T4-10 | J-055 | Free-user paywall | 10 reads → lock; already-read stays open; nudge + upgrade CTA appear. | SENSIBLE |
| T4-11 | J-063/064 | Favorites & collections | Add/remove favorite; create collection; save into it; view detail. | SENSIBLE |
| T4-12 | J-080/081 | Creator hub → editor → submit | Format picker → editor autosave → submit → appears as pending. | SENSIBLE |
| T4-13 | J-100/089 | Staff approve/reject via admin | Admin action publishes (or rejects) and the creator sees the outcome + notification. | SENSIBLE |
| T4-14 | J-074 | Notifications inbox | Bell badge count, panel lists notices, mark-all-read clears. | SENSIBLE |
| T4-15 | J-042/043 | Settings & profile | Preferences save, display name/handle update, blocked users list. | SENSIBLE |
| T4-16 | J-110 | Billing page (dormant local) | Renders an unavailable state instead of crashing. | SENSIBLE |
| T4-17 | J-141 | Mobile responsive @375 | Bottom tab bar, no horizontal scroll, ≥44px targets on the core reading path. | SENSIBLE |
| T4-18 | J-067 | Telemetry in flight | Watch the network tab for `/telemetry/events` — confirm 2xx vs the predicted 403. | DEFECT-EXPECTED |
| T4-19 | J-009/010 | Legal, consent, 404 | Consent banner behaves; legal pages render; unknown path → NotFound. | SENSIBLE |
| T4-20 | J-121 | Delete account | Confirm dialog → 204 → logged out → cannot log back in. | SENSIBLE |

### T5 — Production smoke

| ID | J | Expected behaviour | Sanity |
|---|---|---|---|
| T5-01 | J-136 | Cold start after idle completes within the documented budget (last measured 19s on `/readyz`). | **QUESTIONABLE** — 19s is beyond what a first-time visitor tolerates |
| T5-02 | J-133 | `/readyz` 200 with db+cache ok; `/healthz` — see T3-O05. | — |
| T5-03 | J-011 | Prod share page for a real joke: OG tags, canonical, JSON-LD, no punchline leak. | SENSIBLE |
| T5-04 | J-013 | Prod sitemap + FE `robots.txt` agree, gated routes disallowed. | SENSIBLE |
| T5-05 | J-134 | `/api/schema/`, `/api/docs/` load; count endpoints missing from the schema (T0-05). | SENSIBLE |
| T5-06 | — | Security headers on prod API responses (HSTS, nosniff, frame-deny, referrer policy). | SENSIBLE |
| T5-07 | J-135 | Preflight from `https://jokesforfront.web.app` is allowed with credentials. | SENSIBLE |
| T5-08 | — | Prod SPA loads, no console errors, real data renders. | SENSIBLE |

---

## 4. Exit criteria

- **T0/T1/T2** must be fully green. A regression here blocks everything.
- **T3/T4**: every `SENSIBLE` expectation must hold. Every `QUESTIONABLE` / `DEFECT-EXPECTED` outcome is recorded as a finding with severity, repro and proposed fix — a passing defect-expectation is a *confirmed bug*, not a pass.
- **T5** is report-only but any P0 (data leak, auth bypass, paywall bypass) found there escalates immediately.

## 5. What this pipeline deliberately does NOT cover

Load/perf beyond cold start, penetration testing, cross-browser (Chrome only), real Apple/Google device matrices, Stripe live-mode money movement, actual email deliverability/inboxing, and Vision SafeSearch accuracy. These are called out so their absence is a decision rather than an oversight.
