# JokesFor for iOS — development plan

**Date:** 2026-08-25 · **Status:** design, awaiting approval · **Author:** planning pass
**Companion:** `Docs/Testing/2026-08-25-e2e-verification/` (the verification pass this plan is grounded in)

> Every claim about the backend below was **verified live** against a running stack during this pass, not read from docs. Where a claim is an inference or a decision for the owner, it says so.

---

## 1. What we are building, and why the shape matters

JokesFor is a daily-ritual reading product: one joke a day, a streak, a 10-reads-a-day free tier, and a creator side. That is an unusually good fit for a phone — the ritual *wants* a push notification and a home-screen icon, and the web app cannot have either. The existing React SPA is already responsive (verified: no horizontal scroll at 375 px, working bottom tab bar), so the iOS app is not about reach — it is about **the ritual loop**: notify → open → read → streak.

That framing drives scope. The v1 app should be **excellent at reading and the daily ritual**, and deliberately thin everywhere else.

---

## 2. What the backend already gives us (verified, not assumed)

| Capability | Status | Evidence from this pass |
|---|---|---|
| `Authorization: Bearer <access>` on every endpoint | ✅ Works | `/auth/user/` → 200 with no cookies at all; a mutation reached validation rather than 403 |
| CSRF does **not** apply to the Bearer path | ✅ Works | cookie mutation without `X-CSRFToken` → 403; identical call with Bearer → accepted |
| Full REST surface | ✅ ~180 endpoints | feed, search, detail, daily, streak, mystery box, packs, collections, favorites, follows, inbox, creator drafts/insights, billing, tips |
| Server-side paywall | ✅ Correct | verified across list / search / random / detail for anon and authed; punchline never on the wire when locked |
| Age gate / COPPA | ✅ Correct | under-13 → 400 with no user row created |
| Email verification | ✅ Correct | 6-digit code, lockout at 5 attempts (429 on the 6th) |
| Throttling | ✅ Live | anon 100/h per IP, authed 1000/h |
| Security headers, HSTS, CORS | ✅ Correct in prod | verified on the live service |

**The API is genuinely ready to be consumed by a native client.** That is the single most important input to this plan — there is no rewrite required, only a well-scoped set of additions.

---

## 3. The gaps that block a shippable App Store build

These are ordered by how much they block. Items 1–4 are hard blockers; nothing ships without them.

### 3.1 Native token lifecycle — **the #1 blocker** (verified)

`JWT_AUTH_HTTPONLY=True` blanks the refresh token in response bodies. Measured with a cookie-less client:

| Call | Body returned |
|---|---|
| `POST /auth/login/` | `{access: "<233 chars>", refresh: "", user: {...}}` — real refresh token **only** in `Set-Cookie` |
| `POST /auth/token/refresh/` | `{access, access_expiration}` — **no `refresh` key at all**; the rotated token is only in `Set-Cookie` |
| replay the old refresh token | `401 {"detail": "Token is blacklisted"}` |

With `ROTATE_REFRESH_TOKENS=True` + `BLACKLIST_AFTER_ROTATION=True`, a client that ignores cookies gets **exactly one refresh and is then locked out**.

*Important nuance:* `URLSession` persists cookies through `HTTPCookieStorage` by default, so a naive app would work **by accident**. That is a bad foundation — it breaks under `ephemeralSessionConfiguration`, it silently mixes the CSRF-bearing cookie transport with the Bearer transport, and it makes Keychain-backed token storage impossible.

**Recommended fix:** dedicated native auth views built directly on simplejwt — `POST /api/v1/auth/native/login`, `/native/refresh`, `/native/logout` — returning `{access, refresh, access_expiration, refresh_expiration, user}` in the body and setting **no cookies**. Also enable `JWT_AUTH_RETURN_EXPIRATION=True` (harmless for web). This keeps the browser's XSS hardening completely intact, which flipping `JWT_AUTH_HTTPONLY=False` globally would not.

Also needed on the native path: `verify-email` must return tokens (today it returns cookies only, so a native client finishes signup with no credentials and has to log in again with the password).

### 3.2 Sign in with Apple — **App Store requirement**

App Review Guideline 4.8: an app offering a third-party social login (we offer Google) **must** also offer Sign in with Apple. It does not exist today. Work: enable `allauth.socialaccount.providers.apple`, add an `AppleLogin(SocialLoginView)` accepting the `ASAuthorizationAppleIDCredential` identity token, configure the Apple `SocialApp` (team id, key id, .p8 private key, bundle-id client ids), handle **private-relay emails**, and reuse the existing DOB age gate.

### 3.3 Payments must go through Apple IAP

- **Subscriptions** (the unlimited-reads tier) are digital content consumed in-app → **IAP is mandatory**, 15–30% commission. The current Stripe Checkout flow cannot be used on iOS. Work: StoreKit 2 products, server-side JWS receipt validation, an App Store Server Notifications V2 endpoint, and `Subscription` rows with an `apple` provider that `effective_plan()` honours.
- **Tips** sit on a genuine exception. Apple permits person-to-person monetary gifts without IAP **only if the gift is optional and 100% of the funds reach the recipient**. → **Decision needed: does JokesFor take a platform fee on tips?** If yes, tips must use IAP (or be hidden on iOS). If no, the existing Stripe flow may stay. This materially changes tip economics and needs the owner's answer before Milestone 4.

### 3.4 OpenAPI schema is not codegen-ready

Verified: **22 views emit `drf_spectacular.W002` and are silently omitted from `/api/schema/`** — including `MediaUploadView`, `JokeRevealView`, `UserPreferencesView`, `UserVibesView`, `UserAchievementsView`, `UserAccountDeleteView`, `StreakFreezeView`, `VerifyEmailView`. A generated Swift client would simply lack those calls. Fix by adding `serializer_class` / `@extend_schema` to each (finding F-008). This is the highest-leverage prerequisite: it converts "hand-write ~180 endpoint bindings" into "generate them".

### 3.5 Push notifications do not exist

There is no device-token model of any kind. The daily ritual is the entire reason to build this app, and it needs APNs. Work: a `DeviceToken` model (`user, platform, token, last_seen`), `POST`/`DELETE /users/me/devices/`, and **request-triggered** APNs sends. This must respect the project's standing constraint — single Cloud Run service, no Celery, no workers, no cron — so sends piggyback on existing request paths, and the daily push uses the same Cloud Scheduler → token-guarded internal endpoint pattern the email digest already uses (`/internal/run-digests/`).

> Blocked by F-005: the notification time and days the user picks in onboarding are currently **dropped on the floor** (`notification_time=None`, `notification_days=[]`). A daily push has nothing to schedule against until that is fixed. **The iOS ritual depends on a web bug being fixed first.**

### 3.6 Smaller but required

- **Universal links** — serve `/.well-known/apple-app-site-association`, claim `/jokes/*`, `/creators/*`, `/packs/*`, `/reset-password`. Share links currently point at the web app; without this, sharing from the app leaves the app.
- **Anonymous paywall** — the free-read ledger for logged-out readers is a signed **cookie** (`jf_anon_reads`). On iOS, either send a device-scoped opaque id header, or require sign-in before reading. Recommend: **require sign-in on iOS** (simpler, and the App Store dislikes anonymous paywalls less than it dislikes broken ones).
- **Rate limits** — mobile users behind carrier NAT share the 100/h anonymous IP bucket. Emit `X-RateLimit-*` headers and exempt lookup endpoints.
- **HEIC** — iPhone photos are HEIC by default; the upload pipeline should accept it or the client must transcode.
- **Tap targets** — 61 controls are under 44 pt (F-013). Apple's HIG requires 44 pt; these are being re-implemented natively anyway, but the same design tokens should be corrected.

---

## 4. Approach — three options

**Option A — Native SwiftUI app against the existing REST API. ✅ Recommended.**
A real iOS app: SwiftUI, `URLSession`, Keychain, StoreKit 2, APNs, widgets, offline cache. Highest quality ritual loop and the only option that gets a Lock Screen widget and a proper daily push. Cost: a second client to maintain, and every new feature ships twice.

**Option B — Wrap the existing SPA in a WKWebView shell.**
Fastest to the store (~2 weeks) and one codebase. But: Guideline 4.2 rejects thin web wrappers; IAP still has to be bridged natively; no widget; the cold-start problem (15–19 s, F-009) becomes the app's launch experience. Rejected as a primary strategy.

**Option C — React Native / Expo.**
Shares TypeScript and the existing data-layer knowledge; one codebase for a future Android build. But the team's existing asset is a *web* app, not a React Native one — the component layer does not transfer (Tailwind, DOM, react-router all have to be replaced), so the reuse is smaller than it looks. Worth revisiting **only if Android is a near-term requirement.**

**Recommendation: Option A.** The product's differentiator on mobile is the ritual (push + widget + streak), and that is exactly what the native path does well and the wrapper path cannot do at all. Revisit C if Android moves into scope within 6 months.

---

## 5. Proposed architecture

```
JokesFor.app  (SwiftUI, iOS 17+)
├── Core
│   ├── APIClient           async/await URLSession; Bearer injection; 401 → single-flight refresh → retry
│   ├── TokenStore          Keychain (kSecAttrAccessibleAfterFirstUnlock); access + refresh + expiry
│   ├── Generated/          Swift models generated from /api/schema/ (after F-008 is fixed)
│   └── Telemetry           batched; explicit consent gate; NOT the web's broken beacon path
├── Features                one folder per surface, each a SwiftUI view + @Observable model
│   ├── Today               daily joke, streak, mystery box  ← the reason the app exists
│   ├── Reader              feed / search / detail / reveal / paywall
│   ├── Library             favorites, collections, saved
│   ├── Creator             (v2) drafts, editor, insights
│   ├── Account             settings, preferences, subscription, GDPR export/delete
│   └── Paywall             StoreKit 2 products + purchase + restore
└── Extensions
    ├── WidgetKit           Home + Lock Screen: today's joke, streak count
    └── NotificationService  rich daily push
```

**Deliberate choices**
- **iOS 17+** — buys `@Observable`, SwiftData, and modern StoreKit 2 with no back-compat tax. Covers ~90% of active devices by ship date.
- **No third-party networking dependency.** `URLSession` with `async/await` is sufficient for a REST API this conventional; every dependency is an App Store privacy-manifest liability.
- **Generated models, hand-written endpoints.** Generate the DTOs from the OpenAPI schema (once F-008 lands) so model drift is caught at compile time, but keep the ~40 endpoint calls the app actually uses hand-written and readable.
- **Offline-first for the daily joke only.** Cache today's joke and the streak so the widget and a cold launch on the subway both work. Do not attempt a general offline feed — the paywall is server-authoritative by design and must stay that way.
- **The paywall is never enforced client-side.** The server already strips the punchline; the app renders `is_locked` and must never rely on hiding a value it received.

---

## 6. Scope — what ships in v1

**In:** onboarding (age gate + vibes), Sign in with Apple + Google + email, daily joke + streak + mystery box, feed / search / detail / reveal, the 10-a-day paywall with an IAP upgrade, favorites + collections, creator profiles + follow, notifications inbox, settings incl. GDPR export/delete, daily push, Home + Lock Screen widget, universal links.

**Out (v2):** the creator authoring suite (format picker, editor, media upload, insights) — it is the most complex surface and the least suited to a phone; media upload in particular carries a 300 s in-request normalization timeout that is hostile to mobile networks. Creators keep using the web app. Also out: tips (pending the IAP fee decision), appeals, packs.

**Never:** admin/moderation.

---

## 7. Phased plan

| # | Milestone | Scope | Depends on |
|---|---|---|---|
| **0** | **Backend readiness** | Native auth endpoints (3.1), Sign in with Apple (3.2), schema typing (3.4), `DeviceToken` + APNs (3.5), AASA file, HEIC, `X-RateLimit-*`. **Plus F-005** (onboarding persistence) — the ritual has nothing to schedule without it. | — |
| **1** | **Walking skeleton** | Xcode project, APIClient + Keychain + refresh, email login, feed + detail, paywall rendering. Ships to TestFlight. | 0 |
| **2** | **The ritual** | Today tab, daily joke, streak, mystery box, daily push, widget. **This is the milestone that justifies the app.** | 1 |
| **3** | **Account & identity** | Sign in with Apple + Google, registration + age gate + verification, onboarding, settings, GDPR export/delete. | 0, 1 |
| **4** | **Monetization** | StoreKit 2 subscriptions, server receipt validation, App Store Server Notifications, restore purchases. Tips decision resolved. | 0, 1 |
| **5** | **Library & social** | Favorites, collections, follows, creator profiles, inbox, universal links, share sheet. | 1 |
| **6** | **Submission** | Privacy manifest + nutrition labels, age rating (the catalogue has a mature tier — see below), accessibility pass, App Review. | 2–5 |

Milestones 3, 4 and 5 are largely independent once 1 is done and can be parallelised.

---

## 8. Apple-specific risks

- **Guideline 4.8** — Sign in with Apple is mandatory given Google login. Non-negotiable; it is in Milestone 0.
- **Guideline 3.1.1** — subscriptions must be IAP. Budget for the 15–30% commission in the pricing model; today's Stripe price points assume ~3%.
- **Age rating** — the data model has a `tier_2` mature tier. Verified: **there is no API to opt into it** (`show_mature` has zero serializer/view references), so no user can currently see mature content. Two consequences: (a) rate the app for the content that is actually reachable, and (b) if tier_2 is ever enabled, the rating and the age gate both need revisiting *before* it ships.
- **Guideline 5.1.1(v)** — account deletion must be available in-app. The endpoint exists but **currently 500s and destroys the user's files** (F-016, P0). This is a hard App Review blocker as well as a GDPR one.
- **Privacy manifest + tracking** — declare the telemetry. If no IDFA is used (recommended), no ATT prompt is required.
- **Cold start** — 15–19 s (F-009). A native app hides it behind a cached daily joke, but a first launch that waits 19 s on the API will read as a broken app. Set Cloud Run `min-instances=1` before launch.

---

## 9. Testing

Mirror the tier model this verification pass established, and fix its biggest gap at the same time:

- **Unit** — XCTest over the API client, token refresh (including the single-flight 401 race), paywall state, streak math.
- **Snapshot** — the reading surfaces in light/dark and at Dynamic Type XXL.
- **UI (XCUITest)** — the P0 journeys: sign-in, daily read, hit the paywall, purchase (StoreKit test file), delete account.
- **Contract** — a CI job that regenerates Swift models from `/api/schema/` and fails on drift. This is the mobile equivalent of the T3 tier that found every contract defect in this pass, and it is the single highest-value test investment.
- **Backend** — add tests for the Bearer transport and native refresh, which have **zero coverage today** (verified: no test in the repo sends an `Authorization` header).

---

## 10. Decisions needed from the owner

1. **Do we take a platform fee on tips?** Determines whether tips need IAP, get hidden on iOS, or stay on Stripe. Blocks Milestone 4.
2. **Is Android in scope within ~6 months?** If yes, re-open Option C before Milestone 1.
3. **Anonymous reading on iOS** — allow it with a device-scoped ledger, or require sign-in? (Recommend: require sign-in.)
4. **Minimum iOS version** — 17 is assumed; 16 costs modern StoreKit/`@Observable` ergonomics.
5. **Creator suite in v1?** — assumed out. If creator acquisition is the accelerator metric, that assumption should be challenged.

---

## 11. The honest prerequisite

Milestone 0 is not optional overhead — it is roughly a third of the work, and it includes fixing **web** bugs (F-005 onboarding persistence, F-016 account deletion) because the iOS app inherits them. The ritual cannot be scheduled without notification preferences that persist, and the app cannot pass review with a deletion endpoint that 500s.

Put plainly: **the fastest path to a good iOS app starts by fixing the P0s and P1s found in this verification pass.**
