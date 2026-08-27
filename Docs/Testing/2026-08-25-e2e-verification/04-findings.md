# Findings register — JokesFor verification pass, 2026-08-25

Severity: **P0** = data leak / auth or paywall bypass / launch-blocking · **P1** = a shipped user-visible feature does not work · **P2** = papercut, ops, or DX.

**Three P0s were found, all live in production. All three are now FIXED — see `05-fixes-applied.md`; suite 839/839 green.** (F-021 was found on 2026-08-26 during a second pass driving a brand-new account through the full pipeline — it is the most serious of the three.) The API-level security machinery is sound — paywall stripping, CSRF, COPPA age gate, brute-force lockout, tier gating and prod security headers were all verified correct. The P0s are elsewhere: a Django *template* that renders content the view deliberately withheld, and an account-deletion path that destroys files then fails.

| ID | Sev | Area | One line |
|---|---|---|---|
| **F-021** ✅FIXED | **P0** | Paywall / API | **The `text` field leaks the punchline of every locked two-part joke — 121/314 jokes (39%), on every API endpoint** |
| **F-000** ✅FIXED | **P0** | Paywall / share | **Share page serves the full punchline to anyone — total freemium bypass, live in prod** |
| **F-016** ✅FIXED | **P0** | GDPR / data loss | **Account deletion destroys the user's files, then 500s and keeps the account** |
| F-003 ✅FIXED | **P1** | FE / consent | Cookie banner covers the onboarding CTA and the entire mobile bottom nav |
| F-005 ✅FIXED | **P1** | Contract | Onboarding persists almost nothing, and actively wipes tone preferences |
| F-006 ✅FIXED | **P1** | Telemetry | All `sendBeacon` telemetry is rejected 403 — creator insights under-count |
| F-007 ✅FIXED | **P1** | Gamification | Achievements can never be unlocked; no code ever writes one |
| F-004 ✅FIXED | **P1** | Catalog | Taxonomy lists truncate at 10 rows with no way to page or override |
| F-011 ✅FIXED | **P1** | Search | Multi-format filter returns zero results |
| F-001 ✅FIXED | P2 | Infra | Prod `/healthz` is intercepted by the Google edge (404) |
| F-008 ✅FIXED | P2 | API | 22 endpoints are missing from the OpenAPI schema |
| F-009 | P2 | Perf | 15–19 s cold start |
| F-010 ✅ACCEPTED | P2 | Paywall | Search index exposes punchline words — **owner-accepted 2026-08-27: punchlines stay searchable** |
| F-012 ✅FIXED | P2 | Product | Anonymous "daily" joke is random per request |
| F-013 ✅FIXED | P2 | Mobile | 61 tap targets below the project's own 44 px standard |
| F-014 ✅FIXED | P2 | FE | Anonymous pages fire authenticated-only requests (401 ×6) |
| F-017 ✅FIXED | **P1** | Creator | setup/anti/knock drafts can never be submitted from the editor |
| F-018 ✅FIXED | P2 | Compliance | Admin `is_removed` tick bypasses the DSA notice + appeal right |
| F-019 ✅FIXED | P2 | Safety | SafeSearch failure looks identical to success |
| F-020 ✅FIXED | P2 | Identity | The handle chosen at registration is stored but never shown; profile synthesizes `@user<id>` |
| F-002 ✅FIXED | P2 | DX | `cairosvg` needs `DYLD_FALLBACK_LIBRARY_PATH` on macOS |
| F-015 ✅FIXED | P2 | CI | `makemigrations --check` is not a CI gate |

---

## F-021 — P0 — The paywall leaks the punchline of 39% of the catalogue through the `text` field

**Found 2026-08-26** by reading ten jokes as a brand-new account until the free cap tripped, then inspecting the payload the app actually received rather than the pixels it rendered.

**What happens.** `JokeSerializer.to_representation` strips the payoff when a joke is locked:

```python
if self._is_locked(obj):
    data['punchline'] = None
    data['lines'] = None
    fmt = getattr(obj.format, 'slug', None) if obj.format_id else None
    if fmt in TEXT_ONLY_FORMATS:      # {'oneliner', 'observ', 'story'}
        data['text'] = None
```

`text` is nulled **only for text-only formats**. But for two-part formats `Joke.text` is the backfilled `"<setup> <punchline>"` — so for every other format the punchline survives in `text` while `punchline` is dutifully set to `null`.

**Observed live**, as a capped free user on `/jokes/475/`:

```json
{ "is_locked": true,
  "punchline": null,
  "setup": "Why did the coffee file a police report?",
  "text": "Why did the coffee file a police report? It got mugged." }
```

Sampled 12 locked jokes across formats:

| Format | Locked sampled | Leaking |
|---|---|---|
| `oneliner` | 4 | 0 ✅ |
| `observ` | 3 | 0 ✅ |
| `story` | 3 | 0 ✅ |
| `setup` | 1 | **1** ❌ |
| `anti` | 1 | **1** ❌ |

Catalogue-wide: `TEXT_ONLY_FORMATS = {observ, story, oneliner}`; **121 of 314 live jokes (39%)** are non-text-only with a punchline, and **all 121** have `.text` containing that punchline — `setup-punchline` (64), `setup` (52), `short-story` (3), `anti` (2).

**Why the UI hid it.** The joke page renders from the `setup` and `punchline` fields, so a locked joke correctly shows `████ ███████ ██ ████` and "You've hit your free daily jokes." The leak is invisible on screen and total in the payload — anyone with DevTools, `curl`, or a scripted client reads every punchline for free, on **every** endpoint that serves jokes (list, search, detail, random, trending). This is the freemium model, defeated.

This is the **same root cause as F-000**: the backfilled `text` field carries the payoff, and code that strips `punchline` forgets `text`. Two independent places make the same mistake.

**Additional subtlety:** the catalogue contains both `story` **and** `short-story` slugs. Only `story` is in `TEXT_ONLY_FORMATS` (which is derived from `FORMAT_RULES` where `required == ['text']`), so the 3 `short-story` jokes leak as well. Any fix keyed on a format allow-list will keep having this class of bug.

**Fix.** Do not decide by format. When a joke is locked, strip the payoff unconditionally — null `punchline` and `lines`, and replace `text` with the teaser the serving layer already knows how to compute (`setup` when present, else nothing), rather than nulling it only for three slugs:

```python
if self._is_locked(obj):
    data['punchline'] = None
    data['lines'] = None
    data['text'] = None          # never ship the backfilled "setup punchline"
```

(The client already renders the teaser from `setup`; text-only formats already receive `text: None` today and render the lock state correctly, so this is behaviour-preserving for them.)

Then add a test that, for **every** format in `FORMAT_RULES`, locks a joke and asserts its punchline string appears nowhere in `json.dumps(response.data)` — not merely that `response.data['punchline'] is None`. The existing tests pass because they assert the latter.

---

## F-000 — P0 — The public share page serves the full punchline to anyone (freemium bypass, LIVE IN PRODUCTION)

**What happens.** `joke_share_page` (`jokes/views.py`) is careful: it builds a punchline-free teaser and comments *"NEVER the punchline -- this page advertises the joke, it must not spoil it."* That teaser correctly feeds `og:description`, `twitter:description` and the JSON-LD. But the page body then renders the raw field:

```html
<!-- jokes/templates/jokes/share.html:99 -->
<p class="joke-text">{{ joke.text }}</p>
```

For every two-part format (`setup`, `anti`, `knock`), `Joke.text` is the backfilled `"<setup> <punchline>"`. Measured on the local catalogue: **118 of 118** such jokes have `.text` containing the full punchline.

The view applies only the *content-tier* gate. It never consults `paywall_state`. So the share page is outside the paywall entirely.

**Proven on production**, anonymous, no cookies, no auth:

```
GET https://jokesforbackend-332865216810.us-east1.run.app/jokes/93/share/   → 200

<meta property="og:description" content="Why don&#x27;t scientists trust atoms anymore?">      ← correctly punchline-free
<p class="joke-text">Why don&#x27;t scientists trust atoms anymore? Because they make up everything.</p>   ← FULL PUNCHLINE
```

Reproduced identically on joke 169.

**Why it matters.** This defeats the entire freemium model that the paywall work was built to enforce. Joke ids are sequential and the endpoint needs no auth, no cookie and no ledger — the whole catalogue is scriptable with a `for` loop. Every other serving path (list, search, random, detail, for anonymous *and* authenticated capped users) was verified to strip the punchline correctly; this one route bypasses all of it. It also spoils the joke in the HTML that a human briefly receives before the meta-refresh fires.

Note this is the *same class* of bug as the JSON-LD punchline leak fixed in `04e1b2f` — fixed in the metadata, missed in the body.

**Fix (one line).** The view already computes a safe, punchline-free `description`. Render that instead:

```diff
- <p class="joke-text">{{ joke.text }}</p>
+ <p class="joke-text">{{ description }}</p>
```

Then add a regression test that fetches `/jokes/<id>/share/` for a setup-format joke as an anonymous client and asserts the punchline string is absent from the whole response body — not just from the meta tags, which is what the existing test checks.

---

## F-016 — P0 — Account deletion destroys the user's files, then fails and keeps the account

**What happens.** `DELETE /api/v1/users/me/` raises a 500 for any user who has ever generated an audit row:

```
django.db.utils.InternalError: pgtrigger: Cannot update or delete rows from audit_auditlog table
```

Root cause: `AuditLog.actor` is `on_delete=SET_NULL`, so `user.delete()` issues an **UPDATE** against `audit_auditlog` — and `audit/models.py` installs `pgtrigger.Protect(operation=Update | Delete, name='append_only')`, which blocks exactly that. `audit/signals.on_user_logged_in` writes a row on login.

Controlled experiment (`/tmp/gdpr.py`, both users otherwise identical):

```
no_audit_row     audit_row=False -> DELETED OK
with_audit_row   audit_row=True  -> InternalError: pgtrigger: Cannot update or delete rows...
```

**The destructive part.** Inside `UserAccountDeleteView.delete`'s `transaction.atomic()` block the order is:

1. blacklist refresh tokens
2. **delete the user's uploaded media from the storage backend**
3. **delete the avatar file from the storage backend**
4. purge email records
5. remove media-format jokes
6. `user.delete()`  ← raises here

Steps 2 and 3 touch object storage, which is **not transactional**. The database rolls back, so the account, profile and all rows survive — but the files are already irreversibly gone.

**Net effect:** a user exercising GDPR Article 17 erasure gets an HTTP 500, keeps their account and all their personal data, and permanently loses their uploaded media. That is the worst of both outcomes, and it is a compliance failure on a product whose own Compliance Addendum makes GDPR/DSA obligations explicit.

**Fix.**
1. Anonymise the audit rows *inside* the atomic block before `user.delete()`, wrapping the write in `pgtrigger.ignore('audit.AuditLog:append_only')` — `actor_email_hash` already exists precisely so rows stay correlatable with `actor=NULL`.
2. Move every storage deletion to `transaction.on_commit(...)` so files are only destroyed once the DB delete has actually succeeded.
3. Add a test that creates a user **with** an audit row and asserts `DELETE /users/me/` returns 204 — the current tests pass only because their fixtures never produce one.

---

## F-003 — P1 — The cookie consent banner blocks the onboarding CTA and the whole mobile navigation

**What happens.** The consent banner is `position: fixed` at the bottom with `z-index: 9999`, and the page reserves no bottom offset (`body { padding-bottom: 0px }`). It therefore sits on top of whatever is at the bottom of the viewport.

Two proven consequences:
1. **Desktop** — onboarding step 1's "Continue" button is enabled but unclickable. At 1200×762 the banner spans y 695→762 and the button y 714→762; at 1440×1000, banner y 933 vs button bottom 978. So this is *not* a short-viewport edge case. `document.elementFromPoint()` at the button's centre returns the banner's **Accept** button; Playwright refuses the click with `<button>Accept</button> … intercepts pointer events`.
2. **Mobile (375×812)** — the banner (y 670→812) completely covers `nav.flow-tabbar` (`z-index: 40`, y 756→812). `elementFromPoint` on the "Today" tab returns **"Reject"**. A first-time mobile visitor cannot press any primary navigation tab.

**Why it matters.** Both sit directly on the activation path, and they hit *only* new users — exactly the cohort that has not yet dismissed the banner, and the cohort the accelerator traction story depends on. It is invisible to every existing test: jsdom has no layout, so vitest cannot see an overlap, and there is no E2E tier.

**Repro.** Clear `localStorage['jokesfor-consent']`, register a new account, reach `/flow`, try to press Continue. Or at 375 px wide, load `/flow-canvas` and try the bottom tabs.

**Fix.** Reserve space while the banner is visible — e.g. set a `--consent-height` custom property on `<body>` when it mounts and add it to the bottom padding of the app shell and to `nav.flow-tabbar`'s `bottom`. Also raise the tab bar above the banner or dock the banner above it. Files: the consent banner component in `src/features/consent/`, and `nav.flow-tabbar` in the FlowAppShell styles.

---

## F-005 — P1 — Onboarding persists almost nothing and destroys existing tone preferences

**What happens.** `PATCH /users/me/preferences/` (`UserPreferencesView._update`, `jokes/views.py:2115-2148`) handles only `humor_types`, `notifications`, `privacy`, `theme`. The SPA's onboarding sends nine fields. Result, proven twice — once by direct API probe and once by completing the real 3-step flow in a browser:

| What the user chose | Stored |
|---|---|
| 3 vibes (Puns, Nerd, One-liners) | ✅ `UserVibe` rows via `PUT /users/me/vibes/` |
| Formats (`humor_types` = format slugs) | ❌ — and **`preferred_tones` is wiped to `[]`**, because `Tone.objects.filter(slug__in=<format slugs>)` matches nothing and the result is `.set()` |
| Ritual time 07:00 | ❌ `notification_time = None` |
| Ritual days Mon–Fri | ❌ `notification_days = []` |
| Notifications on | ❌ `notification_enabled = False` |
| Completion | ❌ `onboarding_completed = False` |

Every one of those returned **HTTP 200**.

**The deeper problem.** The one thing that *does* save is never read. `UserVibe` appears only in `models.py`, `admin.py`, `serializers.py`, and its own CRUD view — **no serving or recommendation path reads it**. Meanwhile `get_personalized_joke` (`jokes/recommendations.py:65-75`) filters on `preferred_tones`, `preferred_contexts`, `preferred_age_rating`, `preferred_language` — all four left empty (and one actively cleared) by onboarding.

**Net effect: the entire onboarding flow has zero influence on what any user is served.** The vibes screen promises "We'll tune your daily joke around these." The Today hub then renders "We're still learning your taste — read and save a few jokes and picks will show up here" to a user who just answered three screens of taste questions. `onboarding_completed` never flipping also means the flow can re-trigger.

**Why it matters.** This is the retention loop. Personalization is the product's core promise and it is currently inert — and silently so, which is why 1,632 passing tests never caught it: the frontend tests assert against a mock that accepts the fields, and the backend tests assert against the fields the backend actually supports. Nobody tested the seam.

**Fix (three parts, in order).**
1. Stop the destruction: in `_update`, do not `.set()` `preferred_tones` from `humor_types`. Formats are not tones — either map format slugs to `Format` and store them in the right field, or drop the key.
2. Persist the rest: extend `_update` (or point the SPA at the already-existing `PATCH /preferences/me/` + `POST /preferences/complete-onboarding/`, which `api.ts:516` defines but never calls) to accept `tones`, `languages`, `notification_*`, `streak_saver_enabled`, `onboarding_completed`.
3. Make it matter: either have `get_personalized_joke` read `UserVibe`, or translate the chosen vibes into `preferred_tones`/`preferred_contexts` on save. Until step 3, steps 1–2 only stop the bleeding.
4. Reject unknown keys instead of ignoring them, so the next contract drift fails loudly.

---

## F-006 — P1 — All beacon telemetry is rejected (403), so creator insights under-count

**What happens.** `src/lib/telemetry.ts` `send()` tries `navigator.sendBeacon` **first and unconditionally** (despite the comment saying "prefer sendBeacon on page-hide paths"), and returns early when it queues. `sendBeacon` cannot set `Authorization` or `X-CSRFToken`, but does send cookies — which routes the request onto the cookie-auth path, where CSRF is enforced.

Proven at three levels:
- **Code** — the early `return` means the Bearer `fetch` fallback is unreachable whenever `sendBeacon` exists (i.e. every modern browser).
- **Server** — cookies without CSRF → `403 {"detail":"CSRF Failed: CSRF token missing."}`; Bearer → `202 {"accepted":1}`; axios+CSRF → `202`.
- **Real browser** — instrumented beacon returned **`true`**, network log shows `POST /api/v1/telemetry/events => [403] Forbidden`.

This applies in **production**, not just locally: the prod CORS preflight for `content-type` alone returns 200 with `allow-credentials: true`, so the beacon's preflight passes and the POST proceeds — straight into the 403.

**Why it matters.** Impressions, reveals, dwell, and watch feed `creator_insights` — reach, `payoff_rate`, dwell, scroll depth. Those are the numbers shown to creators and quoted in the business docs. They are currently built on whatever fraction of events happens not to go through the beacon.

**Fix.** In `send()`, either (a) attach the access token as a query-free credential the beacon can carry — simplest is to **stop preferring the beacon** and use `fetch(..., {keepalive: true})` with the `Authorization` header, which survives unload just as well for payloads under 64 KB; or (b) exempt `TelemetryIngestView` from CSRF and rely on the JWT cookie, accepting the (low, fire-and-forget) CSRF risk on an append-only endpoint. Option (a) is safer and is a ~5-line change. Add a backend test that POSTs with a cookie and **no** CSRF header and asserts the intended outcome.

---

## F-007 — P1 — Achievements can never be unlocked

**What happens.** 12 `Achievement` rows are seeded and `/users/me/achievements/` renders them, but `grep -rn "UserAchievement.objects.create"` across the codebase returns **nothing**. No signal, view, or command ever awards one. `criteria_type` / `criteria_value` are decorative. Verified live: a user past several seeded thresholds still shows `unlocked: 0/12`.

**Why it matters.** A visible, shipped gamification surface that is permanently empty — it can only ever discourage. Staff would have to insert rows by hand in Django admin.

**Fix.** Either implement awarding (a `post_save` evaluator on the relevant counters, or a request-triggered check on profile load — consistent with the project's no-workers constraint), or hide the surface until it is implemented. Do not leave it visible and inert.

---

## F-004 — P1 — Taxonomy catalogs silently truncate at 10 rows

**What happens.** Lookup viewsets inherit `PAGE_SIZE=10` with no `page_size_query_param`. Measured live: `context-tags` **19 → 10**, `tones` **12 → 10**, `formats` **11 → 10**. `?page_size=100` is ignored. The SPA (`src/features/create/api.ts:18-24`) fetches page 1 only. `VibeViewSet` is the sole lookup with `pagination_class = None`.

**Why it matters.** Nine taxonomy rows are unreachable in the UI — creators cannot tag with them, and readers cannot filter by them. Content tagged with a hidden theme is undiscoverable by that axis. It looks like a working feature, which is why nobody noticed.

**Fix.** Set `pagination_class = None` on the lookup viewsets (matching `VibeViewSet`) — these are small, bounded reference tables. Add a test asserting `len(results) == Model.objects.count()` for each so re-adding pagination fails loudly.

---

## F-011 — P1 — Multi-select format filter returns nothing

**What happens.** `?joke_format=setup,oneliner` → **0 results**; `?joke_format=oneliner` → **107**. The filter is an exact match on a single slug, with no comma splitting (`jokes/managers.py`). Tone/context/culture filters *do* use `__in`; format does not.

**Fix.** Split on comma and use `format__slug__in`, matching the sibling filters. One-line change plus a test.

---

## F-001 — P2 — Prod `/healthz` never reaches Django

`GET /healthz` on the public Cloud Run URL returns a **Google-edge HTML 404** (`content-type: text/html; charset=UTF-8`, none of Django's security headers), while `/healthzz`, `/Healthz` and `/healthz/` return *Django* 404s and `/readyz` returns 200 with full headers. Locally the same route returns `{"status":"ok"}` — **so the code is correct and the edge is intercepting the exact reserved path**.

Impact: any external uptime check pointed at `/healthz` is dead. Container-level probes bypass the edge and are unaffected. **Fix:** expose an alias (e.g. `/livez`) alongside `healthz` in `JokesForProject/urls.py`, and repoint monitoring/docs.

## F-008 — P2 — 22 endpoints are missing from the OpenAPI schema

`check --deploy` emits 22 × `drf_spectacular.W002 "unable to guess serializer … Ignoring view for now"` — including `MediaUploadView`, `JokeRevealView`, `UserPreferencesView`, `UserVibesView`, `UserAchievementsView`, `UserAccountDeleteView`, `StreakFreezeView`, `JokeDraftSubmitView`, `VerifyEmailView`, `ResendVerificationView`, `EmailUnsubscribeView`, `csrf_token_view`. They are silently **omitted from `/api/schema/`**.

Harmless for the hand-written SPA client. **Blocking for the iOS plan**, where the schema is the natural source for generated Swift models — a generated client would simply lack these calls. **Fix:** add `serializer_class` or `@extend_schema(request=…, responses=…)` to each. This is the single highest-leverage prerequisite for iOS.

## F-009 — P2 — 15–19 s cold start

`/readyz` cold: **15.2 s** (measured again at 19.0 s earlier), of which the DB ping alone is 768 ms and cache 161 ms — the remainder is container start plus Django/Neon warm-up. First `/api/v1/jokes/` hit ≈ 4.6 s. A first-time visitor arriving on a scaled-to-zero instance waits that long. Mitigations: Cloud Run **min-instances = 1**, and/or a cheap keep-warm ping. Worth doing before any traction push.

## F-010 — P2 — Search index exposes punchline wording — ACCEPTED, NOT A DEFECT

> **Owner decision, 2026-08-27: punchlines stay in the search index.** This is a
> deliberate product choice, not an outstanding finding. Do not "fix" it later
> without re-weighing the recall cost below.

`search_vector` covers `text, setup, punchline`. A capped reader searching a word that occurs **only** in a locked joke's punchline gets that joke back (`is_locked: true`, `punchline: null`). No text leaks, but wording is inferable by guess-and-check. **Decide and document:** either drop `punchline` from the search vector (costs recall) or accept it explicitly.

## F-012 — P2 — The anonymous "daily" joke is not daily

`GET /daily-jokes/today/` for anonymous callers is `order_by('?')` per request: four consecutive calls returned ids `[265, 218, 384, 246]`. Authenticated users correctly get a stable per-day pick (`[489, 489, 489]`). A shared "joke of the day" link shows a different joke to every logged-out visitor, and the shared-moment framing in the marketing copy does not hold. **Fix:** seed the anonymous pick deterministically from the date (e.g. index by `date.toordinal() % count`, or reuse `get_daily_editorial_joke`).

## F-013 — P2 — 61 tap targets below the project's own 44 px standard

At 375×812: 61 interactive elements are under 44 px in a dimension — reaction buttons at **28×36**, the primary "Unlock with Supporter" CTA at **40 px** high. `Docs/RESPONSIVE.md` sets ≥44 px. (WCAG 2.2 AA's 24×24 minimum is met; Apple's HIG 44 pt is not — which matters directly for the iOS port.)

## F-014 — P2 — Anonymous pages fire authenticated-only requests

On the public `/trending` page an anonymous visitor triggers `GET /jokes/my-drafts/`, `GET /notifications/unread-count/` and `POST /auth/token/refresh/` ×3 — six 401s and six console errors. Wasteful against the 100 req/h anonymous IP throttle (~16 page views before a visitor is throttled) and it makes the console useless for spotting real errors. **Fix:** gate those queries on `enabled: isAuthenticated`.

## F-017 — P1 — Setup / anti / knock drafts can never be submitted from the creator editor

**Confirmed end-to-end through the real UI on 2026-08-26** with a brand-new account: picked "Setup → Punchline", typed a setup and a punchline, and watched it fail.

The exact sequence, captured live on draft 108:

```
PATCH /api/v1/jokes/my-drafts/108/   {setup, punchline}          -> 200 OK
   response shows the server's backfill:
   "text": "Why did the QA engineer walk into a bar? To order a beer, 0 beers, 999999 beers, and a lizard."

POST  /api/v1/jokes/my-drafts/108/submit/                        -> 400
   {"text": "Not allowed for setup format."}
```

So the server **backfills `text` on save, then rejects the draft on submit because `text` is populated** — for a format whose `FORMAT_RULES` entry forbids `text`. The draft is permanently unsubmittable, and the failure is entirely self-inflicted: the user supplied only the two fields the format requires.

The alternate path `POST /jokes/submit/` returns 201 because validation runs *before* the backfill. **The SPA uses the broken path** (`src/features/create/api.ts`).

Additionally, the editor surfaced **"Save failed · retry"** during autosave — its own `PATCH` returned 400 (a minimal `{setup, punchline}` PATCH returns 200, so the editor sends at least one extra field the API rejects). The draft body was still empty (`setup: ""`, `punchline: ""`) server-side until the minimal PATCH was replayed by hand.

**Why it matters.** Three of the nine formats — including `setup → punchline`, the flagship two-beat format and 116 of the 314 jokes in the catalogue — cannot be published through the creator UI at all. Existing tests miss it because they construct submissions through the ORM rather than driving the autosave→submit sequence the editor actually performs.

**Shared root cause with F-021.** The same "backfill `text` from setup+punchline" decision causes both this P1 *and* the P0 paywall leak: the backfilled field is rejected by the submit validator and simultaneously ships the punchline past the paywall. Fixing the backfill strategy addresses both — derive `text` only at publish time (or never, and let serializers compose it), rather than storing a denormalized copy that other code forgets about.

**Fix.** Stop persisting a backfilled `text` for formats that forbid it; derive it at publish. Add a test that drives PATCH-then-submit exactly as the editor does, for every format in `FORMAT_RULES`.

## F-018 — P2 — `is_removed` in Django admin is a DSA-notice bypass

Ticking `is_removed` directly in `JokeAdmin` hides the joke with **no statement-of-reasons notification, no media quarantine and no share-card blanking**, and leaves `removed_at` NULL — so the creator's later appeal is refused with *"This removal is not eligible for appeal."* A moderator taking the obvious admin action silently strips the user's DSA appeal right. **Fix:** make `is_removed` read-only in the admin form and route removals through the existing takedown action.

## F-019 — P2 — SafeSearch failure is indistinguishable from success

`{"status":"skipped"}` (screening disabled) and `{"status":"error"}` (Vision unreachable) are both non-blocking and look identical to a healthy pass from outside. Fail-open is a defensible availability choice for an NSFW/CSAM gate, but it must be *observable*. **Fix:** emit a metric/log-based alarm on `status=error` so a silently broken Vision integration surfaces.

## F-020 — P2 — The handle chosen at registration never becomes the public handle

Registering as "Pipeline Tester" / "@pipetest26" stores both correctly — `auth_user.first_name = 'Pipeline Tester'`, `auth_user.username = 'pipetest26'` — and `GET /users/me/profile/` returns `name: "Pipeline Tester"` ✅. But it returns **`username: "@user715"`**, synthesized from the user id, because `UserProfile.handle` is `null`; the registration flow writes to `auth_user.username`, while the profile serializer reads `UserProfile.handle`.

So a new user picks a handle, the app accepts it, and then shows them a different one until they set it again under Settings → public identity. Two parallel identity stores (`auth_user.first_name/username` vs `UserProfile.display_name/handle`) with the write and the read on opposite sides. **Fix:** have the post-verification patch populate `UserProfile.handle`/`display_name`, or have the profile serializer fall back to `auth_user.username` before synthesizing `@user<id>`.

## F-002 — P2 — `cairosvg` needs a DYLD path on macOS

`import cairosvg` fails on macOS unless `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` is set, even with Homebrew cairo 1.18.4 installed. CI installs `libcairo2` so it is green there. **Fix:** one line in the local dev runbook.

## F-015 — P2 — `makemigrations --check` is not a CI gate

It passes today ("No changes detected"), but it is not in `.github/workflows/ci.yml`. Since `cloudbuild.yaml` runs `migrate` before deploying, undetected model drift would ship a schema that does not match the code. **Fix:** add one step to the CI job.

---

## What was verified as *correct* (worth stating)

- **Paywall (lock state and `punchline` field)**: `is_locked` resolves correctly on every serving path (list, search, random, detail) for both anonymous and authenticated capped users; teaser preserved, payoff withheld; re-reads free; daily joke exempt; subscriber unlimited; midnight-UTC reset.
- **Auth**: COPPA age gate with no orphan row, generic unverified-login error (no account oracle), 6-digit code lockout at 5 attempts, HttpOnly cookies, CSRF enforced on the cookie path and correctly bypassed on the Bearer path, throttles live.
- **SEO metadata**: OG/Twitter/JSON-LD per joke, bot/human dual-mode share page, sitemap and robots.txt in agreement, no punchline leak *into the meta tags* (the body is F-000).
- **Moderation**: reversible takedown with media quarantined to `quarantine/<uuid>/<random-token>/` and the public path genuinely removed from storage; appeal window / duplicate / ownership matrix correct (404 not 403 for a foreign joke); symmetric blocks; tier derivation at publish; all media limits match source exactly.
- **Billing**: cleanly dormant with blank keys — 503 `billing_unavailable`, webhook 200 `billing_dormant` no-op, and 400 `Invalid signature.` on a bad signature.
- **Prod hardening**: HSTS with preload, nosniff, frame-deny, referrer policy, COOP; CORS scoped to the SPA origin with credentials.
- **Suites**: 834 backend tests in 111 s with **zero skips** (ffmpeg and cairo paths really ran), 798 frontend tests in 12 s, ruff clean, no model drift, bandit 0 High.
