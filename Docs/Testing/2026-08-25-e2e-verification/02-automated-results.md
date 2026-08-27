# T0–T2 + T5 — Automated tier results (2026-08-25)

Environment: backend `56e4945`, frontend `04e1b2f`, local Postgres `jokesfor`, Python 3.11 / Django 5.2.17, Node 22.16.
All backend commands run with `DATABASE_URL='' DB_*=local DEBUG=True DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`.

## T0 — Static & build gates

| ID | Check | Result | Detail |
|---|---|---|---|
| T0-01 | `ruff check .` | **PASS** | "All checks passed!" (CI hard gate) |
| T0-02 | `manage.py check` | **PASS** | 0 issues, 0 silenced |
| T0-03 | `makemigrations --check --dry-run` | **PASS** | "No changes detected" — model code and migrations agree. **Not in CI; should be** (drift here means a prod deploy migrates an incomplete schema) |
| T0-04 | `check --deploy` (`DEBUG=False`) | **PASS (1 expected)** | 47 issues = 22 × `drf_spectacular.W002` + 24 related lines + **1** `security.W009`, which is only the throwaway `SECRET_KEY=x` passed to the check itself. **No real security warnings.** |
| T0-05 | OpenAPI schema completeness | **CONFIRMED-QUIRK** | **22 views emit `W002` "unable to guess serializer" and are omitted from the schema** — see F-008. Harmless for the hand-written SPA client, blocking for iOS codegen. |
| T0-06 | `npm run lint` | **PASS with debt** | 0 errors, **26 warnings** — including `react-hooks/set-state-in-effect`. Two `react-hooks` v7 rules were deliberately demoted to `warn` in `a3ef699` to make the gate green. |
| T0-07 | `tsc -b && vite build` | **PASS** | build succeeds (CI runs it on every PR) |
| T0-08 | `bandit` | **PASS (report-only)** | 12,202 LOC scanned: **0 High**, 2 Medium, 47 Low. Non-blocking in CI. |

## T1 — Backend suite

```
Ran 834 tests in 111.129s
OK
```

| ID | Check | Result | Detail |
|---|---|---|---|
| T1-01 | Full suite, local Postgres | **PASS** | **834/834, 0 failures, 0 errors, 111.1 s** (1m56s wall incl. DB create/destroy). This is the first recorded measurement of suite runtime — no prior doc had it. |
| T1-02 | ffmpeg-gated tests actually ran | **PASS** | **0 skips overall** — the 28 `@skipUnless(FFMPEG)` media tests genuinely executed against ffmpeg 8.1.2 (real encodes, not stubs) |
| T1-03 | cairo-gated share-card tests ran | **PASS** | real `cairosvg` renders executed (needs `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` on macOS — see F-002) |
| T1-04 | Skip census | **PASS** | **zero skipped tests.** No hidden lost coverage. |

## T2 — Frontend suite

```
Test Files  109 passed (109)
     Tests  798 passed (798)
  Duration  12.24s
```

| ID | Check | Result | Detail |
|---|---|---|---|
| T2-01 | `vitest run` | **PASS** | 798/798 in 12.2 s |
| T2-02 | Contract coverage limitation | **NOTED** | Every test runs in jsdom against `src/lib/mock-api.ts`. **Green here proves component logic, not the FE↔BE contract** — which is exactly why T3 exists, and exactly where the defects were found (F-004…F-007). |
| T2-03 | Untested pages census | **NOTED** | No test file for `FlowCanvasPage` (the authenticated home), `FlowPage` (onboarding), `SubmitJokePage`, `DraftsPage`, `PackDetailPage`, `TrendingPage`, `OnboardingPage`, `ForgotPasswordPage`, `NotFoundPage`. The two flows carrying the confirmed onboarding defects are both untested. |

## T5 — Production smoke

Prod revision at time of test: **`jokesforbackend-00046-bqv`**.

| ID | Check | Result | Detail |
|---|---|---|---|
| T5-01 | Cold start | **CONFIRMED-QUIRK** | `/readyz` cold: **15.2 s** (DB ping alone 768 ms, cache 161 ms); a second measurement earlier the same session was 19.0 s. Warm `/api/v1/jokes/` ≈ 4.6 s first hit. See F-009. |
| T5-02 | `/readyz` | **PASS** | 200 `{status: ready, db ok, cache ok}` |
| T5-02b | `/healthz` | **CONFIRMED-DEFECT** | 404 from the Google edge, never reaching Django — F-001 |
| T5-03 | Share page (bot UA) | **PASS** | 200 with per-joke `og:title`/`og:description`/`og:type`/`og:url` + 1 JSON-LD block |
| T5-03b | Share page (human UA) | **PASS** | Same 3,997-byte page, which additionally carries `<meta http-equiv="refresh" content="0; url=…/jokes/175">` **and** `location.replace(...)`. A client-side redirect by design — bots read tags, browsers bounce into the SPA. Initially looked like a missing 302; verified as correct. |
| T5-04 | Sitemap + robots | **PASS** | `/sitemap.xml` is valid XML with ~170 joke URLs, 3 creators, 4 packs; `robots.txt` disallows every gated surface (`/create`, `/settings`, `/flow*`, `/explore`, `/library`, `/onboarding`, auth routes). They agree. |
| T5-05 | API docs | **PASS** | `/api/schema/`, `/api/docs/` serve 200 (but see T0-05 for the 22 omitted views) |
| T5-06 | Security headers | **PASS** | `strict-transport-security: max-age=31536000; includeSubDomains; preload`, `x-content-type-options: nosniff`, `x-frame-options: DENY`, `referrer-policy: same-origin`, `cross-origin-opener-policy: same-origin` |
| T5-07 | CORS preflight | **PASS (with consequence)** | `OPTIONS` from `https://jokesforfront.web.app` → 200, `allow-credentials: true`, `max-age: 86400`. Note this means the **sendBeacon preflight succeeds in prod too**, so the telemetry POST proceeds and is then rejected 403 — F-006 applies to production, not just local. |
