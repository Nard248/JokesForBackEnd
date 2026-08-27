# Backend Trust & Safety / Compliance — Deep Dive (`be-compliance-moderation`)

Repo: `/Users/narekmeloyan/PycharmProjects/JokesForProject` (Django 5.2 / DRF / Postgres / Cloud Run).
All facts below are from code unless explicitly labelled "spec"/"plan". Line numbers are as of 2026-08-25 (HEAD `56e4945`).

---

## 0. Map of the T&S surface

| Concern | Primary code | Endpoints | Admin |
|---|---|---|---|
| Report content | `jokes/models.py:736` `ContentReport`; `jokes/views.py:2275` `ContentReportView` | `POST /api/v1/reports/` | `ContentReportAdmin` (`jokes/admin.py:398`) |
| Block user | `jokes/models.py:783` `UserBlock`; `jokes/moderation.py`; `jokes/views.py:2355,2384` | `POST/DELETE /api/v1/users/<id>/block/`, `GET /api/v1/users/me/blocks/` | `UserBlockAdmin` |
| Takedown (reversible) | `ContentReportAdmin.take_down_joke` (`jokes/admin.py:420-538`); `Joke.is_removed/removed_at`; `JokeManager` (`jokes/managers.py`); `MediaAsset.quarantine/release/purge` (`jokes/models.py:1473-1517`) | none (admin-only) | `ContentReportAdmin`, `JokeAdmin.restore_jokes` |
| Submission review / rejection | `JokeSubmissionAdmin.approve_and_publish` (`jokes/admin.py:321`); rejection = change-form status edit + signal `jokes/signals.py:141-175` | `POST /jokes/my-drafts/<id>/submit/` | `JokeSubmissionAdmin` |
| Automated screening | `jokes/media_screening.py` (Vision SafeSearch + NullMatcher CSAM seam); `MediaUploadView` (`jokes/views.py:1480`) | `POST /api/v1/media/uploads/` | `safesearch_flags` column in `JokeSubmissionAdmin` |
| DSA appeals | `Appeal` (`jokes/models.py:1562`); `AppealCreateSerializer` (`jokes/serializers.py:1040`); `AppealCreateView`/`MyAppealsView` (`jokes/views.py:2308,2343`); `jokes/quarantine.py` lazy sweep | `POST /api/v1/appeals/`, `GET /api/v1/users/me/appeals/` | `AppealAdmin` (`jokes/admin.py:578-772`) |
| Moderation notices (in-app) | `inbox/` app: `Notification` w/ `data` JSON; `inbox/services.notify` | `GET /api/v1/notifications/`, `.../unread-count/`, `POST .../mark-read/` | `NotificationAdmin` |
| Content tiers / age gate | `jokes/serving.py:allowed_tiers`; `UserProfile.date_of_birth/is_adult/is_minor` (`jokes/models.py:535-590`); `UserPreference.show_mature` (`jokes/models.py:331`) | applied on every read path | `JokeAdmin` exposes `content_tier` |
| COPPA registration gate | `JokesForProject/serializers.py:EmailOnlyRegisterSerializer`; `JokesForProject/adapters.py:SocialAccountAdapter`; `GoogleLogin` (`jokes/views.py:893`) | `POST /api/v1/auth/registration/`, `POST /api/v1/auth/google/` | — |
| GDPR export / delete | `DataExportView` (`jokes/views.py:2499`), `UserAccountDeleteView` (`jokes/views.py:2399`) | `GET /api/v1/users/me/data-export/`, `DELETE /api/v1/users/me/` | — |
| Audit log | `audit/` app (`models.py`, `services.py`, `signals.py`) | — | `AuditLogAdmin` (read-only) |
| Email engine / verification | `notifications/service.py`, `verification.py`, `templates_registry.py`, `throttles.py` | `POST /api/v1/auth/verify-email/`, `POST /api/v1/auth/resend-verification/` | `EmailMessageLogAdmin`, `EmailVerificationAdmin` (read-only) |
| Digest engine + trigger | `notifications/digests.py`; `RunDigestsView` (`notifications/views.py:238-280`) | `POST /api/v1/internal/run-digests/` (schema-excluded) | `DigestRunAdmin` (read-only) |
| CAN-SPAM unsubscribe | `notifications/unsubscribe.py`; `EmailUnsubscribeView` (`notifications/views.py:169-235`) | `GET/POST /api/v1/email/unsubscribe/?token=` | — |

---

## 1. Content moderation

### 1.1 Reporting (`POST /api/v1/reports/`)
- Model `ContentReport` (`jokes/models.py:736-777`): `reporter` FK CASCADE, `joke` FK CASCADE, `reason ∈ {offensive, inappropriate, spam, copyright, harassment, other}`, `description`, `status ∈ {pending, reviewed, resolved, dismissed}` (default pending), `resolved_at`, `created_at`. Index on `(status, created_at)`.
- `ContentReportSerializer` (`jokes/serializers.py:994`) exposes `joke, reason, description`. Because `joke` is a ModelSerializer PK field it uses `Joke._default_manager` = `JokeManager` (filters `is_removed=False`) → **reporting an already-removed joke is a 400** (joke not found in queryset).
- `ContentReportView.create` (`jokes/views.py:2275-2306`): `IsAuthenticated`; dedup — one pending report per `(reporter, joke)`; a repeat returns the existing row with **200** instead of 201. `perform_create` audits `content_report` with `metadata={'reason': ...}`, `target_type='joke'`.
- No per-view throttle (falls under the global `user: 1000/hour`).
- Anonymous users cannot report.

### 1.2 Blocking
- `UserBlock` (`jokes/models.py:783-802`): `blocker`/`blocked` CASCADE, `unique_together`.
- `UserBlockView.post` (`jokes/views.py:2355-2375`): 404 for unknown user, 400 for self-block, `get_or_create` (idempotent) then **severs Follow rows in both directions**, audits `block`. Returns 201 `{status: 'blocked'}` even if it already existed.
- `delete`: idempotent, audits `unblock`, 204.
- `MyBlocksView` lists blocked users via `follows.serializers.PublicUserSerializer`.
- Enforcement (`jokes/moderation.py`): `is_blocked_between` (symmetric), `hidden_user_ids(user)` (both directions, empty for anon), `visible_jokes(qs, request)` = `is_removed=False` + exclude `creator_id__in=hidden`. Applied per read path, NOT globally: `JokeViewSet.get_queryset` (`views.py:166`), search/list path via `hidden_user_ids` (`views.py:337, 372`), reveal (`views.py:663`), recommendations (`jokes/recommendations.py:52`), mystery-box pool (`views.py:2759`), follower/following lists (`follows/views.py:69,91`), creator profile (`creator_insights/views.py:61-65` → 404), follow service (`follows/services.py:11-13` → ValidationError).
- Verified by `jokes/tests_moderation.py` (symmetry, feed hide, profile 404, follow raise, block severs follows, recommendations/mystery-box exclusion).
- Not applied: the block does not hide the blocked user's *reactions/tips/notifications*; `Notification.actor` from a now-blocked user is still shown in inbox. Blocks cannot be appealed (spec explicitly out of scope).

### 1.3 Takedown (admin action `ContentReportAdmin.take_down_joke`, `jokes/admin.py:420-538`)
Sequence, per selected report rows:
1. Collect `joke_ids`; group `reason` values per joke.
2. Snapshot `to_remove = Joke.all_objects.filter(pk__in, is_removed=False)`; `update(is_removed=True, removed_at=now)`.
3. Share-card leak closure: delete `share_image` file per joke (per-item try/except; only clear the DB field for successful deletes; admin WARNING lists failures).
4. Statement of reasons: `notify(creator, 'joke_removed', joke=jk, reason=<most common report reason or 'other'>, appeal_deadline=(now+14d).isoformat())`.
5. Resolve every non-resolved/dismissed report on those jokes (`status='resolved', resolved_at=now`).
6. Media: JokeMedia links are KEPT; each linked `MediaAsset` not `still_shared` with a live joke outside the takedown set is `quarantine()`d (per-asset try/except with WARNING). Audit `media_quarantined` once per batch (`target_type='joke'`, comma-joined ids).
7. Audit `content_takedown` per joke id (`actor=request.user`).

Global enforcement of removal: `JokeManager.get_queryset()` filters `is_removed=False` (`jokes/managers.py:14`); `Joke.all_objects` is the unfiltered manager used by admin/appeals/deletion. FK traversals bypass the manager, so serializers add explicit guards: `JokeSerializer.get_share_image_url/get_media` return `None`/`[]` for removed jokes (`serializers.py:245, 278`), `JokeListSerializer` likewise (`:383,397`), `JokePackDetailSerializer` filters `joke__is_removed=False` (`:1364`), saved/favorites/collections/recently-viewed/daily-history exclude removed (tests in `tests_appeals.py:537-600, 1382-1435`). `Joke.save()` refuses to (re)generate a share card when `is_removed` and blanks the card on a live→removed transition made via the admin change form (`models.py:191-243`).

Other take-down paths:
- `JokeAdmin` change form: staff can tick `is_removed` directly. `removed_at` is **readonly** and stays NULL → no notice, no quarantine, no report resolution, and the joke is **not appealable** (`AppealCreateSerializer` returns 400 "not eligible" when `removed_at is None`, `serializers.py:1085-1095`). Only the share card is blanked (model `save()`).
- `JokeAdmin.restore_jokes` (`admin.py:116-165`): releases quarantined assets first, `update(is_removed=False, removed_at=None)`, regenerates share cards; no notification, no audit row.
- Account deletion takes down media-format jokes (§4.2).

### 1.4 Submission review / auto-reject
- Workflow `JokeSubmission.status ∈ {draft, pending, published, rejected}`; `rejection_reason` text.
- `JokeDraftSubmitView` (`views.py:1774`) enforces `validate_per_format` (`jokes/submission_rules.py`) and moves draft/rejected → pending. There is **no automated text moderation / profanity filter / auto-reject** for text; the only automatic reject is media SafeSearch at upload (§1.5).
- `approve_and_publish` (`admin.py:321-382`): only `pending` rows; creates `Joke` with `creator=submission.user`, **`content_tier = 'tier_2' if age_rating.min_age >= 18 else 'tier_1'`** (COPPA derivation — the only place `content_tier` is set for UGC), copies M2M + media links, regenerates share card, sets `published_joke`, `status='published'`, `notify(user, 'joke_published', joke=joke)`. Per-item `transaction.atomic()` with WARNING on failure. No audit row for approval.
- Rejection: there is **no admin action**; a moderator edits `status` to `rejected` + `rejection_reason` in the change form. Signals `stash_submission_status` (pre_save re-query) + `notify_submission_rejected` (post_save) fire `notify(user, 'joke_rejected', submission_id, rejection_reason)` exactly once per transition (`signals.py:141-175`; tests `tests_appeals.py:187-209`). Bulk `queryset.update()` bypasses the signal. Rejected submissions keep media (no quarantine) and can be edited (`JokeDraftDetailView` allows PATCH when draft/rejected) and resubmitted.
- `JokeSubmissionAdmin` shows `media_preview` (image/poster/audio link — note: renders live asset URLs to staff) and `safesearch_flags` (POSSIBLE+ levels, including per-frame video verdicts).

### 1.5 Automated media screening (`jokes/media_screening.py`, `MediaUploadView`)
- `screen_image` returns `{'status': 'skipped'}` when `SAFESEARCH_ENABLED` is false; on Vision exception or response error returns `{'status':'error', ...}` (**fail-open**: upload proceeds, human review remains the gate). Block policy: `adult` or `violence` at `LIKELY`/`VERY_LIKELY`; `racy/medical/spoof` recorded only.
- Images: blocked → audit `safesearch_block` (outcome `blocked`) + **422** `{'file': ['This image was rejected by automated content screening.']}`, no asset stored. Videos/GIFs: poster + sampled frames each screened; any block → 422. Audio: `{'status':'not_applicable'}`.
- CSAM hash matcher: `get_matcher()` returns `NullMatcher` (always None) — **dormant**; wiring exists (audit `hash_match_hit`, 422 "cannot be uploaded"). Owner-side vendor onboarding required.
- Verdict persisted on `MediaAsset.safesearch` JSON; `phash` stored for future matching.
- Upload path also runs `_sweep_orphan_assets` (owner's unattached assets >24h) and `purge_lapsed_quarantine()` and audits `media_upload`.

---

## 2. DSA appeals (spec `Docs/superpowers/specs/2026-07-23-appeals-notices-design.md`)

### 2.1 Model (`jokes/models.py:1562-1623`) — matches spec
`user`, `joke` (null), `submission` (null), `action_type ∈ {takedown, rejection}`, `reason_text`, `status ∈ {pending, upheld, reversed}`, `created_at`, `resolved_at`, `resolver` (SET_NULL), `resolution_note`. Constraints: `appeal_exactly_one_target` CheckConstraint; partial unique `(user, joke)` and `(user, submission)` where `status='pending'`. Note: spec says "at most ONE open appeal per target"; code scopes uniqueness per *(user, target)* — equivalent in practice since only the owner can file.

### 2.2 Filing (`POST /api/v1/appeals/`)
`AppealCreateSerializer.validate` (`serializers.py:1040-1160`), in order:
1. Exactly one of `joke_id`/`submission_id` → else 400.
2. Target lookup via `Joke.all_objects` / `JokeSubmission.objects`; missing OR not owned → **404** (indistinguishable, anti-probe).
3. Joke not removed → 400; `removed_at is None` → 400 "not eligible"; `now > removed_at + 14d` → 400; pending appeal exists → 400 (`DUPLICATE_JOKE_APPEAL_MSG`).
4. Submission not `rejected` → 400; `now > updated_at + 14d` → 400 (window anchored on `updated_at`, which any edit of the rejected submission would move — see risks); duplicate pending → 400.
`create()` wraps insert in `atomic()` and converts `IntegrityError` (race on the partial unique index) into the same 400.
`AppealCreateView` (`views.py:2308-2341`): `IsAuthenticated`, `ScopedRateThrottle` scope `appeals: 10/day` (settings), audits `appeal_filed` (`target_type=action_type`), then runs `purge_lapsed_quarantine()` (spec's lazy sweep trigger), returns 201 with `AppealSerializer` (`id, action_type, status, reason_text, target_type, target_id, target_preview, created_at, resolved_at, resolution_note`).
`MyAppealsView`: caller-only list, paginated (global `PAGE_SIZE=10`).

### 2.3 Quarantine mechanism (`MediaAsset`, `models.py:1438-1517`)
- `quarantine()`: idempotent; stamps `quarantined_at`; `_move_stored_files` copies `file` and `poster` to `quarantine/<uuid>/<secrets.token_urlsafe(16)>/<basename>` via `default_storage` (copy-all → single save → delete-old; crash-safe). Random segment prevents prefix-substitution guessing (spec amendment R1; test `test_quarantine_path_is_not_derivable_from_public_path`).
- `release()`: moves back to `media-assets/<uuid>/<basename>`, clears stamp. `purge()` = `delete_with_files()`.
- Leak guards on quarantined assets: `JokeSubmissionListSerializer.get_media` emits dims-only/no URL for quarantined assets (`serializers.py:815-833`); `DataExportView` emits `url: None, status: 'quarantined'` (`views.py:2603-2616`).
- Lazy expiry `purge_lapsed_quarantine()` (`jokes/quarantine.py`): assets with `quarantined_at < now-14d`, skipping those linked to a joke with a pending appeal, and **skipping any asset still linked to a live joke** (live-joke guard beyond spec). Audits one `media_purged` row per batch (`actor=None`). Triggered from upload finalize and appeal create only — if neither endpoint is hit, nothing is purged (accepted per no-cron rule).

### 2.4 Resolution (`AppealAdmin`, `admin.py:578-772`)
- Queue: annotated pending-first, oldest-first within pending; columns `target_preview, action_type, hours_open (red bold when pending ≥36h), status, created_at`; filters `status, action_type, OverdueAppealFilter (>36h pending)`; search `user__email, reason_text`.
- `uphold_appeals`: pending only; for takedown targets purges quarantined assets unless `still_shared` with a live joke or a sibling joke sharing the asset has its own pending appeal; stamps `status='upheld', resolver, resolved_at`; audits `appeal_upheld`; `notify(user, 'appeal_resolved', joke, outcome='upheld', action_type, submission_id)`. Per-appeal try/except with WARNING.
- `reverse_appeals`: takedown → `release()` all quarantined assets, `Joke.all_objects.update(is_removed=False, removed_at=None)`, regenerate share card (isolated), notify `appeal_resolved outcome='reversed'`; rejection → `submission.status='draft'`, `rejection_reason='Appeal reversed on <date> — you can edit and resubmit.'`, notify. Stamps status/resolver/resolved_at, audits `appeal_reversed`.
- `resolution_note` is only settable via the change form (spec-consistent). Note: reversing a takedown does **not** re-open/dismiss the original ContentReports (they stay `resolved`).
- Rejection reversal returns the submission to `draft`, not `published` — spec ("restore joke / draft submission") matches.

### 2.5 Spec vs code deltas
- Spec: "appeal-outcome emails out of scope" → code: inbox only. ✔
- Spec: notice `reason` = most common report reason → ✔ (`Counter.most_common`).
- Spec: `Notification.data` JSONField → ✔ with `DjangoJSONEncoder` (migration `inbox/0004`).
- Spec: audit `appeal_filed/appeal_upheld/appeal_reversed/media_quarantined/media_purged` → all present. ✔
- Spec does not cover: JokeAdmin direct `is_removed` flip (not appealable, no notice) — documented gap in code comments.
- Spec "rejection → submission updated_at at rejection" → code uses live `updated_at`; any later PATCH by the owner (allowed while rejected) resets the window. Minor deviation (lenient toward the user).
- SLA breach auto-alerting: none (spec: post-MVP). Only the red `hours_open` and the overdue filter exist.

---

## 3. Content tiers, mature gating, age gate & COPPA

### 3.1 Tiers
`Joke.content_tier ∈ {tier_1 universal, tier_2 mature, tier_3 prohibited}` default `tier_1`, indexed (`models.py:133-145`). `allowed_tiers(request)` (`jokes/serving.py`): anon → `{tier_1}`; missing profile/preference → `{tier_1}`; `profile.is_adult` False (age unknown or <18) → `{tier_1}`; adult with `preference.show_mature` → `{tier_1, tier_2}`; else `{tier_1}` + metric `age_gate_block`. **tier_3 is never served to anyone** (only reachable via `Joke.all_objects`/admin). Every call emits a `jokesfor.metrics` `content_tier_decision` line.

Applied at: `JokeViewSet` list/retrieve/search/random/trending (`views.py:161,319,371,563`), reveal (`:664`), collections/saved (`:985`), daily today/history (`:1182,1223,1270`), share page (`:1380` → content-free `share_redirect.html` when gated, never 404), favorites (`:1838`), mystery box (`:2826`), recently viewed (`:2875`), pack detail serializer (`serializers.py:1355-1364`), creator profile (`creator_insights/views.py:66`), sitemap (`jokes/sitemap.py` uses BASE_TIERS). Retrieval of a tier_2 joke by a minor/anon → 404 (tests `tests_compliance.py:523-535`).

**Finding:** `UserPreference.show_mature` is **not writable (or readable) through any API** — not in `UserPreferenceSerializer`/`UserPreferenceUpdateSerializer` fields (`serializers.py:488-503`) nor `UserPreferencesView` (`views.py:2084-2149`); `grep show_mature jokes/serializers.py jokes/views.py` → 0 hits. Only Django admin (`UserPreferenceAdmin` change form) can flip it. Consequently tier_2 jokes (every UGC joke approved with an `age_rating.min_age >= 18`) are effectively invisible to all API users in prod unless staff toggles the flag. Docs (COPPA plan Wave 1B Task 1) describe `show_mature` as an "adult opt-in" but no opt-in UI/API path exists in backend.

### 3.2 Age / DOB
- `UserProfile.date_of_birth` (null → treated as minor). `age`, `is_adult (>=18)`, `is_minor` properties (`models.py:566-590`).
- Email registration (`EmailOnlyRegisterSerializer`): `date_of_birth` required, write-only; future/today → "Enter a valid date of birth."; age <13 → "You must be at least 13 years old to use Jokes For."; persisted on the signal-created profile. Tests `tests_compliance.py:131-169`.
- Google OAuth (`SocialAccountAdapter.pre_social_login`, `adapters.py`): existing linked user or existing local account with same email → no DOB gate, existing DOB kept; brand-new user → DOB required (`400 {"code":"dob_required"}`), invalid → 400, <13 → 400, all before any row is created; `save_user` persists DOB. `GoogleLogin.post` stashes raw DOB on the underlying HttpRequest. Tests `tests_google_age_gate.py`.
- DOB is **immutable after signup**: no API PATCH path exposes it (`UserProfileView.patch` handles only names/bio/display_name/handle). It is readable by the owner via `JokesForUserDetailsSerializer.date_of_birth` (GDPR Art. 15 justification in docstring) — the frontend uses it to gate analytics consent (`src/features/consent/*`).
- Under-13 handling = hard block at signup; no parental-consent flow (frontend legal draft `children.ts` states the same). No mechanism to detect/purge an under-13 account that lied about DOB beyond staff deleting the user in admin.
- Google users skip email verification (`notifications/tests/test_google_exemption.py`).

### 3.3 Consent records
- Backend stores **no consent record**. Analytics/cookie consent is a versioned `localStorage` record in the frontend (`src/features/consent/storage.ts`, key `jokesfor-consent`, `{version, analytics, ts}`) gated additionally on `isAdult(date_of_birth)`. No server-side evidence of consent, no consent timestamp in the audit log. `UserProfile.share_analytics` (default False) exists and is exposed via preferences `privacy.share_analytics` but nothing in the backend reads it.
- Email marketing consent = `UserProfile.email_digest_opt_in` / `creator_milestone_opt_in`, **default True** (opt-out model, per spec product call). No timestamp of opt-in/out is stored (unsubscribe flip is not audited).

---

## 4. GDPR

### 4.1 Data export (`GET /api/v1/users/me/data-export/`, `views.py:2499-2657`)
Synchronous zip containing `jokes-for-data-export.json` (`DjangoJSONEncoder`). Sections: `export_meta, account (id,email,username,date_joined,last_login,is_active), profile (bio, avatar name, is_premium, public_profile, show_activity, share_analytics, theme, created_at), preferences (notification_enabled, notification_days, onboarding_completed, tones, contexts), collections, saved_jokes (excl. removed), favorites (excl. removed), ratings, reactions, daily_jokes, views[:5000], streak, streak_days, submissions (id,text,setup,punchline,status,created_at), media_assets (url null when quarantined), reports_filed, blocks, achievements, vibes, pack_progress, mystery_rolls, share_events, email_logs`. Audits `data_export`.
**Not exported** (Art. 15 completeness gaps): `date_of_birth`, `display_name`/`handle`, `email_digest_opt_in`/`creator_milestone_opt_in`, `show_mature`, published `Joke` rows attributed to the creator, `Appeal` rows, inbox `Notification` rows, `Follow` rows (both directions), billing `Subscription`/`Tip` rows, telemetry `JokeImpression`/`JokeDwell`/`JokeWatch`, `AuditLog` rows about the user, `rejection_reason` on submissions. No throttle beyond global `user 1000/hour`; the export is unbounded except `views[:5000]`.

### 4.2 Account deletion (`DELETE /api/v1/users/me/`, `views.py:2399-2497`)
- Re-auth gate first: usable password → `password` required + checked (400s); OAuth/unusable password → `confirm == 'DELETE'` required.
- Inside `transaction.atomic()`: (1) blacklist all `OutstandingToken`s; (2) `delete_with_files()` every owned `MediaAsset` (quarantined files included — test `test_account_delete_removes_quarantined_files`); (3) delete avatar file; (4) purge `EmailMessageLog` by FK OR `to_email` and `EmailVerification`; (5) **media-format jokes** created by the user (`FORMAT_RULES` formats requiring `media`) whose media link is now gone (`media__isnull=True`) are marked `is_removed=True, removed_at=now` (erasure wins); text jokes survive **anonymized** via `Joke.creator` SET_NULL; (6) `user.delete()` cascades.
- Audit `account_delete` AFTER commit with `actor=None`, `metadata={'actor_email_hash': <12-hex>}`. Note the hash used here (`observability.redaction.hash_email`, 12 chars) differs from `AuditLog.actor_email_hash` (`audit.services._hash_email`, 64 chars) — correlation requires prefix match.
- Cascade consequences (from FK definitions): `ContentReport.reporter` CASCADE (reports the user filed disappear, and reports *about* the user's jokes survive only for text jokes), `UserBlock` both sides CASCADE, `Appeal.user` CASCADE, `Notification.recipient` CASCADE / `actor` SET_NULL, `AuditLog.actor` SET_NULL (rows retained, hash preserved), `billing.Subscription.user` CASCADE, `billing.Tip.sender/creator` CASCADE (**financial records deleted with the user; no Stripe cancellation or customer deletion is attempted** — `grep stripe` in the view → none), `Follow` CASCADE.
- No grace period / soft delete; no email confirmation; deletion of a user with a live Stripe subscription leaves Stripe billing untouched (owner/ops risk).
- The appeal window is irrelevant on self-deletion (spec: "erasure wins").

### 4.3 Other GDPR touchpoints
- Right to rectification: bio/display_name/handle editable; DOB and email immutable (no change-email feature; comment in delete view).
- Retention: `AuditLog` append-only forever (pgtrigger `Protect` on UPDATE/DELETE; `audit/models.py:63-69`); `EmailMessageLog` retained until account deletion; `JokeView` etc. retained indefinitely. No retention sweeps.
- PII posture in audit: actor email hashed (SHA-256), IP masked (`mask_ip`: IPv4 last octet zeroed / IPv6 /48), UA truncated to 256, `metadata` caller-redacted.

---

## 5. Audit app (`audit/`)

- `AuditLog` fields: `actor` (SET_NULL), `actor_email_hash`, `action`, `target_type`, `target_id`, `ip`, `request_id`, `user_agent`, `outcome ∈ {success, failure, denied}`, `metadata` JSON, `created_at`. Indexes on action/outcome/created_at. **Append-only** via `pgtrigger.Protect(Update|Delete)` (tests `audit/tests.py:61-69`).
- `record_audit(request, action, *, outcome, actor, target_type, target_id, metadata)` (`audit/services.py`): DB write try-wrapped (never breaks the request) AND always emits a `jokesfor.audit` structured log line (fallback sink). Request context from contextvars (`request_id`), XFF-first IP then masked.
- Signal receivers (`audit/signals.py`, connected in `AuditConfig.ready`): `login` success/failure (failure hashes the attempted identifier, never queries the user table — anti-enumeration), `logout`.
- Complete list of action names emitted in code:
  `login`, `logout`, `registration` (success/failure w/ `email_send_failed`), `content_report`, `block`, `unblock`, `content_takedown`, `media_quarantined`, `media_purged`, `media_upload`, `safesearch_block` (outcome `blocked`), `hash_match_hit` (outcome `blocked`), `appeal_filed`, `appeal_upheld`, `appeal_reversed`, `data_export`, `account_delete`, `digest_run`.
- **Not audited**: submission approval (`approve_and_publish`), submission rejection, `JokeAdmin.restore_jokes`, `dismiss_reports`/`mark_resolved`, direct `is_removed` flips in JokeAdmin, unsubscribe flips, preference changes (incl. `show_mature` via admin), password change/reset, email verification success, Google login (only allauth `user_logged_in` if fired), admin logins (Django admin uses session auth → `user_logged_in` signal does fire → `login` audit).
- `AuditLogAdmin`: read-only (no add/change/delete), list `action, outcome, actor, actor_email_hash, ip, created_at`, filters `action, outcome, created_at`, search `action, actor_email_hash, request_id`.

---

## 6. Email notifications (`notifications/`)

### 6.1 Engine
- `send_email(to_email, template_name, context, user=None, headers=None)` (`service.py`): renders from `templates_registry.TEMPLATES` (`verification_code`, `daily_digest`, `creator_milestone`; unknown → `UnknownTemplate`), creates `EmailMessageLog(status='pending')`, sends `EmailMultiAlternatives` (text + html) via `EMAIL_BACKEND` (prod: `anymail.backends.resend.EmailBackend`, `RESEND_API_KEY`; default console), marks `sent`/`sent_at` or `failed`/`error` and raises `EmailSendError`. Synchronous, in-request. `provider_message_id` field exists but is never populated.
- `EmailMessageLog`: `to_email, template_name, subject, status, provider_message_id, error, user (SET_NULL), created_at, sent_at`; index `(to_email, -created_at)`.
- Transports: only Django mail backend (Resend via anymail). No SMS/push. `UserPreference.notification_*` flags (daily_joke, trending_alerts, collection_updates, email_digest, notification_time/days) are **stored but consumed by nothing server-side** (frontend-only nudges). In particular `UserPreference.notification_email_digest` (default False, exposed through `/users/me/preferences/` as `notifications.email_digest`) is a *different field* from `UserProfile.email_digest_opt_in` (default True) which the digest engine actually reads — **the in-app toggle does not control digest emails; only the emailed unsubscribe link (or admin) does**.

### 6.2 Verification (`verification.py`, `views.py:35-104`)
- 6-digit `secrets.randbelow` code, SHA-256 hash stored, TTL `EMAIL_VERIFICATION_CODE_TTL_MINUTES` (10), `EMAIL_VERIFICATION_MAX_ATTEMPTS` (5; the 6th attempt returns `too_many_attempts`), `issue_code` invalidates prior codes, `verify_code` uses `hmac.compare_digest` and an atomic conditional consume.
- `VerifyEmailView`: unknown email → same 400 `{'code': ['Incorrect code.']}` (anti-enumeration); already active → 400 detail; too many attempts → 429; success → `is_active=True` + JWT cookies set.
- `ResendVerificationView`: uniform 200; `ResendThrottle` 3 per 15 min keyed on normalized email (cache-backed; cache is DB table `jokesfor_cache`).
- `CookieRegisterView`: when `EMAIL_VERIFICATION_REQUIRED` (prod True per memory) creates inactive user, emails code, returns 201 with no tokens; provider failure → 502 with the account recoverable via resend; audits `registration`.

### 6.3 Digest engine (`digests.py`) vs spec (`2026-07-24-email-digest-design.md`)
- Eligibility: daily digest → `is_active=True AND profile.email_digest_opt_in=True` minus users with any `EmailMessageLog(template='daily_digest', created_at__date=today)` (sent OR failed counts as touched → failed recipients are not retried same day). Skipped entirely when `get_daily_editorial_joke(today)` is None (`skipped=True`). Email carries setup-only teaser (never the punchline), `reveal_url = FRONTEND_URL/daily`.
- Milestones: creators of live jokes, `is_active`, `creator_milestone_opt_in`, not already sent today; `new reactions (JokeReaction on non-removed jokes) since last successful creator_milestone sent_at (or ever) >= DIGEST_MILESTONE_THRESHOLD (10)`.
- Budget: single `cap` (`DIGEST_SEND_CAP`=500) shared digest-first then milestones; `remaining` reported. Per-send try/except (`EmailSendError` and any Exception) → `failed` count, never 500.
- Concurrency: `DigestRun` row per date with `claimed_until` CAS claim (10-min window) replacing the spec's implied advisory lock (documented rationale: Neon PgBouncer transaction pooling); second overlapping caller gets `locked=True` no-op; `finally` clears the claim. Counts accumulated with `F()`.
- Headers: `List-Unsubscribe: <url>` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058) on both digest types.
- Spec deltas: spec said "`DigestRun` row per date + EmailMessageLog ledger" ✔; spec "returns `{digests_sent, milestones_sent, skipped}`" → code adds `failed, remaining, locked`; spec "verified active users" → code uses `is_active` only (Google users are active without verification — consistent with the app's definition); spec "digest-hour env" → **not in code** (hour is Cloud Scheduler config only). The `EmailMessageLog` ledger uses `created_at__date` in the server TZ (UTC) — a run just after midnight UTC counts as a new day.

### 6.4 `RunDigestsView` token guard (`views.py:238-280`)
- `authentication_classes=[]`, `AllowAny`, `throttle_classes=[]`, `@extend_schema(exclude=True)`.
- Header `X-Digest-Token` stripped, encoded with `surrogateescape`, compared via `hmac.compare_digest` to `settings.DIGEST_CRON_TOKEN` (env, stripped). Missing header, wrong token, **or empty server secret → `Http404`** (dormant by default). Success → `run_daily_digests()` + audit `digest_run` (`metadata=summary`) + 200 summary. Token header is on the log-redaction denylist (`observability/redaction.py:33-34`). Tests cover 404 paths, non-ASCII/lone-surrogate probes, schema exclusion, audit row.
- Deployment status (memory + plan): DORMANT — owner must set `DIGEST_CRON_TOKEN`, create the Cloud Scheduler job (`0 15 * * *` UTC suggested, no retries), and replace `[COMPANY POSTAL ADDRESS]` in `notifications/templates/notifications/email/base.html` + `.txt` templates before enabling.

### 6.5 CAN-SPAM unsubscribe (`unsubscribe.py`, `EmailUnsubscribeView`)
- Token = `django.core.signing.dumps({'uid', 'type'}, salt='email.unsubscribe')`, max age 90 days; kinds `digest → email_digest_opt_in`, `milestone → creator_milestone_opt_in`. No PII in URL (test `test_token_carries_no_pii_in_plaintext`).
- `GET` renders a confirm page (token escaped into a hidden input) and **never mutates** (link-scanner safety). `POST` reads token from body OR query string (RFC 8058 one-click) → `apply_unsubscribe` flips the flag to False (idempotent), returns a plain HTML confirmation; any bad/expired/unknown-user token → 400 friendly page, never 500. No CSRF (`authentication_classes=[]`; DRF only enforces CSRF for session auth) and no auth.
- Templates: every digest/milestone email has an in-body Unsubscribe link and the postal-address row (placeholder). Transactional `verification_code` email carries no unsubscribe (exempt) but still renders the postal placeholder.
- Re-subscribe path: none in the API (the confirmation page says "from your account settings", but `/users/me/preferences/` writes `UserPreference.notification_email_digest`, not `UserProfile.email_digest_opt_in`). **Gap.**

---

## 7. Inbox app (in-app notifications)

- `Notification` (`inbox/models.py`): `recipient` CASCADE, `actor` SET_NULL, `verb ∈ {followed_you, joke_published, joke_removed, joke_rejected, appeal_resolved}`, `joke` SET_NULL, `data` JSON (DjangoJSONEncoder), `read`, `created_at`; index `(recipient, read, created_at)`.
- `notify(recipient, verb, actor=None, joke=None, **extra)` (`inbox/services.py`): no-op when recipient None or actor == recipient; `extra` → `data`. Synchronous, no fan-out control, no dedup (except follows: `Follow.get_or_create` only notifies on create).
- Call sites: `follows/services.py:17` (`followed_you`), `jokes/admin.py:369` (`joke_published`), `:481` (`joke_removed` w/ `reason`, `appeal_deadline`), `jokes/signals.py:172` (`joke_rejected` w/ `submission_id`, `rejection_reason`), `jokes/admin.py:672,733,744` (`appeal_resolved` w/ `outcome`, `action_type`, `submission_id`).
- API (`/api/v1/notifications/`): list (page size 20, `select_related actor, joke`), `unread-count/`, `mark-read/` (mark-all only; no per-item read, no delete). Serializer exposes `id, verb, read, created_at, data, actor {id, name, username}` (never email), `joke {id, preview: text[:60]}`. **Note:** `get_joke` renders `obj.joke.text[:60]` even for a removed joke (the `joke_removed` notice legitimately shows the creator their own removed joke's preview; FK bypasses the manager).
- No email transport for inbox notices (spec: inbox only for MVP). No push.
- `NotificationAdmin`: full CRUD by staff; search by recipient/actor email.

---

## 8. Django admin — what a staff user can do (T&S-relevant)

All admin classes are registered with default permissions (any `is_staff` user with model perms; no custom `has_*_permission` except the read-only ones). No custom admin site, no 2FA, session auth (`django.contrib.sessions`), `/admin/` publicly routed.

| Admin | Capabilities |
|---|---|
| `JokeAdmin` | Sees removed jokes (`all_objects`); edit text/classification incl. `content_tier` and `is_removed`; `removed_at` readonly; action **Restore selected jokes** (releases quarantine, regenerates cards). Direct `is_removed` tick = silent takedown (no notice/appeal/quarantine/report resolution). |
| `ContentReportAdmin` | Queue with `joke_removed` boolean; actions **Take down reported joke** (full DSA-compliant flow), **Dismiss**, **Mark resolved**; search by reporter email/joke text/description; edit any field. |
| `JokeSubmissionAdmin` | See media preview + SafeSearch flags; action **Approve and publish**; reject by editing `status`+`rejection_reason` (signal notifies); filters by status/format/age_rating. |
| `AppealAdmin` | SLA queue (pending-first, red ≥36h, overdue filter); actions **Uphold** / **Reverse**; edit `resolution_note`; raw-id pickers. |
| `UserBlockAdmin` | View/create/delete blocks. |
| `UserProfileAdmin` | Edit any profile field incl. `date_of_birth`, `email_digest_opt_in`, `creator_milestone_opt_in`, `is_premium`. |
| `UserPreferenceAdmin` | Edit prefs incl. **`show_mature`** (the only path to enable tier_2 for a user). |
| `MediaAsset` | **Not registered** in admin (no direct asset browsing/purge UI). |
| `AuditLogAdmin` | Read-only. |
| `EmailMessageLogAdmin`, `EmailVerificationAdmin`, `DigestRunAdmin` | Read-only. |
| `NotificationAdmin` (inbox) | Full CRUD. |
| Django `auth.User` admin | Default: deactivate/delete users, set staff/superuser. Deleting via admin **bypasses** `UserAccountDeleteView` (no storage cleanup of media/avatar, no token blacklist, no `account_delete` audit, EmailMessageLog rows survive with `user=NULL`). |

---

## 9. Settings that gate behaviour (`JokesForProject/settings.py`)
`SAFESEARCH_ENABLED` (env, default off), `EMAIL_VERIFICATION_REQUIRED` (default false; prod true), `EMAIL_VERIFICATION_CODE_TTL_MINUTES=10`, `EMAIL_VERIFICATION_MAX_ATTEMPTS=5`, `DIGEST_SEND_CAP=500`, `DIGEST_MILESTONE_THRESHOLD=10`, `DIGEST_CRON_TOKEN` (empty = dormant), `BACKEND_URL`, `FRONTEND_URL`, throttle rates `appeals 10/day`, `media-upload 30/hour`, `verification_resend 3/15min`, `anon 100/hour`, `user 1000/hour`. `ACCOUNT_EMAIL_VERIFICATION='none'` (allauth's own verification disabled; custom code path instead).

---

## 10. Risks / gaps (ranked)

1. **`show_mature` has no API** → mature (tier_2) UGC unreachable by design-intended adult opt-in; only admin can enable. Either a product gap or unintended.
2. **Digest opt-in mismatch**: `/users/me/preferences/` `notifications.email_digest` writes `UserPreference.notification_email_digest` (unused), while digests read `UserProfile.email_digest_opt_in` (default True). Users cannot opt back in, and cannot opt out in-app (only via email link). Confirmation page copy ("account settings") is misleading.
3. **JokeAdmin direct `is_removed` flip** produces a non-appealable, un-noticed takedown with media still at public paths (only the share card is blanked). DSA statement-of-reasons requirement is bypassed on this path.
4. **Admin `auth.User` delete bypasses erasure cascade** (media files, avatar, token blacklist, email logs, audit row).
5. **Account deletion ignores Stripe**: `Subscription`/`Tip` rows CASCADE-deleted; no Stripe customer/subscription cancellation; tip financial records lost (accounting/refund traceability).
6. **Data export incompleteness** (DOB, handle/display_name, appeals, notifications, follows, tips/subscription, published jokes, telemetry).
7. **No server-side consent record** (analytics consent lives in browser localStorage only); no audit of unsubscribe/opt-out.
8. **No text moderation automation** (no profanity/URL/spam filter) — all text UGC relies on manual admin review of `pending` submissions; no SLA on submission review, no admin reject action (free-text status edit).
9. **SafeSearch fail-open** + CSAM matcher dormant; screening verdicts are advisory except LIKELY adult/violence.
10. **Lazy purge trigger dependence**: quarantined media is only purged when someone uploads or files an appeal.
11. **Rejection appeal window anchored on `updated_at`** — owner edits to a rejected submission extend the window indefinitely.
12. **Postal address placeholder** in email templates (`[COMPANY POSTAL ADDRESS]`) — CAN-SPAM violation if digests are enabled before replacement.
13. Audit hash inconsistency (12-char vs 64-char SHA-256) between `account_delete.metadata` and `actor_email_hash`.
14. Reports on a removed joke → 400 (user cannot report content already removed — acceptable) but reports on blocked creators' jokes are possible only if the reporter can see them (they can't via feed, but can by direct ID — retrieve excludes blocked creators via `visible_jokes`, so 404).
15. Inbox notifications from a now-blocked actor remain visible; block does not purge historical `followed_you` notices.
16. No per-notification read/delete; mark-all only.

---

## 11. Test coverage snapshot (existing suites)
- `jokes/tests_appeals.py` (1503 lines): constraints, rejection signal, takedown notice reason/deadline, quarantine/release path semantics + non-derivability, takedown batch isolation, removed-joke exclusion across surfaces, lapse sweep (13d/15d, open appeal, live-joke guard), account delete removes quarantined files, endpoint 201/400/404 matrix, throttle scope, admin uphold/reverse incl. shared-asset guards, SLA red/overdue, IntegrityError race → 400, `removed_at=None` → 400, dims-only for quarantined in drafts/export.
- `jokes/tests_moderation.py`: manager filtering, block symmetry/visibility, profile 404, follow sever, dedup report, admin take-down/dismiss/restore.
- `jokes/tests_compliance.py` (868 lines): age math, registration DOB errors, `allowed_tiers` matrix, every read path tier exclusions incl. share page gated redirect, DOB in user details.
- `jokes/tests_google_age_gate.py`, `jokes/tests_media.py` (screening block 422, orphan sweep, takedown quarantines, account delete removes assets and takes down media jokes, export lists assets), `jokes/tests_launch_blockers.py` (tier derivation from age rating).
- `audit/tests.py`: dual sink, DB failure fallback, append-only trigger, login/logout/failed signals, metrics.
- `notifications/tests/*`: engine, verification lifecycle, verify/resend views, throttling (incl. Postgres cache), templates, digests (eligibility, idempotency, cap, milestones, failure isolation, claim/lock), trigger (404 paths, audit, schema exclusion, redaction), unsubscribe (GET no-mutate, POST flips, RFC 8058 query-string POST, error pages), registration flow, Google exemption.
- `inbox/tests.py`: notify semantics, `data` payload, serializer no-email, list/unread/mark-read, auth required.
