# Appeals & Moderation Notices — Design — 2026-07-23

Owner-approved 2026-07-23 (design incl. the quarantine recommendation).

## Goal

Close the DSA gap: statements of reasons on every moderation action, a
creator appeal channel with a human-review SLA, and reversibility that
isn't hollow for media jokes.

## Model

`Appeal` (jokes app): `user FK · joke FK null · submission FK null ·
action_type ∈ {takedown, rejection} · reason_text · status ∈ {pending,
upheld, reversed} · created_at · resolved_at · resolver FK null ·
resolution_note`. Exactly one of joke/submission set (DB check constraint);
at most ONE open (pending) appeal per target (partial unique index).
Appeals accepted within **14 days** of the action (takedown → `removed_at`;
rejection → submission `updated_at` at rejection).

## Notices (statement of reasons)

- Takedown: the existing `joke_removed` notification gains a reason (most
  common `reason` among the triggering reports, fallback 'other') and the
  appeal deadline. Carried via the notification payload the inbox already
  renders.
- Rejection: new inbox verb `joke_rejected`, fired automatically when a
  submission transitions to `rejected` (signal on status change — the
  admin's existing manual workflow is untouched), carrying
  `rejection_reason`.

## Quarantine (the reversibility mechanism)

Takedown no longer hard-deletes media. Instead:
- `MediaAsset.quarantined_at` (null datetime). `quarantine()` moves each
  stored file to `quarantine/<asset-uuid>/<name>` (copy-then-delete through
  the default storage — no signing needed; unguessable path, out of every
  serving surface), stamps `quarantined_at`. `release()` moves back and
  clears the stamp. `purge()` = existing `delete_with_files()`.
- `take_down_joke` reworked: JokeMedia links are KEPT (restore needs them);
  assets not shared with a live joke are `quarantine()`d (shared assets
  stay untouched, as today).
- Hard deletion happens at: appeal **upheld**; appeal window (14d) lapsed
  with no open appeal (LAZY sweep — piggybacked on the existing
  request-triggered orphan sweep and on appeal-endpoint hits); or account
  deletion (erasure wins — unchanged, no appeal on self-deletion).
- Reversal: `release()` all quarantined assets of the joke, then
  `is_removed=False` (existing restore semantics), notify the creator.
- Rejection appeals involve no quarantine (rejected submissions keep their
  media for editing — unchanged behavior).

## API

- `POST /api/v1/appeals/` `{joke_id | submission_id, reason_text}` —
  IsAuthenticated; target must be the caller's own removed joke / rejected
  submission; inside the window; no open appeal exists. 201 → appeal state.
- `GET /api/v1/users/me/appeals/` — caller's appeals with status.
- Throttle scope `appeals: 10/day` (abuse guard).

## Admin

`AppealAdmin`: default pending-first queue; columns: target preview,
action_type, hours_open (red ≥36h — the 48h SLA visible at a glance),
status; list filter incl. "overdue (>36h)"; actions `uphold_appeals`
(purge quarantined media, notify `appeal_denied`… naming: verb
`appeal_resolved` with outcome payload) and `reverse_appeals` (restore per
above, notify). Both stamp resolver/resolved_at/resolution_note (note via
the change form, actions work without it).

## Frontend

- Inbox: render the richer removal/rejection notices (reason + deadline);
  Appeal CTA on those notices and on the rejected SubmissionDetailPage
  state → minimal appeal modal (reason textarea → POST).
- CreatorHubPage: small "Appeals" status strip (pending/resolved chips)
  fed by `GET /users/me/appeals/`; hidden when empty.
- Graceful degradation: all new UI keys optional; absent API → hidden.

## Audit

`appeal_filed`, `appeal_upheld`, `appeal_reversed`, `media_quarantined`,
`media_purged` via the existing `record_audit`.

## Out of scope

SLA breach auto-alerting (post-MVP, can ride the digest scheduler); appeals
of blocks; counter-notice flows; appeal-outcome emails (inbox only for MVP).
