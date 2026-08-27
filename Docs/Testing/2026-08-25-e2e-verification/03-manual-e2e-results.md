# T3 + T4 — Live API contract & in-browser E2E results (2026-08-25)

Stack under test: real Django `runserver` on **:8010** against local Postgres, real Vite SPA on **:5273** with `VITE_USE_MOCKS=false`, `VITE_USE_REAL_PREFERENCES=true`, `VITE_USE_REAL_CREATE=true`. Ports 8000/5173 were left alone (another project owns them).

Legend — **PASS** = sensible expectation held · **CONFIRMED-DEFECT** = a predicted defect was proven · **CONFIRMED-QUIRK** = surprising-but-intended behaviour proven.

---

## T3-A — Auth & session (11/11 as expected)

| ID | Expected behaviour | Result | Evidence |
|---|---|---|---|
| T3-A01 | Gated registration → 201, **no** JWT cookies, `is_active=False` | PASS | `201 {detail:"Verification code sent to your email.", email}`, `cookies_set=False`, `is_active=False` |
| T3-A02 | Under-13 DOB → 400 **and no user row** | PASS | `400 {date_of_birth:["You must be at least 13 years old to use Jokes For."]}`, `user_created=False` |
| T3-A03 | Missing / future DOB → 400 | PASS | both 400 |
| T3-A04 | Correct 6-digit code → 200 **and** sets JWT cookies | PASS | `200 {user:{id:687,…}}`, cookies set |
| T3-A05 | Code brute-force is stopped | PASS | wrong-code statuses `[400,400,400,400,400,**429**]` — locks out on the 6th |
| T3-A06 | Unverified login gives the **generic** error | PASS | `400 {non_field_errors:["Unable to log in with provided credentials."]}` — never "User account is disabled.", so no account-existence oracle. (Two analyzer reports disagreed; code wins.) |
| T3-A07 | Login sets HttpOnly cookies; `/auth/user/` resolves | PASS | access+refresh present, `HttpOnly=True`, `/auth/user/` 200 |
| T3-A09 | Logout clears cookies | PASS | logout 200, `/auth/user/` → 401 |
| T3-A10 | Cookie mutation **without** `X-CSRFToken` → 403 | PASS | `403 {detail:"CSRF Failed: CSRF token missing."}` |
| T3-A11 | `Authorization: Bearer` works with **no cookies, no CSRF** | PASS | `/auth/user/` 200; mutation reached validation (400 on payload, not 403). **Zero in-repo tests cover this path — it is the transport a native iOS app must use.** |
| T3-A13 | Anon IP throttle 100/h | PASS | fired unprompted mid-run: `{"detail":"Request was throttled. Expected available in 3298 seconds."}` |

## T3-P — Paywall, tiers, search (the monetization core: all correct)

| ID | Expected behaviour | Result | Evidence |
|---|---|---|---|
| T3-P00 | List serializer exposes `is_locked` | PASS | fields include `is_locked` |
| T3-P02 | Anonymous cookie ledger caps at 10/day | PASS | `used` sequence `1..10,10,10`; `over=true` at 12; an unread joke then returns `is_locked=true, punchline=null` |
| T3-P02b | The anon wall is deliberately **soft** | CONFIRMED-QUIRK | a fresh cookie jar gets a fresh 10. Intentional per `jokes/paywall.py` — conversion nudge, not enforcement. Real protection is the authenticated ledger. |
| T3-P03 | Free user: 10 distinct reads/day then lock | PASS | `used 0→10`, `remaining=0`, reads 1–10 `is_locked=false`, reads 11–12 `is_locked=true` |
| T3-P03b | Locked payload withholds content **server-side** | PASS | `is_locked=true`, `punchline=null`; for text-only formats `text` is nulled too, while `setup` (the teaser) is preserved — exactly as `JokeSerializer.to_representation` documents |
| T3-P04 | Re-reading an already-read joke stays free | PASS | `is_locked=false`, `used` stays 10 |
| T3-P05 | Reset at midnight **UTC** | CONFIRMED-QUIRK | `reset_at=2026-08-26T00:00:00+00:00`. Correct per spec, but for a +04 user the allowance resets at 04:00 local — mid-evening for a late reader. |
| T3-P06 | Daily joke exempt from the cap | PASS | 200 with punchline at `remaining=0` |
| T3-P07 | Subscriber is unlimited | PASS | `limit=null, remaining=null`, 0/12 locked |
| T3-P09 | Search indexes punchlines → paywalled jokes discoverable by punchline-only words | CONFIRMED-QUIRK | capped reader searching `literally` (a word only in the punchline) gets joke 481 back with `is_locked=true, punchline=null`. **No text leaks**; existence/wording is inferable. F-010. |
| T3-P10 | `ordering=relevance` with empty `q` silently falls back | CONFIRMED-QUIRK | 200, 304 results ordered by `-created_at` instead of an error |
| T3-P11 | Comma-separated format filter returns nothing | CONFIRMED-DEFECT | `?joke_format=setup,oneliner` → **0**; `?joke_format=oneliner` → **107**. F-011. |

**Paywall enforcement matrix** (capped user, jokes not read today) — verified identical for anonymous *and* authenticated:

| Path | `is_locked` | punchline |
|---|---|---|
| `GET /jokes/?page=3` | true (10/10) | absent |
| `GET /jokes/?q=…` | true | absent |
| `GET /jokes/random/` | true | absent |
| `GET /jokes/{id}/` | true | absent |

> A first probe appeared to show a bypass on the search path. Re-tested properly, it was my harness picking an **already-consumed** joke via a fallback. **No bypass exists.** Recorded because a false P0 was one assertion away.

## T3-C — FE↔BE contract (where the defects are)

| ID | Expected behaviour | Result | Evidence |
|---|---|---|---|
| T3-C01 | Lookup catalogs truncated at 10, `page_size` ignored | CONFIRMED-DEFECT | `context-tags 19→10`, `tones 12→10`, `formats 11→10`; `?page_size=100` ignored. Only `vibes` is unpaginated. F-004. |
| T3-C02 | Onboarding PATCH **wipes** `preferred_tones` | CONFIRMED-DEFECT | `tones_before=3 → tones_after=0`, HTTP **200**. F-005. |
| T3-C03 | Six onboarding fields silently dropped | CONFIRMED-DEFECT | HTTP 200; `onboarding_completed` stays `False`, `notification_time=None`. F-005. |
| T3-C04 | `today-status` reflects defaults, not the chosen ritual | CONFIRMED-DEFECT | consequence of C03 |
| T3-C05 | Telemetry via `sendBeacon` is CSRF-rejected | CONFIRMED-DEFECT | beacon path (cookies, no CSRF) → **403**; Bearer → **202 {accepted:1}**; axios+CSRF → **202**. F-006. |
| T3-C06 | Achievements can never unlock | CONFIRMED-DEFECT | 12 achievements, 0 unlocked; `grep UserAchievement.objects.create` → **no create calls anywhere**. F-007. |
| T3-C07 | Anonymous "daily" joke is random per request | CONFIRMED-QUIRK | 4 consecutive calls → ids `[265, 218, 384, 246]`. F-012. |
| T3-C08 | Authenticated daily joke is stable | PASS | ids `[489, 489, 489]` |

---

## T4 — In-browser E2E (real Chromium via Playwright)

Driven against `http://localhost:5273`. The Claude-in-Chrome extension disconnected partway through; the tier was completed with Playwright, which drives its own browser.

| ID | Journey | Result | Evidence |
|---|---|---|---|
| T4-01 | Anonymous landing + "try it" reveal | PASS | reveal shows "We'll see about that." and a "Loved it? Sign up to keep reading →" CTA; **no API call** — the teaser is static, so the landing page renders even if the API is cold |
| T4-04 | Protected route while anon | PASS | `/explore` → `/login?returnTo=%2Fexplore` |
| T4-05 | Register → verify → onboarding | PASS | 2-step gated form (identity + DOB, then pronouns/context) → `/verify-email?email=…` → typing the 6-digit code from the console email backend auto-submitted → landed on `/flow` |
| T4-06 | Onboarding 3 steps | **CONFIRMED-DEFECT** | Completed vibes → formats → ritual (07:00, Mon–Fri) → `/flow-canvas`. DB after: `onboarding_completed=False`, `preferred_tones=[]`, `preferred_contexts=[]`, `notification_time=None`, `notification_days=[]`, `notification_enabled=False`. **Only `UserVibe` saved** (`['oneliner','nerd','puns']`). F-005. |
| T4-06b | Consent banner blocks the onboarding CTA | **CONFIRMED-DEFECT** | Playwright: `<button>Accept</button> … intercepts pointer events`. Geometry at 1200×762 — banner y 695→762, Continue y 714→762; at 1440×1000 — banner y 933, Continue bottom 978. `position:fixed; z-index:9999`, `body padding-bottom: 0px`. F-003. |
| T4-07 | Today hub | PASS (with F-005 symptom) | 12 endpoints all 200 (streak, daily, tomorrow, mystery-box, packs, in-progress, taste-profile, history, top-jokesters, daily-reads, drafts, unread-count). But **"Hand-picked from your vibes" renders "We're still learning your taste"** immediately after the user picked 3 vibes. |
| T4-08 | Search | PASS | sentence-composer UI ("Show me *any kind of* jokes about *anything* that feel *any vibe*") + keyword → "4 matches" for `atoms`, cards with reactions/save/share |
| T4-10 | Free-user paywall in the UI | PASS | after capping: `daily-reads {limit:10, used:11, remaining:0, over:true}`, **10/10 feed jokes locked, zero punchlines on the wire**, page surfaces the limit + "Unlock with Supporter" |
| T4-17 | Mobile responsive @375×812 | PASS with caveats | **no horizontal scroll** (scrollWidth 375 = innerWidth 375); `nav.flow-tabbar` fixed bottom (56 px) with Today/Explore/Search/Library/Profile. **61 tap targets < 44 px** incl. reaction buttons at 28×36 and the primary "Unlock with Supporter" CTA at 40 px high — below the project's own `Docs/RESPONSIVE.md` ≥44 px standard. F-013. |
| T4-17b | Consent banner blocks mobile navigation | **CONFIRMED-DEFECT** | At 375×812 the banner (`z-index 9999`, y 670→812) fully covers `nav.flow-tabbar` (`z-index 40`, y 756→812). `elementFromPoint` on the "Today" tab returns the **"Reject"** button. A first-time mobile visitor cannot use the primary nav. F-003. |
| T4-18 | Telemetry in a real browser | **CONFIRMED-DEFECT** | Instrumented `navigator.sendBeacon`: called once with `http://localhost:8010/api/v1/telemetry/events`, `Blob{application/json}`, **returned `true`** — so `send()` returns early and the Bearer `fetch` fallback never runs. Network log: **`POST /api/v1/telemetry/events => [403] Forbidden`**. F-006. |
| T4-19 | Consent gate | PASS | with `analytics:false` **no** telemetry request is attempted at all; flipping to `analytics:true` starts the (failing) flush. The consent gate itself is correct. |
| — | Anon console noise | **NOTED** | On the public `/trending` page an anonymous visitor fires `my-drafts`, `notifications/unread-count` and `auth/token/refresh` ×3 — all 401, 6 console errors. Wasted calls against a 100/h anon IP budget. F-014. |

### Not covered in this pass
Creator authoring/media upload, moderation/appeals/takedown, billing/tips, and GDPR export/delete through the browser UI were delegated to a parallel API-level agent (results in `02b-api-contract-results.md`) rather than driven by hand. Google OAuth consent, GCS, Vision SafeSearch, Resend delivery, Stripe hosted checkout and Cloud Scheduler remain prod-only and untested here.
