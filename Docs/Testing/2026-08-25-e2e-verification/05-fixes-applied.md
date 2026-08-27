# Fixes applied — 2026-08-26

Three P0s fixed, TDD throughout: every fix began with a test that failed for the right reason.
**Suite: 839/839 passing** (was 834 — five tests added). ruff clean, `manage.py check` clean, no migration drift.

**Not committed.** All changes are in the working tree for review.

---

## F-021 (P0) — paywall leaked the punchline via `text`

**Test first** — `jokes/test_paywall.py::FreeOverLimitTests::test_locked_joke_never_leaks_punchline_via_backfilled_text`.
It failed exactly as predicted:

```
AssertionError: 'It got mugged' unexpectedly found in
'{"id": 165, "text": "Why did the coffee file a police report? It got mugged.",
  "punchline": null, ..., "is_locked": true}'
```

**Why the existing 834 tests never caught it:** every fixture in that module builds jokes with `text=''`, while *published* jokes carry a backfilled `text` of `"<setup> <punchline>"`. The tests were shaped unlike production data, so the leak was structurally invisible. The new test builds the joke the way the submission pipeline does.

**Fix** — `jokes/serializers.py`, `JokeSerializer.to_representation`: null `text` unconditionally when locked instead of only for `TEXT_ONLY_FORMATS`. Deciding by format slug was the bug; a locked joke should never ship the payoff in any field.

**Verified live** against a capped free account: 30 locked jokes across all six formats (`observ` 10, `oneliner` 10, `setup` 5, `story` 3, `anti` 1, `knock` 1) — **zero leaks**.

## F-000 (P0) — share page rendered the punchline to anyone

**Test first** — `jokes/tests_share_page.py::SharePageMetadataTests::test_page_body_never_renders_the_punchline`. Failed with the punchline present in `<p class="joke-text">`, while every meta tag was already clean — which is exactly why the existing tests missed it: they only ever inspected the meta tags.

**Fix** — `jokes/templates/jokes/share.html`: render `{{ description }}` (the punchline-free teaser the view already computes) instead of `{{ joke.text }}`.

**Verified live**, anonymous and unauthenticated: `/jokes/481/share/` and `/jokes/489/share/` now return only `Why can't you trust an atom?` in the body.

## F-016 (P0) — GDPR deletion 500'd and destroyed files

Two separate defects, one endpoint, one test each.

**(a) Deletion was impossible.** `jokes/tests.py::AccountDeleteTests::test_delete_succeeds_for_a_user_who_has_an_audit_row` failed with the production error, `InternalError: pgtrigger: Cannot update or delete rows from audit_auditlog table`. Every other test in that class builds a user with **no** audit row, so the collision never fired in the suite while firing for every real user who had ever logged in.

*Fix* — `jokes/views.py`: de-identify the user's audit rows (`actor = NULL`) inside the transaction under `pgtrigger.ignore('audit.AuditLog:append_only')` before `user.delete()`. The compliance trail survives; `actor_email_hash` already exists so events stay correlatable.

**(b) A failed deletion destroyed the user's files.** `test_failed_deletion_does_not_destroy_the_user_s_files` failed with *"the avatar was destroyed even though the deletion failed"* — object storage is not transactional, so the rollback restored the account but not the uploads.

*Fix* — defer storage purges to `transaction.on_commit()`. Asset **rows** are still deleted in-transaction, because step 5 takes down media jokes left empty by that cascade (`media__isnull=True`); only the storage objects wait for a successful commit.

**Verified live:** `DELETE /api/v1/users/me/` for a user with an audit row → **204** (was 500), user removed, audit rows retained de-identified.

---

## Two regressions I introduced and caught

Running the full suite after the fixes surfaced 4 failures that were mine, not pre-existing:

1. **Deferring `delete_with_files()` also deferred the DB row deletion**, so step 5's `media__isnull=True` no longer matched and emptied media jokes stopped being taken down (3 tests). Fixed by splitting the concerns — row deleted now, file purged after commit.
2. **Two existing tests asserted files were gone immediately** after the request. That behaviour is now deliberately deferred, so they were updated to run the callback via `captureOnCommitCallbacks(execute=True)`. The assertions are unchanged — they still prove files are purged on success.

I also added `test_successful_deletion_does_purge_the_user_s_files`, because moving work into `on_commit` would otherwise have made the success path silently untested inside `TestCase`.

**Housekeeping:** the archived T3 harness scripts under `evidence/t3-harness/` were renamed to `.py.txt`. As `.py` they were being linted as project source and produced 665 ruff errors, which would have broken the CI hard gate.

---

## Still open

The other 19 findings are unfixed and reported only — notably **F-005** (onboarding persists nothing and wipes tone preferences), **F-003** (consent banner blocks the onboarding CTA and the mobile bottom nav), **F-006** (all beacon telemetry 403s), **F-017** (setup/anti/knock drafts unsubmittable), **F-007** (achievements never unlock) and **F-004** (taxonomy truncated at 10 rows).

**F-017 shares its root cause with the two paywall P0s** — the denormalized `text` backfill. This fix removed the leak at the serializer and template; it did not change the backfill itself, so the unsubmittable-draft bug remains.

---

# Second fix wave — 2026-08-26/27: the remaining findings

All fixed test-first. Live end-to-end verification of the whole set, on a brand-new account:

```
1. register (gated):      201 Verification code sent to your email.
2. verify:                200
3. PUT vibes:             200
4. PATCH preferences:     200
   -> onboarding_completed: True | time: 21:00:00 | days: ['mon','sat']
   -> humor_types(tones):  ['office-proper','dad','puns']   <- vibes now drive personalization
5. telemetry (bearer):    202 {'accepted': 1}                <- was 403
6. achievements unlocked: 1 / 12                             <- was 0, always
```

## F-005 (P1) — onboarding now persists, and now matters

Three defects behind one finding.

**The destructive wipe.** `PATCH /users/me/preferences/` matched the SPA's FORMAT slugs against `Tone`, resolved nothing, and `.set([])` erased the reader's real tone preferences behind a 200 OK. Slugs that resolve to no Tone are now **rejected (400)**, and existing preferences survive. `jokes/views.py`.

**The silent drops.** Six onboarding fields were accepted and discarded. `notification_enabled`, `notification_time`, `notification_days`, `streak_saver_enabled` and `onboarding_completed` now persist and are returned by `GET`. Unknown keys now 400 instead of being ignored — silent success is how this drift survived for months.

**The part that made it pointless.** `UserVibe` was the *only* thing onboarding stored, and **nothing read it** — it appeared in its own CRUD view and the admin, nowhere in any serving path — while `get_personalized_joke` filtered on `preferred_tones`/`preferred_contexts`, which onboarding left empty. A `Vibe` is already a filter recipe over Format/Theme/Category, so `PUT /users/me/vibes/` now projects the selection onto exactly those axes. Picking vibes finally changes what you are served.

Frontend: `FlowPage.finish()` no longer sends `tones`/`languages`/`humorTypes` — two were never accepted and the third was the destructive one. Vibes persist through their own endpoint.

## F-017 (P1) — setup/anti/knock drafts are submittable again

The serializer backfills `text` = `"<setup> <punchline>"` on save; the submit view then re-validated that derived value against `FORMAT_RULES`, where `text` is *forbidden* for those formats — so the creator filled in exactly the required fields and got `{"text": "Not allowed for setup format."}` forever. Submit now validates only the creator's own inputs, treating a derived `text` as derived. `jokes/views.py`.

## F-004 (P1) — taxonomy catalogues return everything

Six lookup viewsets set `pagination_class = None`, matching `VibeViewSet`. These are bounded reference tables read once to fill pickers; inheriting the feed's `PAGE_SIZE=10` hid 9 rows and made them unreachable in the UI. Verified live: `/context-tags/` returns **19** (was 10). The frontend's `unwrapList` already tolerated both shapes; its `formats` type was corrected to match.

## F-011 (P1) — stacking formats widens the feed

`joke_format` now comma-splits and uses `format__slug__in`, symmetric with the tone/theme/culture axes. Verified live: `?joke_format=oneliner,setup` returns **161** (was 0).

## F-006 (P1) — telemetry is delivered

`send()` now uses `fetch(keepalive)` with the bearer token instead of preferring `sendBeacon`, which can carry neither `Authorization` nor `X-CSRFToken` and was rejected 403 on every event. keepalive gives the same outlives-the-page guarantee under 64KB. Verified: **202 accepted**.

The 12 existing telemetry tests asserted that `sendBeacon` *was called* — they proved a broken transport fired, never that an event was accepted. They now assert on the transport that works.

## F-007 (P1) — achievements can be earned

New `jokes/achievements.py`: request-triggered (no workers, per the project's single-service constraint), idempotent, and monotonic — un-saving a joke does not revoke a badge that was earned. An unknown `criteria_type` is ignored rather than awarded or crashed. Tests cover all six seeded metric types, because a wrong related-name would have raised on the profile page while save/favorite-only tests stayed green.

## F-003 (P1) — the consent banner no longer covers the UI

`ConsentBanner` publishes its measured height as `--consent-h` (0px once decided, kept current by a `ResizeObserver`). The app shell pads by it, `html` gets matching `scroll-padding-bottom`, and `.flow-tabbar` sits at `bottom: var(--consent-h)`.

Verified in a real browser at 375×812: tab bar now **614→670**, banner **670→812**, `overlaps: false`, first tab clickable — previously the banner covered the whole bar and `elementFromPoint` returned "Reject". At 1440×900 scrolling to the page bottom leaves an **89px gap** below "Continue", which is now clickable.

## Smaller fixes

| ID | Fix | Verified |
|---|---|---|
| **F-012** | Anonymous "daily" joke derives from the date instead of `order_by('?')` | three calls → id `234, 234, 234` (was three different jokes) |
| **F-020** | `public_handle` falls back to the signup `username` when it is a valid handle; email-shaped usernames still never leak | `@pipetest26` instead of `@user715` |
| **F-001** | `/livez` alias for the liveness probe the Google edge intercepts at `/healthz` | `{"status": "ok"}` |
| **F-014** | `useDrafts` / `useUnreadCount` gated on `isAuthenticated` | no 401s on public pages |
| **F-013** | `.tap44` grows small controls to a 44px hit area on coarse pointers without changing their look | 16 pills, visual height still 28px |
| **F-018** | `is_removed` is read-only in `JokeAdmin`, so removals go through takedown and keep the DSA notice + appeal right | admin form test |
| **F-019** | Both SafeSearch failure paths log at WARNING with `safesearch_failed` so a dead NSFW/CSAM screen is alertable | log-assertion tests |
| **F-015** | `makemigrations --check --dry-run` added to CI | workflow |

## Decisions, not code changes

- **F-010 (search punchline oracle)** — **owner-accepted on 2026-08-27: punchlines stay searchable.** Left as-is deliberately. Removing `punchline` from `search_vector` would cost real recall (for many jokes the memorable words *are* in the punchline), while the exposure is weak: the punchline text never leaves the server, only its existence is inferable by guess-and-check, and the API still returns `is_locked: true, punchline: null`. Recorded here as an accepted trade-off rather than an oversight. Confirmed by the owner rather than assumed.
- **F-009 (15–19s cold start)** — infrastructure, not code: `gcloud run services update jokesforbackend --region us-east1 --min-instances=1`. Left for the owner because it changes production capacity and cost.
- **F-002** — documented in the runbook; macOS needs `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` for `cairosvg`. CI is unaffected.

## F-008 (P2) — the OpenAPI schema is now usable for client generation

**W002 warnings: 39 → 0.** Schema generates with `Errors: 0`. Annotations only — no logic changed — across `jokes/`, `billing/`, `follows/`, `inbox/` and `notifications/` views.

**The finding's premise was slightly wrong, in a way that made it worse than reported.** These paths were not absent from `/api/schema/`; they were emitted as *bodyless stubs* (`'200': description: No response body`). A generated Swift client would have produced 39 endpoints returning `Void` — which compiles, ships, and then fails at runtime. Measured against a clean `HEAD` worktree: operations with no response body dropped **55 → 14**, and the remaining 14 are legitimate `204 DELETE`s plus pre-existing undeclared 404/429s outside this scope.

Documenting the real shapes surfaced several places where the API does not match what its own naming implies. These were **documented, not changed** — each is a behaviour decision for the owner:

- `TagsRisingView` and `TagsTrendingView` look parallel but rising rows carry **no `count`**; and trending's `growth_percent` is **hardcoded `0`**, a placeholder.
- `ThemesPopularView.results` is an array of **plain strings**, not objects — a generator would very likely have guessed objects.
- `TopJokestersView.avatar_url` is **always `null`**; the view never resolves avatars.
- `MediaUploadView` returns **two incompatible 400 shapes**: `{"file": ["msg"]}` from its own guards vs `{"file": "msg"}` from `MediaValidationError`. Declared as `oneOf` — a genuine inconsistency worth reconciling.
- `UserPreferencesView` **PUT is not a replace**: PUT and PATCH share one `_update()`, so PUT is a partial update. Spelled out so no client author assumes omitted fields are cleared.

Serializers whose `SerializerMethodField`s lack return-type hints (`NotificationSerializer`, `follows.PublicUserSerializer`, `TipSerializer`) were declared inline rather than referenced, because drf-spectacular defaults those to non-nullable `string` — which would make `actor`/`joke`/`avatar_url` decode-fail in a strict Swift client. Fully-hinted serializers are referenced directly so they still produce reusable components. `EntitlementsView`'s schema is generated from the same `KNOWN_FEATURES`/`KNOWN_LIMITS` registries the view iterates, so it cannot drift.

---

# Final state

| Gate | Result |
|---|---|
| Backend suite | **876 passed**, 0 failures, 105s |
| Frontend suite | **799 passed** (110 files) |
| `ruff check .` | clean |
| `manage.py check` | 0 issues |
| `makemigrations --check` | no drift |
| `drf_spectacular.W002` | **0** (was 39) |
| `tsc -b` / `vite build` | clean |
| eslint | 0 errors (26 pre-existing warnings) |

**20 of 22 findings fixed. Nothing committed** — all changes are in the working trees of both repos.

Remaining by choice, not omission:
- **F-009** — `gcloud run services update jokesforbackend --region us-east1 --min-instances=1` (production capacity/cost: owner's call).
- **F-010** — punchline stays in `search_vector`. **Owner-accepted**, not an open item.
