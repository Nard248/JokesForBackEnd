# Wave 1 — Decisions Locked & Your Action Items

> Autonomous session started **2026-06-16**. This file records (a) the verified state of Wave 0, (b) the Wave 1 design decisions I locked so I could proceed without you, and (c) everything that needs **you** (non-implementational / external blockers). Review and override anything you disagree with.

---

## A. Wave 0 — verified LIVE in prod (2026-06-16)
Pushed via CI/CD and confirmed against `https://jokesforbackend-332865216810.us-east1.run.app`:
- ✅ New image deployed: a Django 404 on `/api/v1/bogus/` carries `strict-transport-security: max-age=31536000; includeSubDomains; preload` → **HSTS/hardening active**, request reaching the container.
- ✅ Service healthy: `/admin/` → 302 login, `/api/v1/jokes/` → 200 (159 jokes).
- ℹ️ **`/healthz` returns 404 on the public URL** — but it's an **edge/load-balancer intercept** (the 404 lacks Django's headers + `x-cloud-trace-context`), not a missing endpoint. `/healthz` exists in the image; your external LB/URL-map only forwards app paths. **Not a blocker** — Cloud Run startup/liveness probes hit the container directly and will reach `/healthz`. See "Your action items" if you want it public.

### Please confirm on your side (I can't see the console / prod DB):
1. **`SECRET_KEY`** — was it already set (no user impact), or did you create a new one (everyone logged out once)? Just so we know.
2. **Migration `notifications.0002_create_cache_table` applied to prod Neon?** The shared throttle cache needs the `jokesfor_cache` table. Quick check: in Neon SQL editor run `SELECT count(*) FROM jokesfor_cache;` — if it errors with "relation does not exist", the migration didn't run against prod and throttling will error. Tell me and we'll fix.
3. **`GS_BUCKET_NAME` env is set on Cloud Run** and the bucket `jokesfor-media-prod` is public-read + the runtime SA has Storage Object Admin. (I'll auto-verify once a share card regenerates — currently all `share_image_url` are null.)

---

## B. Wave 1 decisions I LOCKED (override if you disagree)
The milestone is a **legally-launchable, text-only MVP**. I adopted the master plan's recommended (YAGNI) answers so I could build without waiting:

| ID | Decision | Locked choice |
|----|----------|---------------|
| **CD1** | Firebase Analytics boot-gating | Remove the eager `import './lib/firebase'` in `main.tsx`; expose `initAnalytics()` defaulting **OFF**; only fire after consent **and** adult age. (Required for COPPA zero-data Kids handling + GDPR/ePrivacy consent.) |
| **CD2** | Where DOB lives + COPPA depth | DOB on existing `UserProfile` (NOT a custom `AUTH_USER_MODEL` swap). For launch: **block under-13 at a neutral DOB gate**; DEFER the full verifiable-parental-consent vendor flow (external — see C). |
| **CD3** | `content_tier` serving enforcement | One `allowed_tiers(request)` resolver applied at **every** read path (list, random, search, recommendations). anon / Kids / under-18 / null-DOB → `{tier_1}`; adults → `{tier_1, tier_2}` with explicit opt-in; `tier_3` never served. **(This is the real COPPA exposure.)** |
| **CD4** | Consent banner | Simple **Accept / Reject (essential-only)**, stored in `localStorage` as a versioned record `{version, analytics, ts}`. No category toggles (only one non-essential tracker exists). |
| **CD5** | Legal copy authorship | Engineer-drafted from reputable templates into typed TSX content modules under `src/content/legal`, each marked **DRAFT — pending counsel review**. (Counsel review is external — see C.) |
| **CD6** | GDPR export + deletion | **Synchronous in-request** zipped-JSON export (no worker). **Confirmed hard delete** with re-auth (password; typed confirmation for Google-only accounts), purging avatar from storage + `EmailMessageLog`, inside a transaction. |
| **CD7** | Moderation scope | **Deferred to Wave 2** (not on the launch critical path; jokes have no author FK so block-enforcement is minimal). |

---

## C. Needs YOU — deferred, non-implementational blockers
These can't be done from the machine/console by me; tackle when you're back:

1. **Legal counsel review of the DRAFT legal pages** (Privacy, Terms, Cookie, Children's Privacy). I will write complete, reasonable drafts marked `DRAFT`, but a lawyer must review/finalize **before public launch**. This is the long-pole — start it in parallel.
2. **COPPA under-13 strategy.** I'm implementing **"block under-13 at signup"** (compliant, simplest). If you instead want to *serve* under-13 with verifiable parental consent, that requires an **FTC-approved VPC vendor** (e.g., a paid age-verification/consent service) + a parental dashboard — a vendor signup + budget decision. Tell me which way; default is block.
3. **Confirm the Wave 0 prod checks** in section A (SECRET_KEY, the `jokesfor_cache` migration, `GS_BUCKET_NAME`).
4. **(Optional) Expose `/healthz` publicly** — only if you want external uptime monitoring. Add a `/healthz` path rule to your load-balancer URL-map. Otherwise leave as-is (probes work container-direct).
5. **(Optional) `SENTRY_DSN`** if you want error monitoring (Wave 0 wired it; dormant until set).

**No new GCP/infra is required for Wave 1 itself** — it's all application code.

---

## D. What I'm building autonomously this session (Wave 1)
Work-streams (subagent-driven, two-stage reviewed, merged to local `main`, then pushed for CI/CD):
1. **Frontend: Firebase gate + consent banner + legal pages** (CD1, CD4, CD5) — also fixes the dead `/privacy` `/terms` links.
2. **Backend: COPPA** — DOB on UserProfile, neutral age gate at registration (block under-13), `content_tier` serving lock at all read paths (CD2, CD3).
3. **Frontend: age-gate UI** at registration + minor/anonymous handling (CD2).
4. **Backend: GDPR** synchronous export + safe account deletion (CD6).

Progress and any new blockers will be appended here and to the plan docs under `Docs/superpowers/plans/`.

---

## E. Wave 1 COMPLETE (2026-06-17) — merged to local `main`, NOT pushed/deployed
All four work-streams implemented subagent-driven (implementer + spec review + code-quality review each, plus a final holistic review), merged to **local `main`** in both repos, branches deleted:
- Backend `main` @ `da949bd` — **143 tests OK**, `manage.py check` clean, `makemigrations --check` clean.
- Frontend `main` @ `a9ae447` — **398 tests OK**, `tsc` + `vite build` clean.

Delivered: CD1 firebase-analytics consent gate + Accept/Reject banner + DRAFT legal pages (dead links fixed); CD2 DOB age gate (under-13 blocked, enforced **server-side** independent of the UI) on the existing UserProfile; CD3 `content_tier` serving lock across **every** read path (anon/under-18/null-DOB → tier_1; adult+opt-in → +tier_2; tier_3 never), fail-safe to tier_1; CD6 synchronous GDPR export (zipped JSON, no PII leak) + re-auth hard-delete (purge avatar/email-logs, blacklist tokens). Also exposed the user's own `date_of_birth` on `/auth/user/` so the consent-analytics adult-gate actually works.

The final review's verdict: **this is honestly a legally-launchable text-only MVP**, modulo the deferred external items below.

### E1. DEPLOY RUNBOOK — YOU must run this (deferred: prod-affecting, infra, not verifiable from the machine)
I did NOT push, because the deploy has two real risks I can't safely own autonomously:

1. **Migrations MUST run on deploy.** Wave 1 adds `jokes/0023_userpreference_show_mature_userprofile_date_of_birth`; Wave 0 added `notifications/0002_create_cache_table`. There is **no CI/CD config in the backend repo**, so your deploy (Cloud Build trigger / manual) likely does **not** run `migrate` automatically. Run `python manage.py migrate` against prod Neon as part of the deploy (Cloud Run Job, Cloud Shell, or from your machine with the prod `DATABASE_URL`). If the cache table from Wave 0 was never applied, this run fixes that too.
2. **Deploy ORDER matters (cross-repo).** The backend now **requires** `date_of_birth` at registration. If the **backend** deploys *before* the **frontend**, the old frontend won't send DOB → **all registrations 400** until the frontend deploys. So: **deploy the FRONTEND first (or both together)**. Frontend-first is safe — the old backend ignores the extra field (age-gate is briefly UI-only).

**To deploy:** `git push origin main` in the **frontend** repo (triggers Firebase Hosting), then `git push origin main` in the **backend** repo and ensure `migrate` runs before/with the new revision. Tell me when pushed and I'll re-run the live verification (under-13 → 400, tier_2 404 for anon, analytics only after consent+adult, /healthz).

### E2. Still deferred — needs YOU (unchanged)
- **Legal counsel review** of the DRAFT legal pages (Privacy/Terms/Cookie/Children's) before public launch. Start this now (long-pole).
- **Under-13 strategy:** currently **blocked at signup** (compliant, simplest). If you want to *serve* under-13 with verifiable parental consent, that needs an FTC-approved VPC vendor + parental dashboard — a vendor/budget decision.
- **Confirm Wave 0 prod values** (SECRET_KEY set; `jokesfor_cache` table exists; `GS_BUCKET_NAME` set + bucket public).

### E3. Minor code follow-ups (non-blocking, recorded so they're not lost)
- GDPR delete: empty-string password returns "required" instead of "incorrect"; a dead `(request.data or {})` branch; the anti-leak test uses a full-JSON `dumps` substring check (the targeted assertions already cover it). All cosmetic.
- `ConsentBanner` uses inline styles vs. the codebase's Tailwind; `isAnalyticsInitialized()` name slightly over-promises (test-only). Cosmetic.
