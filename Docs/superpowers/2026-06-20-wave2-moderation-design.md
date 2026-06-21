# Wave 2 — Moderation (design)

**Date:** 2026-06-20 · **Status:** in progress · launch-gating (CD7, pre-UGC compliance)

## What already exists (Wave 1 "Phase 6")
- `ContentReport` model — reporter, `joke` FK, `reason` (offensive/inappropriate/spam/copyright/harassment/other), `description`, `status` (pending/reviewed/resolved/dismissed), `resolved_at`, `created_at`; indexed on (status, created_at).
- `UserBlock` model — (blocker, blocked) unique, created_at.
- Endpoints: `POST /reports/`, `POST|DELETE /users/<id>/block/` (both audit-logged via `audit.record_audit`).
- Basic `ContentReportAdmin` + `UserBlockAdmin` (display only — **no triage actions**).

## The gap (this iteration)
1. **Takedown** — no way to remove a reported joke. Published `Joke` has no moderation flag.
2. **Enforcement** — reports/blocks are recorded but applied to **zero** read paths. Removed jokes and blocked users' content still serve everywhere.
3. **Triage** — admin can't act on a report (dismiss / take down / resolve).
4. **Blocks management** — no `GET /users/me/blocks/`; blocking doesn't touch follow edges.
5. **Frontend** — no report UI, block button, blocked-users list, or hidden-content states.

## Decisions (owner-overridable defaults)
- **Takedown, not delete.** Add `Joke.is_removed` (bool, indexed) + `removed_at`. Removed jokes are excluded from all viewer read paths but kept for audit/appeal. Admin action toggles it.
- **No auto-hide threshold (default).** Reports go to an admin queue; nothing is hidden until a human acts. Avoids brigading/abuse. (Owner may later opt into "auto-hide at N distinct pending reports" — would be computed synchronously at report time, no worker.)
- **Symmetric block visibility.** If A blocks B, neither sees the other's jokes/profile (harassment protection). Enforcement excludes jokes whose creator ∈ (users I blocked) ∪ (users who blocked me).
- **Block drops follow edges** both directions and prevents (re-)following while blocked.
- **Report dedup** — one *pending* report per (reporter, joke); repeat returns the existing one (200) instead of stacking.
- Reasons/status taxonomies unchanged (already reasonable).

## Enforcement architecture (global vs per-viewer)
Consistent with the existing **per-path** content-tier lock (`allowed_tiers`), not a manager-wide `get_queryset` override (too broad/risky to retrofit).
- New `jokes/moderation.py`:
  - `visible_jokes(qs, request)` → `qs.filter(is_removed=False)` then, if authenticated, `.exclude(creator_id__in=hidden_user_ids(user))` (covers FK `creator`; submission-attributed jokes are covered because publish stamps `creator`).
  - `hidden_user_ids(user)` → set of user ids in either side of a block with `user`.
- Applied at the viewer-facing surfaces that already apply `allowed_tiers`: feed/search/serving paths in `views.py`, the creator-profile jokes (`creator_insights`), recommendations, and the follow/follower lists (filter out blocked users).
- `Joke.objects` (default manager) additionally excludes `is_removed=True` at the **read paths** (explicit), while admin/moderation use unfiltered queries.

## Phases
- **A. Backend enforcement + takedown** — `Joke.is_removed`/`removed_at` (+migration); `jokes/moderation.py`; apply `visible_jokes` at read paths; block-filter follow lists; `GET /users/me/blocks/`; block↔follow side-effects; report dedup. TDD.
- **B. Admin triage** — `ContentReportAdmin` actions: *take down joke* (sets `is_removed`, resolves the joke's pending reports, audit), *dismiss*, *mark resolved*; status workflow; show report counts. TDD.
- **C. Frontend** — report modal on `JokeCard` (reason picker → `POST /reports/`), block/unblock button on creator profile, blocked-users list in Settings, hidden-content empty states. Mock + real adapter paths. vitest.
