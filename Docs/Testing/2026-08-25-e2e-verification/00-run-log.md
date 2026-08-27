# JokesFor — End-to-End Verification Run Log (2026-08-25)

This log records, in order, everything done during the 2026-08-25 verification pass
(codebase analysis → test-pipeline design → automated tiers → manual in-browser E2E → findings).
Companion files in this folder:

- `01-test-pipeline.md` — the designed pipeline (tiers, test IDs, expected behaviour, sanity check per test)
- `02-automated-results.md` — automated tier results (backend, frontend, lint/security, API contract)
- `03-manual-e2e-results.md` — in-browser E2E results with evidence references
- `04-findings.md` — consolidated findings register (F-###), severity, repro, proposed fix
- `evidence/` — screenshots, logs, raw outputs

## 0. Environment snapshot (12:23 +04)

| Layer | Value |
|---|---|
| Backend repo | `/Users/narekmeloyan/PycharmProjects/JokesForProject` @ `56e4945` (main, clean except untracked business docs) |
| Frontend repo | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend` @ `04e1b2f` (main) |
| Backend prod | `https://jokesforbackend-332865216810.us-east1.run.app` (Cloud Run, GCP project `jokesfor` / 332865216810) |
| Frontend prod | `https://jokesforfront.web.app` (Firebase Hosting, project `jokesforfront`) |
| Python | 3.11.0 in `.venv`; Django 5.2.17, DRF 3.16.1; **no pytest** — suite runs with `manage.py test` |
| Node | v22.16.0 / npm 11.7.0 (CI uses Node 24) |
| Local DB | Postgres @ localhost:5432 `jokesfor` (postgres/6969) — 304 jokes, 12+ legacy test users; **migrations behind code** (jokes 33/36, notifications 2/4, billing 3/4, inbox 1/4) |
| Cloud DB | Neon pooler `ep-round-brook-aq0p3j8j-pooler…` via `DATABASE_URL` in `.env` — must be overridden (`DATABASE_URL=''`) for local runs |
| Binaries | ffmpeg 8.1.2 ✅; cairo 1.18.4 via Homebrew ✅ but cairocffi needs `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` |
| Test inventory | Backend: 834 `def test_` across 52 files; Frontend: 795 cases across 109 vitest files; Playwright: only `e2e/example.spec.ts` |

### Prod smoke (first touch)

| URL | Status | Time |
|---|---|---|
| `GET /readyz` | 200 | 18.99 s (cold start) |
| `GET /api/v1/jokes/?page_size=1` | 200 | 4.64 s |
| `GET /api/schema/` | 200 | 2.35 s |
| `GET /sitemap.xml` | 200 | 1.06 s |
| `GET https://jokesforfront.web.app/` | 200 | 0.59 s |
| `GET /healthz` | **404** (Google-edge HTML, not Django) | 0.43 s |

## 1. Timeline

- 12:23 — Session start. Classified: Part 1 (verification) proceeds on explicit instruction; Part 2 (iOS) is architectural → design spec for review, no implementation.
- 12:30 — Scouted both repos, env files (values hidden), CI/deploy configs, prod health.
- 12:38 — Launched 14-analyzer codebase-mapping workflow (`wf_aa8ea6f8-5da`) — outputs in scratchpad `analysis/*.md`, to be copied into this folder as `analysis/`.
- 12:40 — Early findings logged (see below) while the workflow runs.

## 2. Early findings (pre-pipeline)

- **F-001 (P2, infra/observability)** — Prod `/healthz` is unreachable through the public `*.run.app` URL: exact path `/healthz` (with or without query string) returns a Google Frontend HTML 404 (`charset=UTF-8`, no Django security headers), whereas `/healthzz`, `/Healthz`, `/healthz/` return *Django* 404s and `/readyz` returns 200. Conclusion: the edge intercepts the reserved path before Cloud Run. Expected behaviour per `JokesForProject/health.py`: `200 {"status":"ok"}`. Impact: any external uptime check pointed at `/healthz` is dead; container-level probes (which bypass the edge) are unaffected. Proposed fix: expose an alias (e.g. `/livez`) and update docs/monitoring.
- **F-002 (P2, dev-experience)** — Share-card rendering (`cairosvg`) cannot import on macOS without `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`; CI installs `libcairo2` so it's green there. Worth a one-line note in the runbook.
- **F-003 (P2, dev-environment)** — Local dev DB has unapplied migrations (see table) and legacy `django_celery_*` tables from the removed Celery stack; `manage.py test` is unaffected (own test DB) but the local full-stack E2E requires `migrate` first.

## 3. Execution timeline (continued)

- 13:50 — Codebase map complete (16 reports, 5,076 lines) → archived to `./analysis/`. Critic resolved 16 cross-report contradictions and flagged 6 gaps.
- 13:52 — **T0/T1/T2 baseline**: ruff clean, `check` clean, no model drift, bandit 0 High; **FE 798/798 in 12.2 s**; **BE 834/834 in 111.1 s with zero skips**.
- 13:56 — Local stack prepared: applied the **9 pending migrations**, seeded achievements, created superuser `e2eadmin`.
- 13:58 — Stack up on **:8010 / :5273** (ports 8000/5173 left to the other project). `/healthz` returns 200 locally → **F-001 is a Cloud Run edge interception, not a code bug**.
- 14:00–14:20 — **T3 auth + paywall + contract** run. Auth 11/11. Paywall correct on every path. Contract defects F-004…F-007 confirmed.
- 14:24 — Claude-in-Chrome extension disconnected mid-tier; **switched to Playwright MCP** and continued.
- 14:26–14:40 — **T4 in-browser E2E**: registration → verify → onboarding → hub → search → detail → paywall → mobile. F-003 and F-006 found and proven in a real browser.
- 14:45 — Parallel agent returned the creator/moderation/billing/SEO API tier → `02b-api-contract-results.md`.
- 14:50 — **Independently re-verified the agent's P0** (share-page punchline leak) on local **and production**, and its GDPR-delete claim by controlled experiment.
- 15:00 — Findings register finalized (20 findings). iOS plan written.

## 4. Test-assumption corrections (recorded deliberately)

Three times a "failure" turned out to be my test being wrong, not the app. Recording them because each was one assertion away from a false report:

1. **Reveal endpoint shape** — I assumed `POST /jokes/{id}/reveal/` returns the punchline. It returns *counter state*; authenticated reads are ledgered via `GET /jokes/{id}/` (retrieve). Corrected the harness.
2. **`punchline` as a lock oracle** — one-liner/observational jokes legitimately have no punchline, so "punchline absent" conflated format with lock state. Switched to `is_locked`.
3. **Apparent search paywall bypass** — my probe's fallback picked an **already-consumed** joke. Re-tested properly: no bypass exists. This one would have been a false P0.

A fourth correction came from the parallel agent (duplicate-appeal message wording), and a fifth from prod: the share page's "missing redirect" is a deliberate client-side `meta refresh` + `location.replace`, not a defect.

**Also verified as data artifacts, not bugs:** duplicate "Dara Punwell" in Top Jokesters = two distinct seeded users sharing a display name.

## 5. State left behind

- Local DB: test users `e2e*`, `fr*`, `pd*`, `ios*`, `pref*`, `orc*`, `tel*` and superuser `e2eadmin` (password `E2eAdmin!2026`) remain; the 9 pending migrations are now **applied** (this was needed and should stay).
- No application source file was modified anywhere in either repo. All findings are reported, not fixed.
- Dev servers on :8010/:5273 were started by this pass and stopped at the end. Ports 8000/5173 were never touched.

---

## 6. Second pass — 2026-08-26: fresh-account walkthrough

Re-ran the pipeline end-to-end with a **brand-new account** (`pipeline…@test.local`, "Pipeline Tester" / `@pipetest26`, DOB 1992-03-08) registered through the UI, to confirm the findings reproduce for a first-time user and to cover surfaces the first pass delegated.

**Journey walked:** register (2 steps) → verify-email (code `916380` from the console backend) → onboarding (Dad jokes / Wholesome / Kids OK, 21:00, +Saturday) → Today hub → Explore → joke detail → save + react → read to the paywall → locked joke → creator editor → submit.

**Reproduced:** F-005 exactly (second independent account: `onboarding_completed=False`, `preferred_tones=[]`, `notification_time=None`, `notification_days=[]`; only `UserVibe` saved). F-003 with the mechanism now precisely characterized — the Continue button is the **last element on a scrolling page**, so `scrollIntoView` lands it at y852–900 under the banner's 833–900 band and `elementFromPoint` returns "Accept"; at page bottom it is still blocked. F-017 end-to-end through the editor.

**New findings:** **F-021 (P0)** — locked two-part jokes ship their punchline in the `text` field (121/314 = 39% of the catalogue); found by inspecting the payload rather than the pixels, since the UI renders correct `████` redaction. **F-020 (P2)** — the registration handle is stored on `auth_user.username` but the profile shows a synthesized `@user<id>`.

**Verified working:** registration + verification + auto-submit on 6th digit; save-to-library (1 saved); reactions (`my_reaction: "lol"`, count 3→4); the read ledger incrementing 1→10 with `over:true` at exactly 10; the paywall UI showing `████` redaction + "You've hit your free daily jokes" + "Unlock with Supporter"; the streak chip appearing ("🔥 1-day streak"); Explore rendering 10 cards with filter chips.

**Two more corrections recorded** (test wrong, not app): Explore's "0 jokes loaded" was my snapshot racing the query — 10 cards render fine; and the registration display name/handle *do* persist (to `auth_user`), they are just read from a different table.

**Observed, local data artifact:** the format picker lists both "Setup → Punchline" and "Setup-Punchline", and both "Story" and "Short Story" — duplicate taxonomy rows from the legacy `lookup_data` fixture coexisting with the migration-seeded taxonomy. Relevant because the `story`/`short-story` slug split is part of why F-021 leaks.
