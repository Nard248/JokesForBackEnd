# Appeals & Notices Wave — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the spec at `Docs/superpowers/specs/2026-07-23-appeals-notices-design.md` — Appeal model + notices + quarantine reversibility + admin SLA queue + minimal FE.

**Architecture:** One new model in the jokes app; quarantine as MediaAsset methods over the existing storage layer (copy-then-delete, no signing); takedown reworked keep-links+quarantine; lazy expiry piggybacked on existing sweeps; DRF endpoints + admin actions; small FE additions with graceful absence.

**Tech Stack:** unchanged (Django/DRF; React/vitest).

## Global Constraints

- Backend tests: Django runner NEVER pytest, `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test <target> --keepdb`; new tests in `jokes/tests_appeals.py`; reuse tests_media helpers (make_user/make_asset/make_image_joke, `_generate_share_image` patch pattern, temp MEDIA_ROOT).
- FE: `npm test -- --run` + `npm run build` green; inline styles; graceful-absent contract.
- Commits plain, no footers/emoji. Spec values verbatim: 14-day window, 36h red / 48h SLA, throttle `appeals: 10/day`, quarantine path `quarantine/<asset-uuid>/<name>`.
- MUST NOT regress: wave-1/2 media suites (`jokes.tests_media`, `jokes.tests_media_wave2`) — the takedown rework REPLACES detach-then-reap; those takedown tests will legitimately change (document each: links now kept, unshared assets quarantined not deleted, files exist at quarantine paths).
- The existing single-file-deletion helper stays the ONLY purge path.

---

### Task 1 (backend): Appeal model + notices
**Files:** jokes/models.py (Appeal + constraints), migration, inbox verb `joke_rejected` + `Notification.data` JSONField + `notify(..., **extra)` + serializer exposure (inbox/models, services, serializers — AMENDED scope 2026-07-24) + rejection-transition signal (jokes/signals.py — read how existing signals register), richer takedown notification payload (jokes/admin.py take_down_joke: most-common report reason + deadline in notify kwargs — READ inbox.services.notify signature first and extend payload the way existing verbs do).
**Produces:** `Appeal` exactly per spec §Model; `notify(user, 'joke_rejected', ...)` on transition; takedown notice carries `{reason, appeal_deadline}`.
**Tests (TDD):** model constraints (one-of-target check, single open appeal); rejection transition fires notice once (not on other transitions); takedown notice payload.
Commit: `appeals: Appeal model, rejection notices, reasoned takedown notices`.

### Task 2 (backend): Quarantine + takedown rework
**Files:** jokes/models.py (MediaAsset.quarantined_at + quarantine()/release() — copy-then-delete via default_storage per file field, path per spec; purge() delegates to delete_with_files), migration, jokes/admin.py take_down_joke (KEEP JokeMedia links; quarantine unshared assets; shared-with-live-joke assets untouched; audit `media_quarantined`), lazy expiry: extend the existing upload orphan sweep with purge of assets `quarantined_at < now-14d` with no OPEN appeal on their joke (+ same check invoked from the appeal-create endpoint later — expose a module function).
**Tests (TDD):** quarantine moves files (old path gone, new exists, FieldFile name updated); release restores; takedown keeps links + quarantines unshared + spares shared (REWORK the wave-2 shared-asset test to the new semantics, documented); expiry sweep purges only lapsed-no-open-appeal.
Commit: `appeals: media quarantine with reversible takedown and lazy expiry`.

### Task 3 (backend): API + resolution actions
**Files:** jokes/serializers.py (AppealSerializer read + create validation per spec §API), jokes/views.py (AppealCreateView POST /appeals/ with window/ownership/open-appeal checks + throttle scope + audit `appeal_filed` + invoke expiry check; MyAppealsView GET), jokes/urls.py, settings throttle rate, jokes/admin.py AppealAdmin (queue per spec §Admin: hours_open red ≥36h via format_html, overdue filter, uphold action → purge quarantined media of the target + audit `appeal_upheld` + notify outcome; reverse action → release + is_removed=False for takedowns / submission back to draft for rejections + audit `appeal_reversed` + notify).
**Tests (TDD):** endpoint happy paths + every rejection (not-owner 404/400, window lapsed, duplicate open, wrong-state target); uphold purges; reverse restores joke incl. media serving again (serialize after reverse → urls present); rejection-reverse → draft; notify calls.
Commit: `appeals: file/list endpoints and admin resolution queue with SLA clock`.

### Task 4 (frontend): Appeal UI
**Files (FE repo, branch feat/appeals):** appeal API + react-query mutation/query (follow features/* seams); Appeal CTA + modal (reason textarea) on the rejected SubmissionDetailPage state and on removal/rejection inbox notices (READ how the inbox renders verbs; extend minimally); CreatorHubPage appeals status strip (chips, hidden when list empty or endpoint absent — graceful).
**Tests (TDD, vitest):** modal posts and confirms; strip renders/hides; notice CTA present for the new verb.
Commit: `appeals: creator appeal flow and status strip`.

### Task 5: Regression + wrap
Backend full suite; FE full suite + build. Fix regressions per the established rule (takedown-semantics test updates are expected and documented).

---

## Deployment notes
Backend first is fine here (FE degrades gracefully; new endpoints additive) — either order works; ship backend → FE. No infra changes.
