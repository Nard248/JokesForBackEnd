# JokesFor — Iteration Review (2026-06-19)

> For owner review. This iteration shipped four things — **CI/CD**, **observability**, **slice‑2 (follow + creator pages)**, and the **monetization engine** — plus the earlier MVP 0.2 creator‑insights demo. Everything is committed to **local `main`** in both repos and **not yet pushed/deployed** (you control that). Read this, then we re‑iterate the parts that don't match your business decisions — especially monetization pricing/tiers.

## TL;DR

| Part | Status | Tests | Where |
|---|---|---|---|
| CI/CD (GCP‑native Cloud Build) | ✅ done, wired in GCP | n/a | `cloudbuild.yaml`, `Docs/CICD_SETUP.md` |
| Observability & logging | ✅ merged | 250 | `JokesForProject/observability/`, `audit/` |
| Slice 2 — follow + `Joke.creator` + creator profiles | ✅ merged (BE+FE) | 301 BE | `follows/`, `creator_insights/`, FE `CreatorProfilePage` |
| Monetization engine (entitlements + Stripe) | ✅ merged (BE+FE) | 362 BE / 448 FE | `billing/`, FE `BillingPage` |

Backend `main` HEAD `d75205a` (362 tests, `manage.py check` clean). Frontend `main` HEAD `24b1f4f` (448 tests, build clean). **Nothing is pushed** — the deploy trigger only fires on push.

Design docs (deeper detail) live in `Docs/superpowers/`: `2026-06-17-observability-design.md`, `2026-06-19-slice2-follow-creator-design.md`, `2026-06-19-monetization-design.md` (+ their plans under `plans/`).

---

## How to deploy (when you're ready)

CI/CD is **GCP‑native** and already wired (no GitHub Actions). On push to `main` the existing Cloud Build trigger runs `cloudbuild.yaml`: **migrate → build → deploy** to Cloud Run.

- Already done by me (via gcloud): trigger now uses `/cloudbuild.yaml`; the build SA (`…-compute@…`) has `secretmanager.secretAccessor`. The `database-url` secret already existed.
- **You need only:** push **frontend first (or together)** then **backend** `main`. (Backend now *requires* `date_of_birth` at registration, so a backend‑only deploy ahead of the frontend would 400 registrations.)
- The first deploy's migrate step will also create the **`jokesfor_cache`** table (Wave 0's throttle cache) that the old no‑migrate trigger never applied — so throttling, which has likely been erroring in prod, gets fixed. (I can confirm via Cloud Logging on request.)
- Rollback: `gcloud run services update-traffic jokesforbackend --to-revisions=<prev>=100 --region us-east1`.

---

## 1. CI/CD (GCP‑native)
- `cloudbuild.yaml` mirrors your trigger's existing build/push/deploy steps (same Artifact Registry path/substitutions) and **inserts a migrate step that runs inside the built image** (so it has libcairo/pango + the exact code; a `slim` image would crash on `cairosvg` import). Migrate fails → deploy never runs → broken‑schema code is never served.
- Env stays on the Cloud Run service (secrets via Secret Manager: `database-url`, `django-secret-key`, `resend-api-key`, `google-client-secret`); the deploy never overwrites it.
- The GitHub Actions workflow I first drafted was **removed** to avoid double‑deploys.

## 2. Observability & logging
- New `JokesForProject/observability/` package: request‑id + Cloud‑Trace correlation (contextvars, reset per request), a Cloud Logging JSON formatter (clickable trace links), one structured access‑log line per request, and **PII/secret redaction** (passwords, JWT cookies, the 6‑digit code, authorization — never logged).
- New **`audit`** app: append‑only `AuditLog` (DB trigger blocks UPDATE/DELETE) recording login (incl. anti‑enumeration failures), registration, verification, account deletion, data export, reports, blocks.
- `/readyz` (DB + cache readiness → 503 when down) added alongside `/healthz` (pure liveness). Sentry enriched (release, PII scrub) and stays a no‑op until `SENTRY_DSN` is set.
- **Deferred to you (GCP console):** alert policies, dashboards, log‑based metrics, uptime check on `/readyz` — the precise checklist with thresholds is in `Docs/superpowers/plans/2026-06-17-observability-plan.md`.

## 3. Slice 2 — Follow + Creator pages
- **`Joke.creator` FK** (nullable, `SET_NULL`, indexed) — safe nullable schema migration + a **separate idempotent data‑migration backfill** from `submission.user`; stamped at publish; `resolve_creator_jokes` now uses the FK with a submission‑join fallback. (Locally the backfill is a no‑op — 0 published submissions; written correctly for prod.)
- **`follows`** app: `Follow(follower, creator)` (unique, indexed), self‑follow blocked, endpoints `follow/unfollow/status/followers` + `users/me/following`. Follower lists expose **no email**.
- **Creator profile**: public `GET /api/v1/creators/<id>/profile/` — identity, follower count, `is_following`, and the creator's published jokes **tier‑filtered for the viewer** (respects the COPPA content‑tier lock). Frontend page at **`/creators/:id`** with a Follow button; insights dashboard now shows followers + a follower‑growth sparkline.
- **Security note (fixed):** the commit security review flagged email‑derived public handles (PII/enumeration on public follower lists) — now opaque `user_<id>` (see follow‑ups for a real handle field).

## 4. Monetization engine (config‑driven + Stripe)
Built to be **edited on the go** — pricing/tiers/limits/features are data, not code.
- **`billing`** app: `Plan` (editable in admin — `features` JSON flags + `limits` JSON + money fields + Stripe ids), `Subscription` mirror, `UsageCounter` (lazy period reset — no cron), `ProcessedStripeEvent` (idempotency).
- **`EntitlementService`** (`billing/entitlements.py`): single choke‑point — `has_feature(user,key)`, `get_limit(user,key)`, `check_and_consume_quota(user,key)`. A **FREE default plan** so everyone works without a subscription. Admin edits to a plan's JSON take effect **on the next request, no deploy**.
- **Stripe**: env‑gated (dormant without `STRIPE_SECRET_KEY` — checkout/portal 503, webhook 200‑noop, entitlements still resolve to FREE). Endpoints: `plans`, `my-subscription`, `entitlements`, `checkout-session`, `portal-session`, `webhook`. The **webhook is signature‑verified (raw body), idempotent, synchronous** (no worker). Admin has a **Push‑to‑Stripe** action.
- Two real access points are gated as a demo: Mystery‑Box daily rolls (a limit) and creator analytics (a feature — granted on FREE so existing creators aren't locked out).
- **Frontend** `/settings/billing`: plans, current‑plan highlight, subscribe→checkout, manage→portal, entitlements/limits, dormant + offline‑demo states.
- **Seed plans are PLACEHOLDERS** (`free`, `supporter` $5, `creator_pro` $15) — see open decisions.

---

## Modular‑monolith structure
The codebase moved toward a modular monolith **additively** (no risky big‑bang refactor of the live `jokes` app): new focused apps `creator_insights/`, `audit/`, `follows/`, `billing/`, plus the `JokesForProject/observability/` package. Each reads existing models through clean service layers. Further extraction (e.g. splitting the fat `jokes` app) remains a future, optional step.

---

## Open decisions & follow‑ups (let's re‑iterate these)

**Monetization — business decisions (the engine ships ready; you set the values in admin):**
1. Which features are paid vs free (the `features` flags catalog).
2. The numeric `limits` per plan (mystery‑box rolls/day, submissions/day, daily‑joke sends, history depth, …).
3. Plan names, count, structure (how many tiers).
4. Actual prices + currency, monthly vs annual (+ discount), free trials, proration behavior.
5. When to flip `BILLING_ENABLED` / switch from Stripe **test** to **live** keys + run Push‑to‑Stripe.

**Engineering follow‑ups:**
6. ✅ **DONE (2026‑06‑20, backend `2c87f52`)** **Real creator handles** — added user‑chosen `display_name` + unique `handle` on `UserProfile`, settable via `PATCH /users/me/profile/` (normalized/validated/uniqueness‑checked). New `jokes/identity.py` is the single public‑identity helper (chosen handle/name → opaque `user_<id>`, never email); follows, creator profiles, and the profile endpoint all use it. 8 tests. *(Still open: apply the same helper to the pre‑existing `TopJokestersView`, and add the profile‑edit UI surface in the frontend.)*
7. ✅ **DONE (2026‑06‑20, frontend `437fccf`)** **Creator‑profile jokes shape** — `normalizeProfileJoke` in the creator‑profile adapter converts the lean `JokeListSerializer` shape (slug‑string tones/format/age_rating) into the object `Joke` shape `JokeCard` renders; tolerant reader (already‑nested objects pass through). +2 tests.
8. **Observability console setup** — alerts/dashboards/uptime (checklist in the observability plan).
9. **Deploy** — push (frontend first/together) when ready; confirm the `jokesfor_cache` table after the first migrate.

---

## How to demo locally (no backend / no Stripe needed)
Frontend in mock mode renders everything offline:
```
cd jokes-for-frontend && VITE_USE_MOCKS=true npm run dev
```
- `/create/insights` — creator analytics dashboard (KPIs, top jokes, audience taste, growth suggestions, followers + growth sparkline)
- `/creators/7` — public creator profile + working Follow button (toggles on mock state)
- `/settings/billing` — plans, subscribe (demo banner), entitlements/limits

Backend tests: `DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test --keepdb` (362). Frontend: `npm run test` (448).
