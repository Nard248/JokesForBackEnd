# JokesFor — Known-Gaps & Risk Register (2026-08-25)

Read-only synthesis of documentation, memory notes, SDD ledgers, code annotations and feature-flag defaults across both repos. Every item is classified by **severity** (P0 = blocks safe public launch / legal or money exposure; P1 = should fix before or right after launch; P2 = hygiene / tracked follow-up), **area**, **status** (`open` = code work needed; `owner-action` = ops/business step outside code; `dormant` = built and deployed but switched off by env; `by-design` = documented accepted limitation; `unknown` = could not verify from code), **where** (file:line), and **what test would detect it**.

Backend root: `/Users/narekmeloyan/PycharmProjects/JokesForProject` (BE). Frontend root: `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend` (FE).

---

## 0. Source inventory and staleness verdicts

| Source | Date | Verdict |
|---|---|---|
| `BE/.planning/codebase/CONCERNS.md` | 2026-01-11 | **Fully stale.** Every item (no requirements.txt, no .gitignore, hardcoded SECRET_KEY, DEBUG=True, empty ALLOWED_HOSTS, SQLite, no tests, no security headers) is closed in code: `requirements.txt` exists (Dockerfile:17), `.gitignore` exists, `SECRET_KEY` is env-required when `DEBUG=False` (`settings.py:37-42`), `ALLOWED_HOSTS` env-driven (`settings.py:44`), Postgres via `DATABASE_URL` (`settings.py:142-150`), HSTS/SSL-redirect/nosniff on when `DEBUG=False` (`settings.py:403-410`), 834 backend test functions across 52 files. Treat as historical only. |
| `BE/Docs/2026-06-19-iteration-review.md` | 2026-06-19 | Mostly superseded. Open items still live: monetization business decisions (#1-5: paid-vs-free feature catalog, plan limits, tier structure, real prices, live-key flip), observability console setup (#8), placeholder plan prices. Items #6, #7, #9 are done. Note: it says the migrate step in `cloudbuild.yaml` fixes throttling "likely erroring in prod" — the cache table migration now exists (`notifications/migrations/0002_create_cache_table.py`, referenced from `settings.py:184`). |
| `BE/Docs/superpowers/plans/2026-06-15-mvp-launch-master-plan.md` | 2026-06-15 | Wave 0/1/2 code items are shipped (content_tier serving lock, Firebase consent gating, DOB gate, GDPR export/delete, moderation). **Explicitly deferred items remain open**: FTC verifiable-parental-consent flow + parental dashboard; counsel review of legal copy; DSA/DMCA notice-and-action (appeals shipped 2026-07-24 but reporter acknowledgement / SLA notification path is partial); report dedup constraint (never added — see R-MOD-1). |
| `BE/Docs/superpowers/specs/2026-08-04-quality-seo-metrics-design.md` | 2026-08-04 | Shipped except the owner-gated ops items and two explicit deferrals: build-time prerender (react-snap rejected on React 19/Vite 7) and bot-rendering for content routes (replaced by BE share page `/jokes/:id/share/`). CI's bandit/pip-audit are still `|| true` (non-blocking) — the "ratchet" never happened. |
| Readiness Report (July 2026) / Progress Update (Aug 2026) | Jul/Aug 2026 | Business-facing. Their "Requirements for Public Release" list is the best owner checklist: Stripe live-mode, DSA workflow (partially done via appeals), CI test gates (done for BE and FE), backups/PITR verification (**no evidence anywhere in either repo**), error-monitoring/uptime confirmation (Sentry is DSN-gated; `/healthz` unreachable at the edge), anonymous-paywall policy (decided: soft cookie wall), rate limits on high-volume actions (only 4 scoped throttles exist). Progress Update's claim "800+ tests run every time we change something" is true for GitHub Actions CI on PR/main (`BE/.github/workflows/ci.yml`), but the **Cloud Build deploy pipeline itself has no test gate** (`cloudbuild.yaml` = build → push → migrate → deploy). |
| `FE/Docs/Redesign_Plan.md` | ~Jun 2026 | Stale in parts: says adapters are "mock-only until shapes confirmed", but `api-adapter.ts` now routes every adapter on `USE_MOCKS` (false in the deploy workflow). Still-true residue: legacy `/legacy/*` mirror routes and `<Name>Legacy.tsx` components still exist (`routes.tsx:131-143`); `JokeCard`/`FlowJokeCard` and `Layout`/`FlowAppShell` not consolidated; `api.ts:372,429` TODOs about unconfirmed DTO shapes remain. |
| Memory notes (`~/.claude/projects/.../memory/*.md`) and `BE/.superpowers/sdd/progress.md` | Jun-Aug 2026 | Most current. Owner-activation checklists and fast-follow lists are enumerated below. The referenced readiness artifact (`claude.ai/code/artifact/ba6032d7-…`) is **not retrievable** (artifact read returned "not found"), so the exact 24-item should-fix list cannot be reproduced verbatim — see §3. |

---

## 1. Feature flags / env gates that default OFF (dormant surfaces)

All verified in `BE/JokesForProject/settings.py` unless noted. "Prod state" is from memory notes; anything marked *unverified* could not be confirmed from code.

| Flag | Default | Effect when unset | Prod state | Where |
|---|---|---|---|---|
| `STRIPE_SECRET_KEY` | `''` | Billing dormant: checkout/portal/tips → 503 `billing_unavailable`; webhook → 200 `billing_dormant` no-op; entitlements resolve to FREE | Test-mode keys were set in Jun/Jul (memory: "Stripe test-mode verified"); live keys NOT set; tips dormant | `settings.py:508`, `billing/stripe_gateway.py:14-16`, `billing/views.py:261-263` |
| `STRIPE_WEBHOOK_SECRET` | `''` | `construct_event` verifies HMAC against the empty string → **forgeable webhook** whenever `STRIPE_SECRET_KEY` is set but this is not | Unverified | `billing/stripe_gateway.py:145-150` |
| `BILLING_ENABLED` | `false` | **Dead flag** — defined, referenced nowhere else (grep confirms only `settings.py:512`); `Docs/STRIPE_GOLIVE.md` documents it as unused | n/a | `settings.py:512` |
| `SAFESEARCH_ENABLED` | off | `screen_image` returns `{'status':'skipped'}`; human review queue is the only gate | ON in prod since 2026-07-23 (rev 00039) | `settings.py:286`, `jokes/media_screening.py:33-36` |
| CSAM hash matcher | `NullMatcher` (code, not env) | `get_matcher()` always returns NullMatcher → no hash matching; vendor onboarding is an owner action | Dormant | `jokes/media_screening.py:72-83` |
| `DIGEST_CRON_TOKEN` | `''` | `/internal/run-digests/` 404s for every caller (dormant, schema-excluded) | Dormant (token unset, no Cloud Scheduler job) | `settings.py:505`, `notifications/views.py:244-257` |
| `EMAIL_VERIFICATION_REQUIRED` | `false` | Signup not gated by code | ON in prod since 2026-06-13 | `settings.py:483` |
| `SENTRY_DSN` | `''` | Sentry fully no-op | Unverified whether set in Cloud Run env | `settings.py:631-656` |
| `GS_BUCKET_NAME` | `''` | Media falls back to **ephemeral container filesystem** (uploads/share cards lost on instance churn) | Presumed set (cloudbuild comment lists it among preserved env) — unverified | `settings.py:243-282` |
| `JWT_COOKIE_SAMESITE` | `Lax` | CSRF cookie stays `Lax` → cross-site SPA would 403 on every cookie-only mutation | Must be `None` in prod (memory says it is) | `settings.py:386-389, 442` |
| `DEBUG` | `False` | Secure defaults; `SECRET_KEY` required | Off in prod | `settings.py:32-42` |
| `LOG_SQL` | `false` | SQL logging off | — | `settings.py:552` |
| FE `VITE_USE_MOCKS` | `true` in `.env.example`; `'false'` in deploy workflows | When true or `VITE_API_URL` unset, **every** adapter serves mock data | false in prod builds | `FE/src/lib/api-adapter.ts:33-34`, `.github/workflows/firebase-hosting-merge.yml` |
| FE `VITE_USE_REAL_PREFERENCES`, `VITE_USE_REAL_CREATE` | unset locally; `'true'` in deploy | Preferences/create route to mocks when unset **and** `USE_MOCKS` true | true in prod builds | `api-adapter.ts:677`, `features/create/adapter.ts:22` |
| FE `VITE_FIREBASE_MEASUREMENT_ID` | unset | `initAnalytics()` resolves null | From GitHub secrets | `FE/src/lib/firebase.ts:35-38` |

---

## 2. Risk register

IDs are grouped by area. "Detect via" names the test the pipeline should carry.

### 2.1 Payments / billing / tips

| ID | Sev | Status | Item | Where | Detect via |
|---|---|---|---|---|---|
| R-BIL-1 | **P0** | owner-action | **Stripe live-mode not enabled.** Subscriptions and tips are test-mode/dormant; `Plan` seed prices are placeholders (`supporter` $5, `creator_pro` $15). Real money cannot flow. | `Docs/STRIPE_GOLIVE.md` (runbook), `billing/migrations/0002_seed_plans.py` | Contract test: `POST /billing/checkout-session` with a live-key env returns 200 with a `checkout.stripe.com` URL; plan amounts non-placeholder. |
| R-BIL-2 | **P0** | open (latent) | **Empty `STRIPE_WEBHOOK_SECRET` makes the webhook forgeable** once `STRIPE_SECRET_KEY` is set: `construct_event` is called with `settings.STRIPE_WEBHOOK_SECRET` (`''`) and `is_enabled()` only checks the secret key. An attacker could POST a signed-with-empty-secret `customer.subscription.updated` and grant themselves a paid plan. Flagged "PRE-EXISTING, affects subscriptions too" in the tips wave final review. | `billing/stripe_gateway.py:145-150`, `billing/views.py:256-275` | Unit test: with `STRIPE_SECRET_KEY` set and `STRIPE_WEBHOOK_SECRET=''`, webhook POST must be rejected (currently it would pass HMAC over `''`). Better: startup check that both are set together. |
| R-BIL-3 | P1 | open | **Plan quotas not enforced for most limits.** `EntitlementService.check_and_consume_quota` exists (`billing/entitlements.py:150-198`) but `get_limit` is only consumed for `free_reads_per_day` (`jokes/paywall.py:141`), `daily_joke_history_days` (`jokes/views.py:1321`), and `mystery_box_rolls_per_day` (`jokes/views.py:2784-2845`). Iteration-review promised limits (submissions/day, daily-joke sends) are not wired. Memory: "enforce plan quotas" listed as remaining. | `billing/entitlements.py`, `jokes/views.py` | Test per limit key in `Plan.limits` that an over-limit action returns 429/403; a test enumerating `KNOWN_LIMITS` vs call sites. |
| R-BIL-4 | P1 | open | **Webhook ordering / reconciliation gap.** `handle_event` dedupes on `event.id` only; there is no `event.created` comparison, so a delayed `customer.subscription.updated` (older) delivered after a newer one overwrites status/plan. No reconciliation job (no workers by design). Memory lists "webhook ordering/reconciliation" as remaining. | `billing/webhooks.py:291-313` | Test: deliver events out of order (newer `created` first) and assert final `Subscription.status/plan` reflects the newest. |
| R-BIL-5 | P1 | open | **Subscription period storage relies on `subscription.current_period_start/end`**, which newer Stripe API versions (2025-03 "basil"+) moved to `items.data[0]`. With `STRIPE_API_VERSION='2026-05-27.dahlia'` these `getattr` calls return `None` → `current_period_*` never set from subscription events (only `invoice.paid` stamps `period_end`). Memory: "subscription-period storage (basil API)" remaining. | `billing/webhooks.py:236-250`, `settings.py:511` | Test using a dahlia-shaped subscription object (period on item) asserting `current_period_end` is populated. |
| R-BIL-6 | P2 | open | `checkout.session.expired` unhandled → eternal `pending` Tip rows (totals safe: summaries are succeeded-only); no refund path / no `TipAdmin` registration for refund bookkeeping. | `billing/webhooks.py:302-311`, `billing/admin.py` | Test: `checkout.session.expired` moves Tip to `expired`/removed. |
| R-BIL-7 | P2 | open | Dead code flagged for owner: `price_id = None` assigned and unused in `_handle_checkout_completed` (`ruff F841` ignored per-file). | `billing/webhooks.py:180-182`, `pyproject.toml:66-69` | Lint ratchet (remove the per-file ignore). |
| R-BIL-8 | P2 | open | **No `/billing/success` or `/billing/cancel` FE route** — `BILLING_SUCCESS_URL`/`CANCEL_URL` default to `localhost:5173/billing/...`; prod env values unknown; FE `routes.tsx` has no such path, so Stripe returns users to the `*` NotFoundPage. SDD notes "Pre-existing: no /billing/success return route (subscriptions same; catch-all 404)". | `settings.py:513-515`, `FE/src/app/routes.tsx:146` | FE route test: `/billing/success` renders a confirmation, not 404; BE check that `BILLING_SUCCESS_URL` is non-localhost when `DEBUG=False`. |
| R-BIL-9 | P2 | open | `useMyTips` hook implemented but unwired (harmless). | FE `src/features/tips/` | — |

### 2.2 Compliance (COPPA / GDPR / DSA / CAN-SPAM / legal copy)

| ID | Sev | Status | Item | Where | Detect via |
|---|---|---|---|---|---|
| R-CMP-1 | **P0** | owner-action | **Legal documents are engineer-drafted and render a visible "DRAFT — pending counsel review" banner in production.** All four docs (`privacy`, `terms`, `cookie`, `children`) carry `DRAFT_NOTICE`, and `LegalDocPage` renders it unconditionally. Master plan CD5: "Shipping engineer-written placeholders to prod is the one legally-risky option." | `FE/src/content/legal/types.ts:1`, `FE/src/content/legal/*.ts:6`, `FE/src/pages/legal/LegalDocPage.tsx:30-43` | E2E: `/privacy`, `/terms`, `/cookie-policy`, `/childrens-privacy` must NOT contain the string "DRAFT" once counsel signs off; today the test would (correctly) fail. |
| R-CMP-2 | **P0** | deferred (by-design, known gap) | **No verifiable parental consent for under-13s.** Neutral DOB gate blocks <13 at signup (email + Google via `SocialAccountAdapter.pre_social_login`), but users who lie about DOB are not caught. Master plan documents this as a "known gap with a follow-up milestone"; FTC penalty $53,088/violation. | `JokesForProject/adapters.py`, master plan §Wave 1 Risks | Compliance suite: registration with DOB <13 → 400; Google signup without DOB → rejected. (Existing tests cover this; the *gap* is un-testable by design.) |
| R-CMP-3 | P1 | owner-action | **CSAM hash matching dormant** (`NullMatcher`); vendor (PhotoDNA/NCMEC/Thorn) application is an owner action. Memory: "gates open registration, not demo". | `jokes/media_screening.py:72-83` | Test that `get_matcher()` is not `NullMatcher` in prod settings (will fail until vendor onboarded). |
| R-CMP-4 | P1 | owner-action | **CAN-SPAM postal address placeholder `[COMPANY POSTAL ADDRESS]`** in 3 email templates; must be replaced before digests are activated. | `notifications/templates/notifications/email/base.html:13-16`, `daily_digest.txt:11`, `creator_milestone.txt:11` | Test: rendered digest email must not contain `[COMPANY POSTAL ADDRESS]`. |
| R-CMP-5 | P1 | open | **DSA notice-and-action incomplete.** Appeals (creator side), statements of reasons (rejection/takedown notices), SLA admin queue and reversible takedown are shipped. Missing vs readiness report: reporter acknowledgement/outcome notification to the *reporter*, and report dedup (see R-MOD-1). No email/notification on report receipt (master plan: intentionally out of scope). | `jokes/views.py` (reports), `inbox/` | Test: after a report is resolved, reporter receives a Notification; currently none. |
| R-CMP-6 | P1 | open | **Legal links absent from `FlowAppShell`.** Only `Layout.tsx` (legacy shell) renders `Footer` with Privacy/Terms/Cookie/Children's links; `LandingPage` and `RegisterPage` hard-link some. Most canonical pages (FlowAppShell-based) surface no legal links — master plan flagged this ("App-Store reviewers may not find them"). | `FE/src/components/Footer.tsx:14-17`, `FE/src/components/Layout.tsx`, `FE/src/pages/LandingPage.tsx:474-477` | FE test: `FlowAppShell` renders links to `/privacy` and `/terms`. |
| R-CMP-7 | P2 | open | **Consent record has no version field**, so a material policy change cannot force a re-prompt (master plan risk). `useConsent` stores boolean via `writeConsent`. | `FE/src/features/consent/useConsent.ts`, `storage.ts` | Test: bumping a `CONSENT_VERSION` constant makes `readConsent()` return null. |
| R-CMP-8 | P2 | open (verify) | **Analytics only initialises on the `accept()` click**; `initAnalytics` has no call site on app boot, so on the next page load a consented adult's analytics never re-initialises (consent is honoured; analytics is effectively dead after the first session). Functional, not compliance, gap. | `FE/src/features/consent/useConsent.ts:20-27`; grep shows no other `initAnalytics` caller | FE test: with stored consent=true and adult user, mounting `App` calls `initAnalytics()` once. |
| R-CMP-9 | P2 | by-design | Account-delete for Google-only users uses a typed `DELETE` confirmation rather than password re-auth (weaker assurance; master plan risk). | `jokes/views.py` account delete (~2440-2460) | Test asserts non-matching confirmation → 400. |
| R-CMP-10 | P2 | open | GDPR export shape drift: `build_user_export` must be updated as user-FK models are added (Tip, Appeal, JokeWatch, MediaAsset added since). Master plan recommended a test that fails when a user-FK model is missing from the export. | `jokes/data_export.py` (or equivalent) | Test: enumerate models with FK to `auth.User` and assert each appears in the export manifest. |

### 2.3 Security / auth

| ID | Sev | Status | Item | Where | Detect via |
|---|---|---|---|---|---|
| R-SEC-1 | P1 | owner-action | **Resend API key compromised (shared in plaintext during a build session) — rotation still pending** per memory `project_email_verification_live.md`. | Secret Manager `resend-api-key` | Ops checklist; no code test. |
| R-SEC-2 | P1 | owner-action | **Untracked `.env.bak.1783242100` in the BE repo root is NOT gitignored** (`git check-ignore` → not ignored; `.gitignore:13-15` covers `.env`, `.env.local`, `.env.*.local` only). One careless `git add -A` commits secrets (local `.env` mirrors prod: Neon `DATABASE_URL`, Resend key). | `BE/.gitignore:12-15`, repo root | CI guard: fail if any `.env*` file (other than `.env.example`) is tracked; add `.env.bak*`/`.env*` pattern. |
| R-SEC-3 | P1 | depends-on-env | CSRF enforcement on cookie-JWT **depends on `JWT_COOKIE_SAMESITE=None`** in Cloud Run env; reverting to `Lax` 403s every cookie-only mutation. `OLD_PASSWORD_FIELD_ENABLED=True` is a kept interim mitigation. | `settings.py:379-390, 440-453` | Smoke: cross-origin `POST` with cookie + `X-CSRFToken` → 2xx; without token → 403. Existing `jokes/tests_csrf.py`. |
| R-SEC-4 | P2 | open | Security scanners are **non-blocking** in CI (`bandit ... || true`, `pip-audit ... || true`); the "ratchet to blocking" never happened. Residual `cryptography` 46.x has 4 advisories fixed only in 48-50 (major bump held back). | `BE/.github/workflows/ci.yml:71-76`, memory `project_quality_seo_metrics` | CI config test / policy: flip to blocking with an allowlist. |
| R-SEC-5 | P2 | open | `raise ... from` omissions (B904) in exception-translation code lose original tracebacks — "owner should review individually". | `pyproject.toml:53-58` (`adapters.py`, `media_probe.py`, `media_processing.py`) | Lint ratchet. |
| R-SEC-6 | P2 | by-design | Anonymous paywall is a **deliberately soft wall** — signed cookie `jf_anon_reads`; clearing cookies resets the 10/day cap. Also `record_anon_read` lacks a twice-per-response guard (minor). | `jokes/paywall.py:17-22, 75-110` | Test documents the soft semantics (tampered cookie → treated as empty ledger, not error). |
| R-SEC-7 | P2 | open | Observability redaction `_DENYLIST` is exact-match; future secret headers (beyond `X-Digest-Token`, auth, cookies) would leak to Sentry unless added. | `JokesForProject/observability/redaction.py` | Test: any header containing `token`/`secret`/`key` (case-insensitive) is scrubbed. |

### 2.4 Moderation / content safety

| ID | Sev | Status | Item | Where | Detect via |
|---|---|---|---|---|---|
| R-MOD-1 | P1 | open | **`ContentReport` has no uniqueness on (reporter, joke) and no view-level dedup** — a user can spam duplicate reports (master plan D4 never resolved; grep for "already reported" finds nothing). No scoped throttle on `/reports/` (global 1000/hr only). | `jokes/models.py:754-776` (`Meta` has only an index) | Test: second POST `/reports/` by same user on same joke → 409/400 (currently 201). |
| R-MOD-2 | P2 | owner-action | Screening `'error'` status (Vision failure → fail-open) has limited admin visibility; a Vision outage silently sends unscreened media to the human queue. | `jokes/media_screening.py:44-55`, `jokes/admin.py` | Test: asset with `screening_status='error'` is highlighted/filterable in admin changelist. |
| R-MOD-3 | P2 | by-design | Quarantine-lapse purge (14d) and orphan-asset sweep are **request-triggered** (on upload and on appeal create) — with zero traffic, lapsed quarantine content is never purged. | `jokes/views.py:1469-1471, 2333-2334`, `jokes/quarantine.py:15` | Time-travel test: uphold + 14d + any upload → files gone (exists); document that no traffic = no purge. |
| R-MOD-4 | P2 | open | Blocking is one-directional and hides almost nothing content-side (design decision D1); `TopJokestersView` is AllowAny so anonymous viewers see blocked creators. | `follows/`, `jokes/views.py` TopJokesters | Documented expectation test. |
| R-MOD-5 | P2 | open | Non-self-healing old-path duplicate after quarantine delete-failure; duplicate `content_takedown` audit on retried takedown (accepted tradeoffs). | `jokes/quarantine.py` | — |

### 2.5 Reliability / ops / infra

| ID | Sev | Status | Item | Where | Detect via |
|---|---|---|---|---|---|
| R-OPS-1 | P1 | unknown | **Database backups / PITR never verified; no pre-migration snapshot step.** Readiness report lists it as a release requirement; no mention in `Docs/CICD_SETUP.md` (only a "Rollback" section for Cloud Run traffic) or anywhere else in either repo. Neon provides PITR by default but retention/verification is unconfirmed. | `cloudbuild.yaml` (migrate step has no snapshot), `Docs/CICD_SETUP.md:130` | Ops runbook item; optionally a Cloud Build step that calls Neon branch/snapshot API before `migrate`. |
| R-OPS-2 | P1 | open (infra) | **Prod `/healthz` returns a Google-edge 404** (Django never sees it); `/readyz` works. Any uptime check pointed at `/healthz` is dead. Route exists in code (`urls.py:33`). Today's E2E log F-001 proposes a `/livez` alias. | `JokesForProject/urls.py:33`, `health.py:34-42` | Prod smoke: `GET /healthz` → 200 JSON (currently fails). |
| R-OPS-3 | P1 | owner-action | **No alerting/dashboards/uptime checks applied.** `ops/monitoring/` (log-based latency metric + dashboard) is versioned but owner-gated; observability plan's alert policies never created; Sentry DSN presence unverified. | `ops/monitoring/README.md`, `Docs/superpowers/plans/2026-06-17-observability-plan.md` | gcloud describe checks in an ops smoke script. |
| R-OPS-4 | P1 | owner-action | **Cold starts 10-14 s** (`min-instances=0`); `max-instances=3` with inline video encode tying up a worker ~20 s. Teed-up `--min-instances=1` not applied. Today's prod smoke: `/readyz` 18.99 s cold. | `ops/monitoring/README.md §3` | Prod latency smoke with p95 budget (e.g. warm `/api/v1/jokes/` < 1.5 s). |
| R-OPS-5 | P1 | open | **Deploy pipeline has no test gate**: `cloudbuild.yaml` = build → push → migrate → deploy on push to `main`; GitHub Actions CI runs in parallel but cannot block Cloud Build. A red CI commit still deploys. | `BE/cloudbuild.yaml`, `.github/workflows/ci.yml` | Policy check: branch protection requiring CI before merge to `main` (owner setting), or a test step in `cloudbuild.yaml`. |
| R-OPS-6 | P1 | open | **DRF throttling uses the DB-backed cache** → ~12 extra Neon queries per request (2 throttle classes × 6), a ~500-700 ms app-wide floor. Flagged as the "highest-leverage latency win", not scoped. | `settings.py:187-195, 303-306` | `assertNumQueries` on a trivial endpoint; latency budget test. |
| R-OPS-7 | P2 | open | Backend CI note: "has not been run on actual GitHub Actions infrastructure yet" (workflow comment) — later commit `2a9377c ci: pin lint/scan tool versions…` suggests it has since run, but the stale comment remains. | `.github/workflows/ci.yml:87-90` | — |
| R-OPS-8 | P2 | owner-action | Dependabot/Actions must be enabled in repo settings (both repos have `dependabot.yml`); Google Search Console verification + sitemap submission; default OG image is SVG (X/Twitter will not render) — owner to export 1200×630 raster. | `.github/dependabot.yml` (both), `FE/public/` | — |
| R-OPS-9 | P2 | open | Local dev DB migrations behind code (jokes 33/36, notifications 2/4, billing 3/4, inbox 1/4) and legacy `django_celery_*` tables remain (E2E log F-003). macOS needs `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` for cairosvg (F-002). | E2E run log | Dev-env doc note. |
| R-OPS-10 | P2 | owner-action | `demo.creator@jokesfor.dev` prod login rejected (password drift) — blocks the authenticated real-device media pass; `seed_demo_creator` previously reset a real account's password (fixed 2026-07-11 but re-seed still owner-gated). Share-card backfill (`backfill_share_cards --apply`) for ~300 cardless seed jokes not run on prod. | `jokes/management/commands/seed_demo_creator.py`, `backfill_share_cards.py` | Prod smoke: seed joke `share_image_url` non-null. |
| R-OPS-11 | P2 | open | Email delivery is best-effort synchronous (Resend via anymail, no retry queue by design); `EmailMessageLog` is the only audit. | `notifications/` | Test: transport failure logs `failed` status without 500. |

### 2.6 Product / frontend gaps

| ID | Sev | Status | Item | Where | Detect via |
|---|---|---|---|---|---|
| R-FE-1 | P1 | open | **Playwright E2E is a placeholder**: only `e2e/example.spec.ts`, and it asserts legacy copy ("Find Your Perfect Joke", "Dad Jokes" button, "Toggle menu") that the current `LandingPage` does not render — it would fail if run. No E2E in CI. | `FE/e2e/example.spec.ts`, `playwright.config.ts:12` | Replace with real smoke specs (login, reveal, paywall, create); wire into CI. |
| R-FE-2 | P2 | open | 10 `react-hooks/set-state-in-effect` warnings + 13 `react-refresh/only-export-components` demoted to `warn` to green the CI gate; the former "can flag real bugs". | `FE/eslint.config.*:32-43` | Lint ratchet: re-promote to error after cleanup. |
| R-FE-3 | P2 | open | Prettier introduced without reformat: 277 files unformatted (ratchet). | `FE/.prettierrc`, memory | `prettier --check` on changed files. |
| R-FE-4 | P2 | open | Onboarding `streakSaver` toggle is visual-only ("TODO wire"); `RegisterPage` step-2 pronouns/venue have no backend fields; `SubmissionDetailPage` "View public" link omitted until `ContentDraft` exposes `publishedId`. | `FE/src/pages/FlowPage.tsx:33`, `RegisterPage.tsx:18`, `SubmissionDetailPage.tsx:224` | FE tests asserting the toggle PATCHes `streak_saver_enabled` (currently would fail). |
| R-FE-5 | P2 | open | DTO shape TODOs: `api.ts:372` (replace `unknown` returns, sync mock shapes), `api.ts:429` (profile activity/achievements "speculative"). | `FE/src/lib/api.ts:372, 429` | Contract tests against OpenAPI schema (`/api/schema/`). |
| R-FE-6 | P2 | open | Legacy mirror routes (`/legacy/*`) and `<Name>Legacy.tsx` components still shipped; `JokeCard`/`FlowJokeCard` and `Layout`/`FlowAppShell` unconsolidated (Redesign_Plan follow-ups). | `FE/src/app/routes.tsx:131-143` | Bundle-size / dead-route audit. |
| R-FE-7 | P2 | open | Media fast-follows: GIF stop-on-tap (WCAG 2.2.2), keyboard reveal affordance, `FlowCanvasPage` has no test file, insights chip label casing + duration-formatter duplication, mock GIF/video-poster objectURL quirks. | SDD progress ledger "POST-MERGE FAST-FOLLOWS" | a11y test: GIF pauses on tap; `FlowCanvasPage.test.tsx` existence. |
| R-FE-8 | P2 | open | Appeals adapter maps a 404 to an empty list ("endpoint not yet deployed") — masks a real routing regression on `/appeals/mine/`. | `FE/src/features/appeals/api.ts:11`, `api-adapter.test.ts:676` | Contract test that prod `/api/v1/appeals/` is 401 (not 404) for anon. |
| R-FE-9 | P2 | open | Pre-reveal carousel drag could early-reveal; 0:00 duration chip on zero-duration media; GIF+reduced-motion+no-poster blank frame (minor triage items). | FE media renderers | Component tests. |
| R-FE-10 | P2 | by-design | Static prerender and bot-rendering for FE content routes **deferred**; social scrapers rely on BE `/jokes/:id/share/` page and build-time `sitemap.xml` (`scripts/gen-sitemap.mjs`, fail-soft → stale between deploys). | spec 2026-08-04 §2d, memory | Smoke: `curl -A facebookexternalhit /jokes/<id>/share/` returns per-joke OG tags. |

### 2.7 Monetization business decisions (not code)

| ID | Sev | Status | Item |
|---|---|---|---|
| R-BIZ-1 | P1 | owner-action | Iteration review open decisions 1-5: paid-vs-free feature catalog, per-plan numeric limits, tier count/names, real prices/currency/annual/trials, when to flip to live keys + Push-to-Stripe. Anonymous-paywall policy decided (soft 10/day cookie wall). |
| R-BIZ-2 | P2 | owner-action | Accelerator/traction: pre-launch traction gap is the binding constraint (memory `project_accelerator_prep`). |

---

## 3. The "24 should-fix" list — what can be reconstructed

The 2026-07-13 17-agent audit produced 81 findings: 6 launch-blockers, 24 should-fix, 23 post-MVP. The canonical list lived in a Claude artifact (`ba6032d7-75f1-4ea3-8077-29bda451a5d1`) that is **no longer retrievable** ("artifact not found"), and neither `Docs/`, `.remember/` (daily logs + tar archives) nor `.superpowers/sdd/` contains the enumerated list. What is recoverable from `memory/project_launch_blockers.md`, `.remember/today-2026-07-13.done.md` and the 08-04 memory:

**Should-fix — DONE (demo-credibility subset, deployed 2026-07-13):**
1. `_top_jokes` cartesian-join perf → correlated subqueries (85 tests).
2. Fabricated stats removed; ProfilePage wired to real profile/activity/achievements.
3. Trending-collections email-local-part leak → `public_display_name`.
4. Collections create + `/collections/:id` detail wired.
5. Settings change-password (old_password) / delete-account (type DELETE) / data-export wired.
6. Discovery filter slugs corrected + pagination + Trending/Daily/Favorites nav + Library collection buttons.
7. (from 07-11 log) Explore/Search mock→real; dead Edit button; save bug; editor race; billing `is_premium` sync; checkout→localhost redirect.

**Should-fix — STILL REMAINING (memory: "money/compliance hardening, not demo-facing"):**
8. Finish Stripe live-mode (live keys, onboarding) → R-BIL-1
9. Enforce plan quotas → R-BIL-3
10. Subscription-period storage (basil API) → R-BIL-5
11. Webhook ordering/reconciliation → R-BIL-4
12. DSA report SLA + appeals → partially done (appeals wave); reporter-side ack open → R-CMP-5
13. Scoped rate-limits on high-volume actions → only `media-upload`, `appeals`, `tips-checkout`, `verification_resend`, `creator_insights` scoped (`settings.py:307-316`; `jokes/views.py:1496, 2316`); reactions/favorites/reports/reveal ride the global 1000/hr → R-MOD-1
14. CI test gates → done for GitHub Actions (BE+FE) but not in the deploy path → R-OPS-5
15. Backups/DR → R-OPS-1

Items 16-24 of the original list are unrecoverable from local sources; the most likely candidates, judging by the same-era plan risks, are: consent versioning (R-CMP-7), FlowAppShell legal links (R-CMP-6), report dedup (R-MOD-1), `/billing/success` route (R-BIL-8), Sentry/alerting confirmation (R-OPS-3), `min-instances` (R-OPS-4), Playwright E2E (R-FE-1), export-shape drift test (R-CMP-10), analytics re-init (R-CMP-8). Treat that mapping as inference, not record.

---

## 4. Owner-activation checklist (consolidated, all parked and non-blocking for demo)

From `memory/project_mvp_slate_complete.md`, `project_quality_seo_metrics.md`, `project_media_jokes.md`, `project_email_verification_live.md`, SDD ledger:

1. **Stripe live**: set `STRIPE_SECRET_KEY` **and** `STRIPE_WEBHOOK_SECRET` together (R-BIL-2); set real `BILLING_*_URL`s; edit plan prices in admin; Push-to-Stripe; register `Tip` in `billing/admin.py`; complete Stripe business onboarding.
2. **Digest**: replace `[COMPANY POSTAL ADDRESS]` in 3 templates; set `DIGEST_CRON_TOKEN`; create Cloud Scheduler job (`--attempt-deadline=320s`, retries=0); watch first `DigestRun` in admin.
3. **Ops**: apply `ops/monitoring/` metric + dashboard; `--min-instances=1`; consider `--max-instances`; fix/alias `/healthz`; verify Sentry DSN; alert policies + uptime check on `/readyz`; verify Neon PITR/backups; rotate Resend key; delete or gitignore `.env.bak.*`.
4. **SEO**: Search Console verify + sitemap submit; export raster OG image.
5. **Repo settings**: enable Dependabot + Actions; branch protection requiring CI on `main`.
6. **Content safety**: CSAM vendor application; re-seed demo creator on prod; real-device media pass (HEVC .mov, GIF, audio, reduced-motion, >32 MB → 413 check); `backfill_share_cards --apply`.
7. **Legal**: counsel review of the four legal docs; remove `DRAFT_NOTICE`; ToS clip-wording already owner-approved.
8. **Decisions**: `cryptography` 46→50 major bump; monetization tiers/prices.

---

## 5. Docs vs code disagreements (explicit)

| Claim (doc) | Code reality |
|---|---|
| `memory/project_email_verification_live.md`: "Migrations do NOT run in the pipeline (Dockerfile ends at gunicorn) — apply manually" | **Outdated.** `cloudbuild.yaml` step 3 `Migrate` runs `manage.py migrate --noinput` inside the built image before Deploy (since 2026-06-19). |
| Progress Update: "800+ automated tests that run every time we change something" | True for GitHub Actions on PR/main; **not** a gate on the Cloud Build deploy trigger (R-OPS-5). |
| Readiness Report: "Compliance — COPPA/GDPR foundations Live; DSA workflow pending" | Appeals/notices/SLA shipped 2026-07-24; reporter acknowledgement and report dedup still absent. |
| `Redesign_Plan.md`: adapters "mock-only until shapes confirmed" | All adapters key on `USE_MOCKS` (false in deploy builds); the plan's follow-ups list is stale except consolidation items. |
| Iteration review: "`BILLING_ENABLED` — when to flip" | Flag is dead code; gating is purely `STRIPE_SECRET_KEY` (`Docs/STRIPE_GOLIVE.md` says so; `settings.py:512` sole reference). |
| `CONCERNS.md` (Jan 2026) | Every item closed; file is a scaffold-era snapshot. |
| `ci.yml` comment: "has not been run on actual GitHub Actions infrastructure yet" | Subsequent `ci:` commits (`2a9377c`) imply it has; comment stale. |
| Master plan: "Firebase Analytics auto-inits at app boot (main.tsx `import './lib/firebase'`)" | **Fixed**: `main.tsx` has no firebase import; `firebase.ts` is lazy, `initAnalytics` only from `useConsent.accept()` for verified adults. (New gap: never re-inits on reload — R-CMP-8.) |
| Master plan: "content_tier enforced in ZERO serving paths" | **Fixed**: `allowed_tiers`/`paywall_state` injected across list/feed/search/favorites/saved/mystery/recently-viewed/packs (per SDD Task 6b) and tier-safe sitemap/share pages. |

---

## 6. Recommended detection tests for the pipeline (priority order)

1. **Stripe webhook secret guard** (R-BIL-2): with `STRIPE_SECRET_KEY` set and `STRIPE_WEBHOOK_SECRET=''`, `POST /api/v1/billing/webhook` with a payload signed using `''` must be rejected.
2. **Legal draft banner** (R-CMP-1): FE render test / prod smoke that legal pages contain no "DRAFT" text — expected to fail until counsel sign-off; keep as a red launch gate.
3. **Report dedup** (R-MOD-1): duplicate `POST /api/v1/reports/` → non-201.
4. **Webhook out-of-order** (R-BIL-4) and **dahlia period fields** (R-BIL-5).
5. **Quota enforcement enumeration** (R-BIL-3): every key in `Plan.limits` has a call site.
6. **`/healthz` prod smoke** (R-OPS-2) and warm-latency budget (R-OPS-4/6).
7. **Throttle query floor** (R-OPS-6): `assertNumQueries` on `/api/v1/formats/` ≤ N.
8. **Analytics re-init** (R-CMP-8) and **consent version** (R-CMP-7) FE unit tests.
9. **FlowAppShell legal links** (R-CMP-6).
10. **Postal-address placeholder** (R-CMP-4) in rendered digest emails.
11. **`.env*` never tracked** (R-SEC-2) CI guard.
12. **Real Playwright smoke** replacing `example.spec.ts` (R-FE-1).
13. **Export completeness** (R-CMP-10): every user-FK model appears in the GDPR export.
14. **Appeals 404-masking** (R-FE-8): prod contract test that `/api/v1/appeals/` is 401 for anon, never 404.
