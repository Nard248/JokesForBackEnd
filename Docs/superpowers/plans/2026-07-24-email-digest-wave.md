# Email Digest Wave — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox steps.

**Goal:** Ship `Docs/superpowers/specs/2026-07-24-email-digest-design.md` — daily digest + creator-milestone emails, a token-authed internal trigger endpoint, idempotent sends, CAN-SPAM unsubscribe.

**Architecture:** Reuse `notifications.send_email`; a `POST /internal/run-digests/` endpoint authed by a shared secret does bounded, idempotent per-day sends; Cloud Scheduler (GCP config) calls it daily.

**Tech Stack:** Django/DRF, existing Resend engine, Django signing (unsubscribe).

## Global Constraints
- Django runner NEVER pytest; new tests `notifications/tests/test_digests.py`; email backend is locmem in tests (assert on mail.outbox + EmailMessageLog).
- Commits plain no footers. Spec values verbatim: fixed digest hour env, per-run cap (500), milestone threshold env, constant-time token compare, 404 on bad token.
- No cron in-app; the endpoint is the seam, Scheduler is external config.
- Idempotency is load-bearing: a same-day re-run sends NOTHING new (test it).

---

### Task 1: preferences + signed unsubscribe
**Files:** UserProfile (or preferences model) + `email_digest_opt_in` (default True) + `creator_milestone_opt_in` (default True) + migration; `GET /api/v1/email/unsubscribe/?token=` (AllowAny, signed token over user-id+type via django.core.signing, flips the flag, renders a tiny confirmation — no login); url.
**Tests:** valid token flips flag + idempotent; tampered/expired token → clean error not 500; the flag defaults correct.
Commit: `digest: email preferences and signed one-click unsubscribe`.

### Task 2: digest engine + templates
**Files:** `notifications/digests.py` — `run_daily_digests(cap=500) -> {digests_sent, milestones_sent, skipped, remaining}`: selects verified+active+opted-in users without a today `daily_digest` EmailMessageLog, sends the editorial daily joke via send_email('daily_digest', ...) with an unsubscribe link in context, bounded by cap; creator-milestone: creators whose jokes gained >= threshold new reactions since their last `creator_milestone` send, one summary each, idempotent per-day. Register `daily_digest` + `creator_milestone` templates (subject/html/text) in the template registry; `DigestRun` model (date unique, counts).
**Tests:** digest sends to eligible only (opted-out/unverified/inactive skipped); idempotent (second run same day sends 0); cap respected + remaining reported; milestone threshold boundary; unsubscribe link present + valid in the email body.
Commit: `digest: daily digest + creator milestone engine with idempotent per-day sends`.

### Task 3: token-authed trigger endpoint
**Files:** `POST /api/v1/internal/run-digests/` — no user auth; reads `X-Digest-Token`, constant-time compares to `settings.DIGEST_CRON_TOKEN` (env); MISMATCH/missing → 404 (not 401, don't advertise); on match calls run_daily_digests, returns the summary; throttle-exempt but the 404-on-bad-token + unguessable token is the guard; audit `digest_run`. Setting DIGEST_CRON_TOKEN (env, unset → endpoint 404s for everyone = safely dormant).
**Tests:** no/bad token → 404; correct token → 200 + summary + sends; dormant (unset token) → 404; constant-time compare used (assert via hmac.compare_digest usage, not ==).
Commit: `digest: token-authed internal run-digests trigger endpoint`.

### Task 4: regression + wrap
Full backend suite green.

---

## Deployment notes (owner-visible)
- Backend-only wave. Set `DIGEST_CRON_TOKEN` (Cloud Run env, a long random secret) — until set, the endpoint 404s and no digests send (safe).
- Create the Cloud Scheduler job (owner action, gcloud):
  `gcloud scheduler jobs create http jokesfor-daily-digest --schedule="0 15 * * *" --uri="https://<service>/api/v1/internal/run-digests/" --http-method=POST --headers="X-Digest-Token=<token>" --location=us-east1 --project=jokesfor`
  (15:00 UTC ≈ mid-morning US; tune). This is the ONLY new infra — GCP-managed, no worker.
- Opt-in defaults ship True (daily digest + milestones) with unsubscribe — confirm this product call at plan-review; flip the migration default if opt-in-false preferred.
