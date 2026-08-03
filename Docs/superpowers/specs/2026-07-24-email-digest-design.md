# Email Digest / Re-engagement — Design — 2026-07-24

Feature 3 of the MVP slate (after appeals, share cards). Owner-approved
feature + trigger pattern (Cloud Scheduler → HTTP).

## Goal

Bring readers back and reward creators — two email types on the existing
Resend/`send_email` engine, triggered daily by a GCP-managed scheduler
calling one authenticated endpoint (no cron/worker in the app).

## Two emails (v1)

1. **Daily digest** (reader retention): "Today's joke is ready" — the
   day's editorial daily joke (setup + a reveal link back into the app),
   sent to users who opted in and haven't disabled it. One per user per day,
   idempotent.
2. **Creator milestone** (creator retention): "Your joke made people laugh"
   — fired when a creator's joke crosses a reaction threshold since the last
   digest run (e.g. +10 new laughs). Batched into the same daily run, one
   summary email per creator per day covering all their jokes' new
   engagement.

## Trigger (owner-approved pattern)

- New endpoint `POST /api/v1/internal/run-digests/` — authed by a shared
  secret header (`X-Digest-Token` == `DIGEST_CRON_TOKEN` env, constant-time
  compare); NOT a user endpoint, throttle-exempt, returns a summary
  `{digests_sent, milestones_sent, skipped}`.
- Cloud Scheduler job (created at deploy, owner-visible gcloud command in
  deploy notes) hits it daily at a configured UTC hour with the token
  header. The scheduler is GCP config — no in-app cron, honoring the
  single-app rule.
- **Idempotency:** a `DigestRun` row per (date) with a per-user/per-type
  send ledger (reuse `EmailMessageLog` — query "did we send template=X to
  user on date=today"); a second same-day call sends nothing. So a scheduler
  double-fire or a manual re-run is safe.
- **Batching for scale within the request budget:** the endpoint processes
  in bounded chunks and is safe to call repeatedly — if the eligible set is
  large, it sends what it can per invocation (capped, e.g. 500/run) and
  reports `remaining`; Scheduler can be set to retry, or the cap raised.
  For MVP volume one call drains it. (No worker — bounded synchronous work,
  same principle as the media pipeline.)

## Preferences & compliance

- `UserProfile` (or preferences) gains `email_digest_opt_in` (default per
  a product call — recommend **opt-in true for daily digest** at signup
  with a clear unsubscribe, opt-in true for creator milestones) — CAN-SPAM
  requires one-click unsubscribe: every digest email has an unsubscribe link
  → `GET /api/v1/email/unsubscribe/?token=<signed>` (signed per-user, no
  login needed) that flips the flag. Transactional emails (verification,
  moderation notices) are exempt and unaffected.
- Respect existing verification/active state — only verified active users
  get digests.

## Data / templates

- Templates registered in the notifications template registry:
  `daily_digest`, `creator_milestone` (subject + html + text each).
- `DigestRun` model (date, started_at, finished_at, counts) for
  observability + idempotency anchor.
- Milestone threshold + digest-hour + per-run cap are settings/env
  (tunable without redeploy where reasonable).

## Out of scope (v1)

Weekly/streak digests; per-user send-time optimization; rich
recommendation digests (just the editorial daily joke); real-time
milestone emails (batched daily only); A/B subject testing.

## Risks

- Secret-header auth on an internal endpoint: constant-time compare, env
  secret, not logged, 404 (not 401) on bad token to avoid advertising the
  endpoint. Documented.
- Send volume vs request budget: bounded cap + idempotent re-runs; MVP
  volume is small. The EmailMessageLog ledger prevents double-sends across
  retries.
- Unsubscribe token must be unguessable + not leak identity in URL: Django
  signing over user id, no PII in the querystring.
