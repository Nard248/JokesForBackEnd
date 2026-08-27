# Completeness Critic — audit of the 14 JokesFor analyzer reports

Key: `completeness-critic` · Date: 2026-08-25 · Read-only.
Backend (BE): `/Users/narekmeloyan/PycharmProjects/JokesForProject` · Frontend (FE): `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend`

Method: read all 14 reports end-to-end, diffed the module inventories of `BE/jokes/*.py`, every other BE app, and `FE/src/features/*` against what the reports mention, then resolved every cross-report disagreement by reading the code (and, for the local DB, one read-only `SELECT` on `django_migrations`). One planned prod probe (signature-less `POST /api/v1/billing/webhook` to distinguish dormant vs enabled Stripe) was blocked by the sandbox classifier; that contradiction is resolved on infra-ops' live `gcloud run services describe` evidence instead.

---

## 1. Coverage matrix

### 1.1 Backend `jokes/*.py` (non-test) vs reports

| Module | Covered by | Depth | Verdict |
|---|---|---|---|
| `admin.py` | be-architecture §3.1, be-compliance §8 | good (actions, SLA queue) | one factual error (see C4) |
| `identity.py` | be-architecture, be-api-surface | adequate | — |
| `managers.py` (search) | be-architecture one paragraph | **thin** — no semantics of `q`/ordering/filters, no punchline-oracle note | **GAP G4** |
| `media_probe/processing/screening.py` | be-media-pipeline | excellent | — |
| `models.py` | be-architecture | excellent | — |
| `moderation.py` | be-compliance §1.2 | good | — |
| `password_reset.py` | be-auth-session §8 | good | template-location claim wrong (C8) |
| `paywall.py` | be-billing §3, be-api-surface §0 | excellent | — |
| `quarantine.py` | be-media, be-compliance | excellent | — |
| `recommendations.py` (daily joke) | be-architecture one line | **thin** — algorithm, exhaustion, anon randomness, digest "editorial" mode never described | **GAP G3** |
| `serializers.py` | spread across reports | good for Joke/paywall; `UserPreferenceUpdateSerializer` vs composite view duality unexplained | GAP G1 |
| `serving.py` | be-compliance §3 | excellent | — |
| `share_cards.py` | be-media §7 | excellent | — |
| `signals.py` (streak) | be-architecture | adequate; read-path `_reconcile_streak` only named in be-api-surface | GAP G3 |
| `sitemap.py` | be-api-surface #3 | good | — |
| `submission_rules.py` | be-media §10 (media formats only) | **partial** — text-format constraints (knock 4–8 lines/200 chars, story ≥30 words) never listed | filled in §2.5 below |
| `urls.py`, `views.py` | be-api-surface | excellent (route-level) | — |
| `templatetags/mathfilters.py` | be-media | fine | — |
| `management/commands/*` | be-architecture §4, local-dev-runbook §7 | good | — |
| `fixtures/*` | be-architecture, runbook | good (legacy-pk warning) | — |

Other apps: `notifications/*` (be-compliance §6 — excellent), `billing/*` (be-billing — excellent), `creator_insights/*` (be-billing §4 — good), `follows/*`, `inbox/*`, `audit/*` (be-architecture + be-compliance — good), `JokesForProject/observability/*` (infra-ops §9 — excellent), `health.py` (infra-ops §10 — excellent).

**Subsystem with zero functional coverage: achievements.** Every report lists `Achievement`/`UserAchievement` and the `/users/me/achievements/` endpoint, but none says how achievements are *earned*. Code check: `grep -rn "UserAchievement\|criteria_type"` outside tests/migrations hits only `models.py`, `admin.py`, `views.py:2059-2067` (read), `views.py:2622` (export) and `seed_achievements.py`. **No code path ever creates a `UserAchievement` row** — `criteria_type`/`criteria_value` are decorative. `/users/me/achievements/` returns `unlocked:false` for every achievement forever unless staff adds rows in Django admin.

### 1.2 Frontend `src/features/*` (28 dirs) vs reports

All 28 feature directories are named in fe-architecture-routes §5 with hooks and endpoints; fe-data-layer §9 cross-checks every endpoint string. `src/lib/*` (axios, api, api-adapter, telemetry, dailyReset, firebase, seo) is covered. `src/content/legal/*` is covered by known-gaps R-CMP-1.

Not mentioned anywhere (all presentational; low risk): `components/{BlockButton,BlockedUsersList,CollectionCard,DailyJokeCard,EditorsPickCard,FreshArrivalCard,JokeOfTheDayCard,Pagination,ProCommunityCard,SavedJokeRow,SearchFilters,TopJokesterItem,VibeCard,WeeklySpecialCard}.tsx`, `components/search/*`, `components/ui/{avatar,badge,button,card,chip,input,progress-bar}.tsx`, `lib/utils.ts`.

Under-described: the **reading loop itself**. `FlowJokeCard` is consumed by 13 files (`ExplorePage, SearchPage, TrendingPage, FavoritesPage, LibraryPage, CollectionDetailPage, PackDetailPage, JokeDetailPage, FlowCanvasPage, CreatorInsightsPage, HomePage, SubmitJokePage, JokeRenderer`), yet no report walks a page-level journey (card → reveal → `POST /reveal/` or telemetry → lock UI → save/react/share). `FlowCanvasPage` and `FlowPage` have no tests (fe-tests §8) and no report describes what `FlowCanvasPage` actually renders as its feed (its "For You" query never fires — fe-data-layer #3 — so what *does* the hub show?). → **GAP G6**.

---

## 2. Subsystems the reports missed — code-verified facts

### 2.1 Onboarding never persists (new finding; changes fe-architecture's claim)
`FE/src/pages/FlowPage.tsx:62-78` `finish()` calls `useUpdatePreferences` with `{tones: <vibe slugs>, humorTypes: <FORMAT slugs>, languages:['english'], notificationEnabled, notificationTime, notificationDays, streakSaverEnabled, onboardingCompleted:true}`. `api-adapter.ts:679-703 toDTO` forwards them to `PATCH /users/me/preferences/`. BE `UserPreferencesView._update` (`jokes/views.py:2115-2148`) handles **only** `humor_types`, `notifications`, `privacy`, `theme`:
- `humor_types` = format slugs (`oneliner`, `setup`, …) → `Tone.objects.filter(slug__in=…)` matches nothing → **`preferred_tones.set([])` wipes the user's tone preferences** (which `get_personalized_joke` uses for the daily joke).
- `tones`, `languages`, `notification_*`, `streak_saver_enabled`, `onboarding_completed` are silently dropped. `UserPreference.onboarding_completed` stays `False`; `notification_days/time/enabled` stay at model defaults, so `GET /users/me/today-status/` (`DailyRitualStatusView`) always reflects defaults, never the ritual the user chose.
- The endpoint that *would* persist these (`PATCH /preferences/me/` via `UserPreferenceUpdateSerializer`, `serializers.py:447`, and `POST /preferences/complete-onboarding/`) is defined in `api.ts:516` but never called (fe-architecture §5 already noted `completeOnboarding` unused).
Net: the only server-side effect of the 3-step onboarding is `PUT /users/me/vibes/`.

### 2.2 Lookup-catalog truncation is real, not hypothetical
fe-data-layer #4 flagged "any catalog with >10 rows is truncated" as a risk. Migration `0021_seed_demo_data.py:39-53` seeds **13 ContextTags (themes)** and `0021:56-67` seeds 9 Tones; formats = 6 + `0031` image + `0032` video/audio = 9. `PAGE_SIZE=10` with no `page_size_query_param`; `FE/src/features/create/api.ts:18-24` fetches page 1 only (`unwrapList`). Therefore in **prod** `GET /context-tags/` returns 10 of 13 themes and the creator editor's TagPicker / Explore theme axis can never offer three of them. Locally (legacy `lookup_data` fixture also loaded) formats are 11 and tones 14, so FormatPicker and tone pickers are truncated there too. `VibeViewSet` is the only lookup with `pagination_class=None` (`views.py:2673`).

### 2.3 Daily joke selection (`jokes/recommendations.py`)
- **Anonymous** `GET /daily-jokes/today/` (`views.py:1170-1197`): `Joke.objects.filter(content_tier__in=allowed_tiers).order_by('?').first()` — a **different random joke on every request**; no date binding, no `id`/`issue_label`. The docstring's "editorial pick" is misleading.
- **Authenticated**: `get_personalized_joke(user, exclude=get_recently_shown_joke_ids(user, 30 days), allowed_tiers)`: base = allowed tiers minus removed minus blocked creators minus 30-day `DailyJoke` history; if `UserPreference` has any of `preferred_tones/preferred_contexts/preferred_age_rating/preferred_language`, AND-combine them and use that subset **only if non-empty** (else fall back to base); order `-save_count, '?'`. Returns `None` when the base is exhausted → view 404s. `update_or_create(user,date)`; `delivered_at` stamped on first access.
- **Digest "editorial" joke** (`get_daily_editorial_joke`) is unrelated to what anon sees: it is the mode of that date's authenticated `DailyJoke` rows restricted to `tier_1` and not removed, tie-broken by lowest `joke_id`; `None` (digest skipped) if no authenticated user opened the app that day.

### 2.4 Search engine (`jokes/managers.py`)
- FTS only: `SearchQuery(q, search_type='websearch', config='english')` against `search_vector` (pgtrigger over `text, setup, punchline`, GIN). `TrigramExtension` (migration 0002) exists but **no trigram similarity is used anywhere** — no fuzzy matching.
- `q` blank → browse mode. Ordering: `popularity` = `-like_count(ratings=1), -save_count, -created_at`; `-created_at`; `relevance` only honoured when `q` present, otherwise silently falls to `-created_at`; default = `-rank` when searching, else `-created_at`. Always `.distinct()`.
- Filters: `format` exact single slug (no comma split — confirms fe-data-layer #5), `age_rating` exact, `tones/context_tags/culture_tags` `__in`, `language` code. Aliases `categories`/`themes` are not read.
- **Paywall oracle**: because the search vector includes `punchline`, a locked reader can search punchline words and see which joke matches (`is_locked:true`, `punchline:null`). Content is not disclosed but existence is — worth a documented test/decision.

### 2.5 Text-format submission rules (`jokes/submission_rules.py`) — the part be-media left out
`oneliner`/`observ`: `text` required; `setup,punchline,lines` forbidden. `setup`/`anti`: `setup`+`punchline` required; `text,lines` forbidden. `knock`: `lines` required (list of 4–8 non-empty strings, each ≤200 chars); `text,setup,punchline` forbidden. `story`: `text` required, **≥30 words**. Blank values for forbidden fields pass silently. Error strings: `"This field is required for {slug} format."`, `"Not allowed for {slug} format."`, `"Knock format requires at least 4 lines."`, `"Story must be at least 30 words."`, `"Line N exceeds 200 character limit."`.

### 2.6 Streak has two reconcilers
Write path: `post_save(JokeView)` → `update_streak_on_view` → `_walk_gap` (`signals.py`). Read path: `GET /users/me/streak/` → `_reconcile_streak` (`views.py:2890-2913`) → same `_walk_gap` + monthly freeze refresh, but **only if `last_active_date` is set** and it does not bump `current_count` (read-only reconcile). Only `test_streak_time_progression.py` covers the signal path; the read-path reconcile of a multi-day gap without a new view is untested.

### 2.7 Google login creates a Django session and an audit row (code-traced, medium confidence)
dj-rest-auth `SocialLoginSerializer.validate` (`registration/serializers.py:158`) calls allauth `complete_social_login` → `flows.login.complete_login` → `_login` → `perform_login` → `resume_login` → **`adapter.login(request, user)`** → `DefaultAccountAdapter.login` → `django.contrib.auth.login` (`allauth/account/adapter.py:544-562`). Consequences: `POST /auth/google/` (unlike `/auth/login/`, where `SESSION_LOGIN=False` skips `process_login`) sets a `sessionid` cookie, fires `user_logged_in` (→ `audit` `login/success` row), and updates `last_login`. DRF has no `SessionAuthentication` so API auth is unaffected, but a staff user who signs in with Google gets a live Django admin session. No test asserts either way (`tests_google_age_gate.py` patches only `complete_login`).

### 2.8 Local DB is 8 migrations behind (runbook wrong)
`SELECT app, max(name) FROM django_migrations` (read-only): `jokes 0033_jokewatch` (files go to `0036`), `notifications 0002` (head `0004`), `billing 0003` (head `0004_tip`), `inbox 0001` (head `0004`), `audit 0001`, `follows 0001`. So `Appeal`, `MediaAsset.quarantined_at`, `UserProfile.creator_milestone_opt_in`, `DigestRun`, `Tip`, and inbox `data`/verb choices **do not exist in the local dev DB** until `migrate` runs. Test runs are unaffected (fresh `test_jokesfor`), but any local full-stack E2E of appeals/tips/inbox against `runserver` will 500 until migrated.

### 2.9 Bearer-header auth path is untested — confirmed
`grep -rl HTTP_AUTHORIZATION` over project tests: zero hits. Every authenticated backend test uses `force_authenticate`/`force_login`. The iOS transport (Bearer) is library behaviour only.

### 2.10 `show_mature` has no API — confirmed
`grep show_mature jokes/serializers.py jokes/views.py` → 0 hits. tier_2 is unreachable through the API for any user.

---

## 3. Contradictions between reports — resolved against code

| # | Topic | Report A | Report B | Code says |
|---|---|---|---|---|
| C1 | **Stripe in prod** | be-billing §0/§5: "DORMANT: `STRIPE_SECRET_KEY` unset ⇒ 503 / `billing_dormant`" (from memory notes) | infra-ops §5/§11 (live `gcloud run services describe`): `STRIPE_SECRET_KEY=sk_test_…`, `STRIPE_PUBLISHABLE_KEY=pk_test_…`, `STRIPE_WEBHOOK_SECRET=whsec_…` set as plain env | **infra-ops is right (live evidence).** `is_enabled()=bool(STRIPE_SECRET_KEY)` ⇒ prod billing is *enabled in test mode*: `POST /tips/checkout/` returns a real test-mode Checkout URL (TipButton's "coming soon" branch will not trigger), `POST /billing/checkout-session` returns **422** (blank `stripe_price_id`) not 503, the webhook verifies signatures (R-BIL-2 "forgeable" is moot in prod because `whsec_` is set). be-billing's status matrix and known-gaps R-BIL-1 wording ("test-mode/dormant") need this correction. Not re-probed (sandbox blocked the POST). |
| C2 | Login for inactive (unverified) user | local-dev-runbook §3.2: `"User account is disabled."`; be-api-surface #11 lists both messages | be-auth-session §4.1: only `"Unable to log in with provided credentials."` | **be-auth-session.** allauth `_check_password` returns `None` when `user_can_authenticate` fails (`auth_backends.py:91-96`), so dj-rest-auth `get_auth_user` returns `None` → `validate` raises the generic message (`dj_rest_auth/serializers.py:127-131`); `validate_auth_user_status` is unreachable. |
| C3 | Duplicate content reports | known-gaps R-MOD-1: "no view-level dedup; second POST → 201 (currently)"; also lists dedup as the never-resolved D4 | be-compliance §1.1 / be-api-surface #108: repeat pending report → 200 with the existing row | **be-compliance.** `ContentReportView.create` (`views.py:2281-2291`) returns the existing pending report with 200. True residue: no DB uniqueness and no scoped throttle on `/reports/`. |
| C4 | `MediaAsset` in admin | be-architecture §3.1: "all models registered" | be-compliance §8: "`MediaAsset` not registered" | **be-compliance.** No `@admin.register(MediaAsset)` in `jokes/admin.py`; also unregistered: `JokeImpression`, `JokeDwell`, `JokeWatch`, `JokeMedia`, `JokeSubmissionMedia`, `Source`? (Source IS registered at :90). |
| C5 | Local DB migration state | local-dev-runbook §1.2/§0: jokes at `0033_jokewatch` "(head)", `showmigrations` → "0 unapplied", `migrate` "safe/no-op" | known-gaps R-OPS-9: local behind (jokes 33/36, notifications 2/4, billing 3/4, inbox 1/4) | **known-gaps.** See §2.8 — 8 migrations pending locally. |
| C6 | Google sign-in when an email/password account with the same email exists | be-compliance §3.2: "existing local account with same email → no DOB gate, existing DOB kept" (implies login proceeds) | be-auth-session §6: 400 `"User is already registered with this e-mail address."` | **be-auth-session.** `dj_rest_auth/registration/serializers.py:165-178` raises when `not login.is_existing` and `UNIQUE_EMAIL` and a user with that email exists. No auto-link. |
| C7 | Audit row / session on API login | be-auth-session §4.1/§16: "`user_logged_in` never fires for API logins; only failures audited" | be-compliance §5: "Google login (only allauth `user_logged_in` if fired)" | **Both partially right.** Password login: no session, no signal (dj-rest-auth `LoginView.login` skips `process_login` when `SESSION_LOGIN=False`). Google login: allauth `resume_login` → `adapter.login` → `django_login` ⇒ session cookie + `user_logged_in` ⇒ `audit login/success` row (§2.7). |
| C8 | Password-reset email template | be-auth-session §8: "project override in `BE/templates/`" | be-architecture §1.3/§6: root `templates/` is empty | **be-architecture.** `ls -la templates` → empty. The template is allauth's packaged `account/email/password_reset_key_message.txt`; only the URL is customised (`jokes/password_reset.py`). |
| C9 | Stripe return URLs | be-billing §1.8 / known-gaps R-BIL-8: FE has no `/billing/success` route; prod values unknown → checkout lands on 404 | infra-ops §5: prod `BILLING_SUCCESS_URL=https://jokesforfront.web.app/settings/billing?checkout=success`, cancel `…?checkout=cancel`, portal return `/settings/billing` | **infra-ops.** Prod returns to an existing `ProtectedRoute` page. Residual: `BillingPage.tsx` never reads `checkout=` (no `useSearchParams`/`location.search`), so there is no success/cancel acknowledgement; and the settings **defaults** are still `localhost:5173/billing/…` (relevant to local E2E, not prod). |
| C10 | Onboarding completion | fe-architecture §2 (`/flow`): "PATCH preferences with `onboarding_completed: true`" (reads as persisted) | fe-data-layer #7: BE ignores `onboarding_completed` etc. | **fe-data-layer, and worse than stated** — see §2.1 (format slugs sent as `humor_types` wipe `preferred_tones`). |
| C11 | Tip terminal status | local-dev-runbook §4: `Tip.status 'pending'→'paid'` | be-billing §2.3: `succeeded` | **be-billing.** `billing/webhooks.py:139 tip.status = 'succeeded'`. |
| C12 | Anonymous daily joke | be-api-surface #71: "random tier_1 joke" | fe-data-layer §9: "anon = random editorial" / view docstring "editorial pick" | Both acceptable; precise statement: `order_by('?')` **per request** — not a fixed pick for the day and not `get_daily_editorial_joke` (§2.3). |
| C13 | Share-page test path | be-tests §2: `tests_share_page.py` tests "`/s/<joke>`" | be-media/be-api-surface: `/jokes/<pk>/share/` | Route and tests use `/jokes/<pk>/share/` (`tests_share_page.py:3,79`). Typo in be-tests. |
| C14 | Appeals list path | known-gaps R-FE-8: "`/appeals/mine/`" | fe-architecture/fe-data-layer: `GET /users/me/appeals/` | `api.ts:1091` → `/users/me/appeals/`. known-gaps typo. |
| C15 | CI ever run | be-tests §8: "unverified either way" | infra-ops §4: `gh run list` shows successful runs (≈6 min) | infra-ops (live). |
| C16 | Data-export module | known-gaps R-CMP-10 cites `jokes/data_export.py` | be-compliance/be-auth: `DataExportView` in `jokes/views.py:2499` | No such file; export lives in `views.py`. |

---

## 4. Claims made without file evidence (flag, do not treat as fact)

1. **Telemetry beacon 403** (fe-data-layer #1 "HIGH", be-auth-session §12 "medium confidence"): reasoned from `dj_rest_auth/jwt_auth.py` + `sendBeacon` semantics; consistent and very likely, but never observed (no network capture, no backend test sends a cookie-only POST without `X-CSRFToken` to `/telemetry/events`). Should be the first thing the pipeline verifies.
2. known-gaps §3 items 16–24 of the "24 should-fix" list are self-declared inference.
3. known-gaps R-SEC-6 "`record_anon_read` lacks a twice-per-response guard" — not verified here.
4. be-tests §11 suite runtime "single-digit minutes" — estimate, no measurement anywhere.
5. be-billing §0 "DORMANT" runtime states (see C1) were sourced from memory notes, not live env.
6. local-dev-runbook §1.2 "showmigrations → 0 unapplied" was asserted, not run (see C5).
7. infra-ops §10 GFE `/healthz` diagnosis is well-evidenced (multiple hosts, request-log absence) but remains an inference about Google's edge.
8. ios-api-readiness §2.2 "two google `SocialApp` rows → `MultipleObjectsReturned`" — library-behaviour reasoning, untested.

---

## 5. What is still MISSING for (a) an exhaustive E2E test pipeline and (b) an iOS plan

Ranked; each is self-contained enough to hand to a follow-up read-only analyzer.

### G1 — Preferences/onboarding contract (two overlapping endpoints, silent drops, destructive `humor_types`)
Why: onboarding is the first authenticated journey; today it wipes tone preferences and persists nothing else; the ritual/today-status/personalized-daily features all read fields the SPA never sets. Neither the E2E suite nor an iOS client can be designed without a single truth table of "field → which endpoint → persisted?".

### G2 — Lookup catalogs exceed the 10/page cap (13 themes) and the FE reads page 1 only
Why: every creator-editor and Explore filter test would pass while three themes are unreachable; iOS codegen would inherit the same truncation.

### G3 — Daily ritual & gamification engines (daily joke selection, streak dual reconcile, mystery box pool, today-status, achievements never unlocked)
Why: these are the retention loop; achievements are decorative (no unlock code), anon daily joke is random per request, streak has an untested read-path reconcile. The test pipeline needs deterministic freezegun scenarios and the iOS plan needs to know which of these are real.

### G4 — Search engine semantics and the paywall/search interaction
Why: FTS `websearch` + english config, ordering fallbacks, exact-format filter, trigram unused, and the punchline-in-search-vector oracle are undocumented; Explore/Search are the main reading surfaces.

### G5 — Social-login side effects and the native-client auth matrix
Why: Google login creates a Django session + audit row (password login does not); existing-email users get 400; only the `code` mode is tested; Bearer path untested. iOS needs `access_token`/`id_token` mode, Apple sign-in, and a refresh-token-in-body path — the exact behaviour of the current code on each input must be pinned before changing it.

### G6 — Page-level reader journeys on the FE (FlowCanvasPage/Explore/Search/JokeDetail/Pack) with reveal → paywall → telemetry/reveal POST → save/react/share
Why: 13 consumers of `FlowJokeCard`, `FlowCanvasPage` untested and its feed source unknown, Playwright spec is dead; the E2E pipeline needs concrete selectors and network expectations per journey.

(Not a gap but a correction the pipeline must absorb: C1 — prod Stripe is enabled in test mode; C5 — local DB needs `migrate` before any appeals/tips/inbox E2E.)

---

## 6. Test-relevant behaviours surfaced by this audit (GIVEN / WHEN / THEN)

1. GIVEN an authenticated user with `preferred_tones` set, WHEN the SPA finishes onboarding (`PATCH /users/me/preferences/` with `humor_types` = format slugs), THEN `preferred_tones` becomes empty and `onboarding_completed` remains `false` (documents the §2.1 defect; expected to be fixed).
2. GIVEN `PATCH /users/me/preferences/` with `notification_time`/`notification_days`/`streak_saver_enabled`/`onboarding_completed`, WHEN followed by `GET /users/me/today-status/` and `GET /preferences/me/`, THEN none of those values changed (backend ignores them).
3. GIVEN the migration-seeded taxonomy, WHEN `GET /api/v1/context-tags/` is called without `page`, THEN `count` is 13 and `results` has 10 (three themes only on page 2); the creator editor's TagPicker shows 10.
4. GIVEN any user, WHEN `GET /users/me/achievements/` is called after saving/favoriting/sharing/rating/streaking past every seeded threshold, THEN every item still has `unlocked:false` (no unlock engine exists).
5. GIVEN an anonymous client, WHEN `GET /daily-jokes/today/` is called twice, THEN the two `joke.id`s may differ and the body has no `id`/`issue_label`/`delivered_at`.
6. GIVEN an authenticated user whose preferences match no joke, WHEN `GET /daily-jokes/today/`, THEN a joke is still returned (fallback to base pool); GIVEN every allowed joke is in the user's last-30-day `DailyJoke` history, THEN 404.
7. GIVEN a date with no authenticated `DailyJoke` rows (or only tier_2 rows), WHEN `run_daily_digests()` runs, THEN `skipped=True` and no digest email is logged.
8. GIVEN a free user over the daily cap, WHEN `GET /jokes/?q=<word that appears only in a locked joke's punchline>`, THEN that joke is returned with `is_locked:true` and `punchline:null` (existence oracle — decide/document).
9. GIVEN `q` is empty, WHEN `ordering=relevance`, THEN results are ordered by `-created_at`; GIVEN `joke_format=setup,oneliner`, THEN 0 results.
10. GIVEN an email/password account exists for `x@e.com`, WHEN `POST /auth/google/` completes for a Google identity with the same email, THEN 400 `non_field_errors: ["User is already registered with this e-mail address."]` and no `SocialAccount` is created.
11. GIVEN a successful `POST /auth/google/`, WHEN the response is inspected, THEN it carries a `sessionid` Set-Cookie and an `AuditLog(action='login', outcome='success')` row exists; GIVEN a successful `POST /auth/login/`, THEN neither exists.
12. GIVEN an inactive (unverified) user, WHEN `POST /auth/login/` with the correct password, THEN 400 `non_field_errors: ["Unable to log in with provided credentials."]` (never "User account is disabled.").
13. GIVEN a valid access JWT sent only as `Authorization: Bearer` (no cookies), WHEN any `IsAuthenticated` endpoint is called, THEN 200 and no CSRF check runs (currently untested in-repo).
14. GIVEN a second `POST /reports/` by the same reporter for the same joke while the first is `pending`, THEN 200 with the existing report id (not 201); GIVEN the first was `resolved`, THEN 201 creates a new one.
15. GIVEN a user who last read 3 days ago with 1 freeze, WHEN only `GET /users/me/streak/` is called (no new view), THEN `last_14_days` shows one `frozen` and one `missed` day, `current_count` is 0, and `freeze_days_available` decremented — via `_reconcile_streak`, not the signal.
16. GIVEN a `knock` draft with 3 lines, WHEN `POST /jokes/my-drafts/{id}/submit/`, THEN 400 `{"lines": ["Knock format requires at least 4 lines."]}`; GIVEN a `story` draft with 29 words, THEN 400 `{"text": ["Story must be at least 30 words."]}`.
17. GIVEN prod env (`STRIPE_SECRET_KEY=sk_test_…`), WHEN `POST /billing/checkout-session {plan_slug:'supporter'}`, THEN 422 "not yet available for purchase" (not 503); WHEN `POST /tips/checkout/` with a valid tier, THEN 200 `{checkout_url, tip_id}` pointing at `checkout.stripe.com`.
18. GIVEN `BILLING_SUCCESS_URL=…/settings/billing?checkout=success`, WHEN Stripe redirects back, THEN the SPA renders BillingPage with no success acknowledgement (documents the missing UI).
19. GIVEN the local dev DB, WHEN `showmigrations --plan` runs with `DATABASE_URL=`, THEN 8 migrations are unapplied (jokes 0034–0036, notifications 0003–0004, billing 0004, inbox 0002–0004) — E2E setup must run `migrate` first.
20. GIVEN `MediaAsset` rows exist, WHEN a staff user opens `/admin/jokes/`, THEN there is no MediaAsset changelist (quarantine/purge is only reachable through joke/report/appeal actions).

---

## 7. Verdict

The 14 reports form a strong, mostly code-grounded map: the API surface, auth/session model, media pipeline, T&S/compliance, billing/paywall, observability, deploy topology and both test suites are documented at a depth sufficient to design most of the pipeline, and the reports usually flag their own confidence. Weaknesses are concentrated in (1) three runtime-state claims that relied on memory notes instead of live evidence and were wrong — prod Stripe is enabled in test mode, the local DB is eight migrations behind, and an inactive-user login message — (2) a handful of internal engines nobody opened: daily-joke selection, search semantics, the streak read-path reconcile, and achievements (which turn out to have no unlock code at all), and (3) one real contract defect that fell between the FE and BE analyzers: the onboarding flow persists nothing and actively clears tone preferences, while the seeded 13 themes exceed the unqueryable 10-row page cap. Sixteen cross-report contradictions were resolved above; none undermines the architectural picture, but the pipeline and any iOS plan must adopt the corrected facts (especially C1, C5, C6/C7, C10) before writing expectations.
