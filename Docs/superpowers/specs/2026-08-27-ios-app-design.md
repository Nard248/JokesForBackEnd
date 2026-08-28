# JokesFor for iOS — analysis, design system, and implementation plan

**Date:** 2026-08-27 · **Status:** design, awaiting owner approval
**Supersedes:** `2026-08-25-ios-app-design.md` (several of its blockers are now fixed — see §2.3)
**Method:** 10 parallel analysis agents over the backend, the web client, the existing Xcode project, and Apple's iOS 26 platform; every load-bearing claim re-verified by hand before being written here.

---

## 1. Bottom line

**You have a production backend and zero iOS app.**

The 3,574 LOC at `/Users/narekmeloyan/XCodeProjects/JokesFor` builds cleanly and is architecturally modern, but it is *a picture of an app that does not exist* — no networking of any kind, and data models invented rather than derived from the API. Not one live API response would decode against it.

**The plan is now local-first, by owner decision (2026-08-27): no Apple Developer Program spend, no Cloud Run `min-instances`, build the whole app locally, then do the administrative side.**

That reverses this document's original advice. The Apple administrative chain was the front-loaded long pole *precisely because* it gated push, Sign in with Apple, StoreKit and universal links — and all four are now out of the first phase, each behind a protocol seam that becomes a capability checkbox later. **It is now the last thing, not the first.**

`LK93ZVLL6Y` is confirmed a **free personal team** (profiles carry `TimeToLive => 7`). That ceiling turns out to be generous: **76 % of the remaining engineering and ~95 % of the user-visible app can be built and verified for $0** — including the widget, because App Groups is one of only 11 capabilities available to free teams.

**Effort:** Phase A (free) ≈ **14 engineer-weeks**; Phase B (gated) ≈ **4.4 ew**, ~60 % of it form-filling. Roughly 9–10 weeks calendar with two engineers, ~4.5 months solo.

The two things you genuinely give up in the meantime: **you cannot hand a build to another human**, and **you cannot live with the app for more than seven days at a stretch**. The first shapes your demo format; the second is the real cost, and neither is solvable with code.

---

## 2. What we verified

### 2.1 The toolchain is fully current

| | |
|---|---|
| Xcode | 26.6 (build 17F113) |
| Swift | 6.3.3 |
| iOS SDK | 26.5 |
| Simulators | 26.0 → 26.5 |
| Team | `LK93ZVLL6Y`, `CODE_SIGN_STYLE = Automatic` |
| Bundle | `com.narekmeloyan.JokesFor` |
| Deployment target | **26.4** |
| Signing identity | Apple **Development** only — **no Distribution certificate** |

Targeting 26.4 means the entire Liquid Glass API surface is available with **zero `if #available` guards**. It also means the app cannot yet be distributed: there is no Distribution certificate, no entitlements file, and no App Store Connect record.

### 2.2 The existing app runs — and the tab bar is already Liquid Glass

Built and launched on a 26.5 simulator. It renders a Home tab with a TODAY hero, vibe chips, hashtag pills, search, and a FRESH feed. **The bottom tab bar is already true Liquid Glass** — feed content visibly refracts through it — purely as a consequence of building against the iOS 26 SDK. That is the shape of the whole opportunity: most of the native feel is free, if you stop opting out of it.

### 2.3 Blockers from the 2026-08-25 spec that are now GONE

| Item | Then | Now |
|---|---|---|
| **F-008 OpenAPI codegen** | 22 views missing from schema | ✅ **0 `W002`, 0 errors**, 82 component schemas — verified by running `spectacular`. Swift models can be generated today. |
| **F-005 onboarding persistence** | dropped on the floor | ✅ persists |
| **F-016 account deletion** | 500'd, destroyed files first | ✅ fixed, deferred to `transaction.on_commit` |
| **F-021 paywall `text` leak** | punchline on the wire | ✅ stripped |

Live on Cloud Run revision `jokesforbackend-00048-8f2` (commit `d074d86`).

### 2.4 Blockers that remain

| Item | Evidence |
|---|---|
| **Native token lifecycle** — *the #1 blocker* | `JWT_AUTH_HTTPONLY=True` + rotation + blacklist ⇒ the refresh token is **never in any response body**. Login returns `refresh: ""`; the refresh endpoint deletes the key entirely. A body-only client gets exactly one refresh, then a hard 401. Verified with a live login/refresh/replay round-trip. |
| **Cold start** | No `minScale` — only `maxScale=3`. Still scale-to-zero, 15–19 s. Verified against the live service. |
| **Push infrastructure** | Zero `DeviceToken`, zero APNs, Cloud Scheduler API not even enabled. |
| **Sign in with Apple** | Absent. Hard App Review blocker (4.8) the moment Google Sign-In ships. |
| **Universal links** | Both hosts serve Firebase's empty stub `{"applinks":{"apps":[],"details":[]}}`. |
| **HEIC upload** | iPhone camera default is rejected at `Image.open` with a misleading `"Not a valid image."` — proved against a real `sips`-generated HEIC. |
| **Stripe** | Production is **still `sk_test_`**, and the secret + webhook keys are **plaintext `value:` env vars** while every other secret uses `secretKeyRef`. |
| **Tap targets** | 134 sub-44 pt interactive elements across 11 routes, with no automated guard. |

---

## 3. The existing Xcode project: a parts bin, not a foundation

**What is genuinely good.** 6 × `@Observable`, 0 × `ObservableObject`, 51 `async` / 0 completion handlers, `Sendable` protocol seams, actor-based service doubles, `SWIFT_APPROACHABLE_CONCURRENCY = YES` already set. That is the pattern you would write from scratch in 2026 — and also about 30 minutes of work to reproduce from a blank template.

**What is missing.** No `URLSession`, no `URLRequest`, no `JSONDecoder`, no Keychain, no image loading, no tests (0% coverage), no app icon, no color assets, no Dynamic Type, no accessibility labels. `ServiceContainer.init(useMocks:)` has an `else` branch that is a **byte-for-byte copy of the `if` branch** — the seam was designed but never filled.

**What is actively wrong.** The models were invented, not derived. `Joke` expects flat string enums where Django returns nested objects, and its enum raw values (`one_liner`, `setup_punchline`, `clean`, `puns`, `absurdist`…) **do not exist in the backend**, whose real slugs are `oneliner/setup/knock/story/anti/observ/image/video/audio`. It models none of the last 18 months of work: no `is_locked`, no media, no `lines`, no streaks, no follows, no appeals, no notifications. `TrendingView` calls `Int.random(in: 20...150)` **inside `body`** to fabricate statistics. `HomeView.swift:51` actively opts *out* of the iOS 26 glass nav bar.

**Verdict: new target, cherry-pick ~530 LOC (≈15%).** Keep `LogoView`, `EmptyStateView`, `VibeChip`, `SearchBar`, `CollectionCard`, `FlowLayout`, `MainTabView`, `PaginatedResponse`, `User`, the Theme *structure*, and the enum display metadata (real product vocabulary). Delete ~640 LOC outright; rework or discard the other ~2,400. It is under git with a single commit, so deletion is free and reversible.

> The single most expensive mistake available here is *"let's just wire up the existing app."*

Also: flip `SWIFT_VERSION` 5.0 → 6.0 on day one. A strict-concurrency build fails on only ~20 mechanical sites, all in `Services/Mock/` and the models' `MainActor`-isolated `Decodable` conformances — which you must fix regardless, because a real API client decodes off the main actor.

---

## 4. Design: the JokesFor brand on iOS 26

### 4.1 The thesis

JokesFor's visual essence is **an editorial broadsheet that occasionally screams in neon**: a warm off-white page, hairline-ruled cards, a heavy Epilogue display voice — punctuated by a fully saturated lime card, a black card and an amber card in the same scroll.

**The brand is the format-skinned joke card. Nothing else in the system is load-bearing.**

Which makes Apple's central rule — *Liquid Glass belongs to the navigation/control layer, never the content layer* — not a tension but a **free win**. The translation is a **deletion**: stop drawing the bar, let the system draw it, and spend the entire brand budget on the content layer where Apple explicitly wants saturated color to live.

The real risk is the opposite failure mode: an engineer reaching for `.glassEffect()` on a joke card because it looks modern. That would dissolve the lime/black/amber rhythm that *is* the product into nine identical frosted rectangles.

> **Ban `.glassEffect` outside a `Chrome/` directory and the design system enforces itself.**
>
> **One carve-out, and it is the most important line in this document: the punchline blur is NOT glass.** It is an 18 pt `.blur` on the text itself. Glass samples what is *behind* a surface; the reveal must obscure what is *in front*. Anyone who builds it with `.glassEffect(.clear)` ships a legible punchline.

### 4.2 The live design is the "Flow era", not the tokens in `@theme`

A correction that matters, verified in source: the `@theme` block in `index.css` describes the **legacy** design (48 px pillow cards, purple-tinted shadows), now reachable only at `/legacy/*`. The **live** design — every canonical route, wrapped in `FlowAppShell` — is flatter and more editorial:

| | Legacy (dead) | **Flow (live)** |
|---|---|---|
| Card radius | 48 px | **18 px** (`FlowJokeCard.tsx: borderRadius: 18`) |
| Separation | purple-tinted shadow | **1 px `#E9E8E7` hairline**, near-zero shadow |
| Page ground | `#F8F6F6` | **`#FBFAF7`** warm off-white |
| Ink | `#2E2F2F` | **`#1A1A1A`** |

Hardcoded counts in live source: `#6A1CF6` ×258, `#1A1A1A` ×235, `#E9E8E7` ×218, `#CAFD00` ×103, `#FBFAF7` ×56. Note the brand purple is hardcoded 258 times and is *not* a `--color-*` token.

**Four typefaces, four jobs** — and Epilogue outnumbers Plus Jakarta roughly 5:1. Epilogue (display) is the default for anything structural; Plus Jakarta is reserved for paragraphs and button labels only; JetBrains Mono carries the wide-tracked `.eyebrow-mono` label (111 uses); Fraunces italic supplies the `.wink` word inside display headlines. Getting the Epilogue/Jakarta ratio backwards flattens the brand faster than any color mistake.

**Three signature devices**, all verified live: the `.wink` Fraunces-italic word, the `.eyebrow-mono` tracked label (111 uses), and the `.punch-blur` 18 px tap-to-reveal (24 uses).

### 4.3 The load-bearing abstraction: format skins

Every joke card is skinned by format. This single map reproduces the feed rhythm that defines the product, verified verbatim at `JokeRenderer.tsx:23-32`:

| format | bg | fg | border |
|---|---|---|---|
| `setup` / `knock` / `image` / `video` | `#FFFFFF` | `#1A1A1A` | 1 px `#E9E8E7` |
| `observ` | `#FBFAF7` | `#1A1A1A` | 1 px `#E9E8E7` |
| `oneliner` | **`#CAFD00`** | `#3A4A00` | none |
| `story` | **`#FFC965`** | `#5F4200` | none |
| `anti` | **`#1A1A1A`** | `#FFFFFF` | none |
| `audio` | `#F2E9FF` | `#6A1CF6` | none |

Port this as a `JokeSkin` struct one-for-one. Everything else in the card derives its color from it.

### 4.4 Dark mode is net-new design work

The web has **no dark mode**: `@custom-variant dark` is declared, the only 8 `dark:` utilities are untouched shadcn boilerplate, and nothing ever applies `.dark`. There is no ramp to port.

A daily-joke ritual that fires at 9 pm is inherently a dark-mode product, so it is worth authoring — under three rules:

1. **Keep the warmth.** `#FBFAF7` is a warm off-white, so the dark ground is a warm near-black (`#121110`), never Apple's blue-leaning `#1C1C1E`.
2. **Saturated brand surfaces do not flip.** A lime card is lime at 3 am. Format skins are *pigments*, not appearance tokens.
3. **The purple must lift.** `#6A1CF6` on `#121110` is **2.80:1** — unreadable. Purple as a *fill* stays `#6A1CF6`; purple as *ink* becomes `#AC8EFF` (7.3:1) in dark.

In dark mode elevation flips from border to luminance: `cardSurface #1B1A18` is *lighter* than `canvas #121110`, so the hairline becomes texture rather than separation. That is correct — do not crank it.

### 4.5 The lime rule

`#CAFD00` on white is **1.20:1**. That is not "low contrast" — it is *not a color you can see*. Four hard rules:

1. **In light contexts, lime is a ground and never an ink.** Never text, never a stroke, never a symbol tint, never a border.
2. **Lime's only legal ink is `#3A4A00`** (8.12:1). Construct lime surfaces *together* with their ink so the pairing is unforgeable.
3. **Lime is never a Liquid Glass tint.** At ~93 % relative luminance the material's adaptive label has nothing to sit against, and under Increase Contrast the tint vanishes entirely. `.tint()` on glass takes `#6A1CF6` and only `#6A1CF6` — one tinted glass element per screen, always the primary action.
4. **The inversion:** on any ground at or below `#1A1A1A`, lime *becomes* ink at 14.6–15.9:1. Dark mode unlocks a typographic use of lime that light mode forbids.

> **Lime is ink only on void grounds; everywhere else it is a ground.**

### 4.6 Where glass actually goes

Glass touches exactly four places — `RootTabs`, the toolbars, the tab accessory, and one CTA per screen:

```swift
TabView(selection: $selection) {
    Tab("Today",   systemImage: "newspaper",          value: .today)   { TodayView() }
    Tab("Explore", systemImage: "safari",             value: .explore) { ExploreView() }
    Tab("Library", systemImage: "bookmark",           value: .library) { LibraryView() }
    Tab("You",     systemImage: "person.crop.circle", value: .profile) { ProfileView() }
    Tab(value: .search, role: .search) { SearchView() }
}
.tint(.brandFill)                       // monochrome symbols, purple selection
.tabBarMinimizeBehavior(.onScrollDown)  // the Music-app behavior
.tabViewBottomAccessory { TodayAccessory() }
// Do NOT add .toolbarBackground — HomeView.swift:51's opt-out is the single line
// in the prototype costing the most native feel.
```

Everything else is opaque, hairlined, 18 pt, `.continuous`, and colored from a `JokeSkin`.

### 4.7 What we drop, and what we add

**Drop:** the 48 px radius entirely · every hover state · `float`/`bounce-slow` ambient animation · the 7-item desktop top nav · the cookie banner and its `--consent-h` coordinate dance · **onboarding step 2 (formats), which persists nothing** · the literal `████` glyph string (replaced with drawn bars) · half the eyebrow density · purple shadows on cards · custom fonts in tab bars · the dead shadcn variant matrix.

**Add (things the web cannot have):** dark mode · **haptic comic timing** — the beat between tap and reveal becomes physical, the largest native win available and it costs one modifier · `.tabViewBottomAccessory` as a persistent "🔥 12 · 6 reveals left" strip · zoom navigation transitions · **a local `UNCalendarNotificationTrigger` ritual** · Lock Screen + Home Screen widgets · Control Center button and App Intents · drawn redaction bars seeded by joke id · Dynamic Type across the whole ramp · **an accessible reveal** ("Punchline hidden. Double tap to reveal") — the web's blur is invisible to a screen reader in both directions · on-device share-card rendering via `ImageRenderer` · rolling numerals and a live countdown.

---

## 5. Architecture

```
JokesFor.app  (SwiftUI, iOS 26, Swift 6 strict concurrency)
├── Core
│   ├── APIClient        async/await URLSession; Bearer injection;
│   │                    401 → single-flight refresh → retry
│   ├── TokenStore       Keychain (kSecAttrAccessibleAfterFirstUnlock)
│   ├── Generated/       Swift models from /api/schema/ (schema is ready TODAY)
│   └── Telemetry        batched, consent-gated
├── Design               Pigment, tokens, BrandFont, JokeSkin,
│                        WinkText, EyebrowLabel, PunchBlur
├── Chrome               ← the ONLY directory where .glassEffect may appear
├── Features             Today · Reader · Library · Account · Paywall
└── Extensions           WidgetKit · (v2) NotificationContentExtension
```

**Do the design system and the API client before any screen work.** Theme, fonts, and the three brand devices are inherited by every downstream view; doing them after means touching every screen twice.

---

## 6. Backend work required

| # | Work | Effort | Gates |
|---|---|---|---|
| **B1** | `POST /auth/native/login` + `/native/refresh` returning `refresh` **in the body**, setting no cookies | ~40 LOC + tests | **All authenticated iOS** |
| **B2** | 7 schema type-hint fixes (`@extend_schema_field`, `lookup_value_regex`) | ~30 min | Swift codegen correctness |
| **B3** | `JWT_AUTH_RETURN_EXPIRATION: True`; native `REFRESH_TOKEN_LIFETIME` 1 d → 30 d | 2 lines | **Retention — see R9** |
| **B4** | Sign in with Apple provider + token revocation on account delete | ~1 wk | Submission (4.8, 5.1.1(v)) |
| **B5** | `AppleTransaction` + Server Notifications V2 webhook + union entitlement | ~1 wk | Paid tier on iOS |
| **B6** | Stripe live keys → Secret Manager; **rotate the exposed test keys** | ~0.5 d | Revenue anywhere |
| **B7** | `--min-instances=1` | 1 command | First-launch UX |
| **B8** | Real `apple-app-site-association` on the frontend host | ~1 h | Universal links |

Deliberately *not* on the critical path: HEIC (fix client-side, zero backend change) and push infrastructure (see D5).

---

## 7. Free-team capability ceiling — what $0 actually buys

**Owner decision (2026-08-27): no Apple Developer Program spend and no Cloud Run `min-instances` yet. Build everything locally as a whole, then do the administrative side.** Local notifications: approved.

`LK93ZVLL6Y` is a **free personal team** — proven, not inferred: every issued provisioning profile carries `TimeToLive => 7` (paid Developer Program profiles are 365) and `IsXcodeManaged => true`, and only an *Apple Development* identity exists.

Xcode ships the authoritative answer in `DVTPortalCachedPortalCapabilities.json`. Of **196** capabilities, exactly **11** list `XCODE_FREE_PROGRAM`:

> App Groups · AutoFill Credential Provider · Data Protection · Game Center · HealthKit · HomeKit · Increased Memory Limit · Inter-App Audio · Mac Catalyst · Maps · Wireless Accessory Configuration

| Capability | Free team? |
|---|---|
| `APP_GROUPS` | ✅ **yes** — includes `XCODE_FREE_PROGRAM` |
| `PUSH_NOTIFICATIONS` | ❌ paid |
| `APPLE_ID_AUTH` (Sign in with Apple) | ❌ paid — `APPLE_DEVELOPER_PROGRAM` only |
| `ASSOCIATED_DOMAINS` (universal links) | ❌ paid |
| `USERNOTIFICATIONS_TIMESENSITIVE` | ❌ paid — ship at `.active` |

**App Groups being free is the single largest scope finding.** It means the widget gets the normal app↔widget data channel, so the entire ritual milestone is buildable at $0 with no workaround.

Everything the app needs locally requires **no entitlement at all** and is therefore unaffected by team type: local notifications (calendar triggers, categories/actions, provisional auth, notification content extensions), WidgetKit, App Intents/Shortcuts, Control widgets, background modes, StoreKit local testing, and the whole XCTest/XCUITest tier.

**Verified empirically on this machine:**
- **No ATS configuration is needed.** A URLSession probe on iOS 26.5 reached `http://localhost`, `http://127.0.0.1` and the Mac's LAN IP — all `200` — while `http://neverssl.com` returned `-1022`. Loopback and private destinations are exempt in practice. A *physical device* additionally needs `NSLocalNetworkUsageDescription`.
- The Simulator reaches the local API with zero configuration — confirmed by fetching `/api/v1/jokes/` in simulator Safari against a local Django on port 8012, returning 342 jokes.
- The Simulator **does not validate entitlements** — it emits a `*-Simulated.xcent` containing whatever you declare. So entitlement-gated UI (the Sign in with Apple button, universal-link handling) still compiles and renders; only the backing service is absent.
- `xcrun simctl push <device> <bundle-id> payload.json` drives the full notification-response path with no APNs.

**The real free-team costs are workflow costs, not capability costs:** 7-day profiles, 10 App IDs, 3 devices, and **no way to give a build to anyone**.

### Free-team limits, precisely

10 App IDs at a time (each expiring after 7 days) · 3 test devices per platform · profiles expire 7 days from issuance. There is **no "3 app" limit** — that widely repeated claim conflates it with the 3-*device* limit.

---

## 7b. A0 — DONE (2026-08-27)

Shipped and verified live against a local server. **897 backend tests OK** (up from 877), ruff clean, no migration drift.

| Item | Result |
|---|---|
| `POST /auth/native/login/` | refresh token **in the body** (235 chars), **0 cookies**, 30-day lifetime, 15-min access |
| `POST /auth/native/refresh/` | rotates, returns both tokens in the body, **0 cookies**, keeps the 30-day window |
| **Refresh twice consecutively** | ✅ 200 / 200 — *the milestone exit criterion* |
| Replay of a spent token | 401 (still blacklisted) |
| Bearer round trip | `/auth/user/` → 200 |
| Web login unchanged | still `refresh: ''` + 2 cookies — httpOnly hardening intact |
| `/media/` under DEBUG | 404 → **200** (563 files were unroutable) |
| Schema nullability | `text`, `punchline`, `lines` now declared nullable — they were advertised non-null while the paywall nulls them |
| Seed gaps | audio 0 → 2, video 1 → 2, tier_2 2 → 5; media files generated with ffmpeg so they genuinely decode |

New files: `jokes/native_auth.py`, `jokes/tests_native_auth.py` (17 tests), `jokes/tests_paywall_schema.py` (3), `jokes/management/commands/seed_media_dev.py`.

### Contract notes for the iOS client

- **The format filter parameter is `joke_format`, not `format`.** DRF's content negotiation owns `format` (`URL_FORMAT_OVERRIDE` defaults to it), so `?format=audio` returns **404** for every value — it looks for a renderer by that name. `jokes/views.py:294` names the real filter `joke_format` for exactly this reason. Comma-separated multi-select works: `?joke_format=audio,video`.
- Unknown query params are silently ignored, so a misspelled filter returns an **unfiltered** page rather than an error. Assert on counts, not on HTTP status, when testing filters.
- Local media URLs are absolute and built from the request Host, so a device hitting the LAN IP gets LAN-IP media URLs with no extra configuration.

### Running it locally

```bash
cd /Users/narekmeloyan/PycharmProjects/JokesForProject
export DATABASE_URL='' DEBUG=True DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
.venv/bin/python manage.py runserver 0.0.0.0:8012   # 8000/8011 are taken by other projects
```
`DYLD_FALLBACK_LIBRARY_PATH` is required on macOS — share-card rendering needs Homebrew cairo, and without it any `Joke.save()` raises `OSError: no library called "cairo-2"`.

**Still open in A0:** raise `THROTTLE_ANON`/`THROTTLE_USER` via a git-ignored `.env.ios-dev` (the scoped native-auth throttles are already in place at 20/hr login, 120/hr refresh), and the contract-lock CI script.

---

## 7c. A1 — DONE (2026-08-28)

`/Users/narekmeloyan/XCodeProjects/JokesFor`, commit `44047ee`. **34 tests passing, zero warnings.**
No git remote configured yet — the work is committed locally only.

**Project.** Swift 6 strict concurrency; deployment target 26.0 (D9). Deleted ~3,000 LOC of
mock-backed feature code; kept `FlowLayout`.

> **D8 redrafted.** The folders are `PBXFileSystemSynchronizedRootGroup` (`objectVersion 77`) with
> *zero* `.swift` references in the pbxproj — files on disk are automatically in the target. A new
> target would have burned an App ID slot and orphaned `group.com.narekmeloyan.JokesFor` for no
> benefit. Restructuring in place gives the same clean slate and keeps the bundle identifier (ND8).

**Models are hand-written**, and the decision is now evidence rather than argument: the generator
was run against the real schema and emits 40,275 lines that do not compile, typing `Joke.text`
non-optional while the paywall nulls it.

Two defences, each with tests: `OpenEnum` (unknown value → fallback, because the taxonomy is
database rows) and a lossy `Page<T>` (one malformed row costs one card, not the screen).

**Transport.** `APIClient` — Bearer, one 401 retry, no cookies. `AuthSession` — actor, Keychain at
`AfterFirstUnlock`.

> **Refresh needed more than single-flight.** Ten requests do not 401 at the same instant; their
> failures arrive in sequence, each finding no refresh in flight and starting its own. Every
> rotation blacklists its predecessor, so that is a race against the app's own tail requests. The
> fix is to compare against *the token that actually failed* — first caller rotates, the rest are
> handed the result. A test drives ten concurrent 401s and asserts exactly one refresh; it caught
> this design gap, which is why it exists.

**Live tier.** `LiveAPITests` run against a real server and **skip themselves when none is
listening** — `xcodebuild` does not forward the shell environment into a host-app unit test
process, so an env-var gate silently skips everything and reads as a pass.

### Contract facts the client must respect

| | |
|---|---|
| Format filter | **`joke_format`**, never `format` — DRF owns `format` for content negotiation and 404s for every value |
| Unknown query params | **silently ignored** — a misspelled filter returns an *unfiltered* page, not an error. Assert on counts, not status |
| Page size | pinned at **10**; `?page_size` is ignored |
| Locked joke | `text`, `punchline`, `lines` all `null`; `media[].url` **key absent**, dimensions retained |
| Timestamps | fractional-second ISO-8601 — `.iso8601` alone rejects them |
| Trailing slashes | required (`APPEND_SLASH` 301s, and a redirected POST loses its body). `URL.path` strips them, so never assert on that accessor |

### One correction worth remembering

I briefly rewrote URL construction believing `appending(path:)` dropped the trailing slash. It does
not — only the deprecated `URL.path` accessor does. The change was reverted; the regression test was
kept.

---

## 7d. A2 — DONE (2026-08-28)

Commit `22485a6`, pushed. **45 tests, no warnings.** Verified visually on a 26.5 simulator in both
appearances.

**Typefaces — the trap that would have shipped silently.** Google now publishes these families only
as variable fonts, and their named instances are not addressable as the design assumed:

| Family | Actual named-instance PostScript name |
|---|---|
| Epilogue | `EpilogueRoman-Black` — not `Epilogue-Black` |
| JetBrains Mono | `JetBrainsMonoRoman-Medium`, and **no SemiBold exists** |
| Plus Jakarta Sans | **null** — no PostScript name on any instance |

`Font.custom` with an unresolvable name falls back to San Francisco with no error, so all three
would have produced a quietly off-brand app. Fixed by instancing the variable fonts at the exact
design weights with PostScript names set locally; `FontResolutionTests` asserts each resolves to its
real family. **Info.plist must live in `Config/`** (sibling of the synchronized folder) and be scoped
to the app target only.

**Colour is code, not an asset catalog**, so the rules are executable — `ContrastTests` computes real
WCAG ratios, including that lime on white is ~1.2:1 (invisible, not merely low) and that `limeInk` is
its only legal partner. Dark mode is net-new: warm near-black, saturated pigments held fixed,
purple-as-ink lifted to `#AC8EFF`.

**The reveal is an 18pt blur, never glass** — glass samples what is *behind*; the reveal must obscure
what is *in front*. A comment-aware source scan fails the build if `.glassEffect` appears outside
`Chrome/`.

`DesignGallery` renders the whole system and is the app root until A3.

---

## 7e. A3.1 — read path on real data (2026-08-28)

iOS `22485a6..`, backend `9340070`. **69 iOS tests + 903 Django tests, no warnings.**
Verified by running the app against a live local API, not only by fixtures.

Shipped: the glass tab shell (`Chrome/RootTabs`, five destinations, `Tab(role: .search)`,
minimize-on-scroll, ritual accessory), `JokeService`, `JokeCardView`, Today, Explore, Search.
Library and You are honest placeholders.

### Three bugs only running the app could find

**1. A locked one-liner had nothing to display.** The F-021 fix withheld `text` correctly, but its
docstring's assumption — *"`setup` is always kept, and the client composes the locked card from it"*
— holds only for two-part formats. Measured against a real capped account: **10 of 10** locked jokes
on the page rendered blank, and one-liners are ~40% of the catalogue. Fixed backend-side with an
always-present `teaser`; guarded client-side by `testNoLockedJokeRendersAsABlankCard`.

**2. Anonymous reads failed before leaving the device.** `AppModel` always constructs an
`AuthSession`, so "authenticated" was true with no tokens and `accessToken()` *threw*. Every screen
showed its error state. Reading works signed out by design, so the client now attaches credentials
when it has them and proceeds anonymously when it does not.

**3. `/daily-jokes/today/` is polymorphic.** Signed in it returns
`{id, joke, date, delivered_at, created_at, issue_label}`; signed out, `{joke, date}` — there is no
`DailyJoke` row to return. A non-optional `id` broke exactly one screen, the **first one a new
reader sees**, while every other surface worked.

### The A3 exit criterion

`LeakProofingTests` drives a real locked fixture through every path a client can leak by: `text`,
`payoff`, **Copy**, **Share**, media `url`, and the accessibility label — plus a synthetic case
where the server sends a payoff on a joke flagged locked, which the presentation still refuses.
`JokePresentation` is the single choke point, so the leak is structurally hard rather than a thing
reviewers must remember.

**Still open in A3:** joke detail with `?source=` attribution, Library, and the XCUITest tier.

---

## 7f. A4 + A5.1 — accounts and the ritual (2026-08-28)

iOS `f751680`, `81a6872`. Backend `7e5465c` deployed. **98 iOS + 910 Django tests.**

**A4 — accounts.** Sign in, register, verify. Built against **production's** configuration:
`EMAIL_VERIFICATION_REQUIRED` defaults to `false` locally and is `true` in production, so the local
default would have produced an app that works on this machine and breaks on release.

Added `POST /auth/native/verify-email/` (backend), closing the last gap the original spec named: the
web endpoint sets cookies and returns only the user, so a native client finished verification with
**no credentials** and had to replay the password. The guard chain — anti-enumeration,
already-verified, attempt lockout, `is_active` — was extracted into one function both views call
rather than duplicated; a second copy of that chain is how an auth bypass gets written.

**A5.1 — the ritual.** Local notifications, no backend, works signed out.

> **Deviation from the plan, deliberately.** The plan called for ~60 dated requests topped up per
> foreground so each could carry a real teaser. But the daily joke is assigned per date by the
> server, so tomorrow's is the furthest ahead the client can know — everything beyond carries
> generic copy regardless. What the dated design *does* buy is a hard dependency on the app being
> opened: stop for two months and the ritual silently stops. For a habit product that is backwards.
>
> One repeating trigger per chosen weekday: ≤7 pending requests, never near the 64 ceiling, no
> rescheduling, and it keeps firing whether or not the app is opened again. `DateComponents` rather
> than a date means "9pm wherever you are" survives a flight.

`RitualCopy` **takes no joke as input**, so a punchline cannot reach a lock screen — where a body is
also read by Notification Summaries and Apple Intelligence. Shipped `.active`, not
`.timeSensitive` (paid-gated, and a joke is not an interruption anyone requested).

Provisional authorization: **verified that launch shows no permission dialog**.

### What the UI tier keeps catching

Both A4 and A5 had tests that passed alone and failed in a group, and both times the cause was real
state that *should* persist:

| Persisted by design | Broke |
|---|---|
| Keychain session | a run that signed up left the next already signed in |
| `ritual.plan` in UserDefaults + pending requests | one ritual test inherited another's schedule |

`-resetSessionForTesting` now clears all three — and only ever clears, so it cannot grant access, and
it is compiled out of release builds.

**Still open in A5:** the widget extension (needs a new target and App Group — confirmed free), and
device-only verification: notification delivery under Focus, widget rendering, and haptics.

---

## 8. Phase A — everything buildable for $0

| # | Milestone | Exit criterion | Eff. |
|---|---|---|---|
| **A0** | **Local ground truth** *(backend, start now)* | `/media/` returns 200 (563 files are unroutable today); throttles raised locally; seed gaps filled (0 audio, 1 video, 2 tier_2 rows exist); a Bearer client refreshes **twice consecutively** from the body; contract lock green in CI | 0.5 ew |
| **A1** | **Foundation & contract layer** | Builds at Swift 6 strict concurrency, **zero** warnings; concurrent 401s trigger **exactly one** refresh; the model layer decodes fixtures for all 10 formats **plus a locked joke plus an unknown enum value plus a malformed row**, and the page still renders | 2.5 ew |
| **A2** | **Design system** *(parallel, no backend)* | Snapshot tests for all 9 skins in light **and** dark; reveal is 18 pt blur over 0.55 s and **instant** under Reduce Motion; VoiceOver announces the gate; lime is never ink on a light ground | 1.5 ew |
| **A3** | **Read path** | Today · Explore · Search · Library · Detail on real data; a locked joke leaks its punchline through **no** path — proven by UI test | 3.0 ew |
| **A4** | **Auth, account, compliance** *(minus the SIWA runtime)* | register → verify (code read off disk) → login → Bearer read → Bearer write, green in a UI test; delete-account leaves no row and no 500 | 2.0 ew |
| **A5** | **The ritual** *(zero backend, fully free)* | Notification fires on a real device at the chosen time with **setup text only**; tap deep-links to the joke; widget legible in accented rendering on a real Home Screen | 2.0 ew |
| **A6** | **Media playback** | Image/video/audio render; locked media reserves layout from `width`/`height` without reading `url` | 1.0 ew |
| **A7** | **Hardening** | Every screen clean at `.accessibility2`; VoiceOver on all icon-only buttons; automated 44 pt tap-target guard; `PrivacyInfo.xcprivacy`; age-rating audit written down | 1.5 ew |
| **A8** | **StoreKit local** *(optional, last)* | Only if enrollment is imminent — see ND6 | 1.0 ew |

**Phase A = 14 ew** (15 with A8) — **76 % of remaining engineering, ~95 % of the user-visible app.**
≈ 4.5 months solo, ≈ 9–10 weeks with a second engineer.

### Models are hand-written — settled by evidence, not taste

swift-openapi-generator was actually run against the real schema. It emits **40,275 lines that do not compile** (115 errors: drf-spectacular advertises multipart on 29 DRF endpoints, poisoning `JokesForUserDetails` — the `user` field of the login response). Worse, it types `Joke.text` as **non-optional** while `jokes/serializers.py:318` nulls it for every paywalled joke — a day-one P0 that blanks the feed for any free user past their 10th read.

And it buys nothing here: the taxonomy is `{id,name,slug}` **objects**, not OpenAPI enums, so codegen gives zero enum safety where drift actually lives; `lines` is untyped; `media` lands as `[String: Any]`. The web client already made this call — `src/lib/api.ts` is 1,198 hand-written lines that shipped.

Write ~26 structs. Two defences are mandatory:
- **`OpenEnum`** — lenient decoding with an unknown-case fallback, applied to the 9 backend `choices` enums that can gain values from a Django deploy with no App Store release. Measured blast radius without it: one unknown row → **0 of 20 jokes render, feed blank**.
- **Lossy `Page<T>`** — a malformed row drops itself rather than the page.
- Taxonomy stays `struct TaxonomyRef`, **never** a Swift enum. `text`/`punchline`/`lines` are Optional regardless of what the schema claims.

---

## 8b. Phase B — gated behind money

| Item | What | Eff. | Calendar |
|---|---|---|---|
| **B-ADM** | Enrollment ($99) → Paid Applications Agreement → tax/banking → SBP → 3 × `.p8` → ASC record → DSA trader verification | 0.5 ew | **1–4 wk** |
| **B-SIWA** | Apple provider + revocation, client activation | 1.0 ew | after B-ADM |
| **B-IAP** | `AppleTransaction`, Server Notifications V2, union entitlement resolver | 1.5 ew | after B-ADM |
| **B-LINK** | Associated Domains + AASA verification | 0.2 ew | after B-ADM |
| **B-SHIP** | Screenshots, age rating, privacy labels, distribution cert, TestFlight, review | 1.0 ew | 1–3 wk |
| **B-INFRA** | `--min-instances=1`; Stripe live keys → Secret Manager + **rotate exposed test keys** | 0.2 ew | launch day |

**Phase B = 4.4 ew**, ~60 % of it form-filling and waiting.

### What genuinely cannot be finished in Phase A

The rule for each: **build the seam, build the UI, test with a fake, write down the one sentence that stays unverified.**

| Blocked | Buildable now | Unverifiable until paid |
|---|---|---|
| **Sign in with Apple** | The button, nonce + SHA-256, delegate plumbing, DOB routing, the `IdentityProvider` protocol, **and ~60 % of the backend** (`POST /auth/apple/` tested against locally-minted RS256 tokens) | Whether `ASAuthorizationController` returns a real credential; token revocation on delete |
| **Push** | The entire notification layer — it's the *same* layer. `simctl push` drives the response path with the future APNs payload | `registerForRemoteNotifications()` returning a token; server delivery |
| **Universal links** | The custom URL scheme + one parser handling both shapes, unit-tested. **Publish the AASA file anyway** — one hour, inert until the entitlement exists | Whether iOS associates the domain |
| **StoreKit** | The purchase flow against a local `.storekit` file; `SKTestSession` drives renewals, expiry, interrupted purchases | Sandbox, real products, and **server-side receipt verification** |
| **Distribution** | Nothing. Screenshots can be simulator captures | Everything — no TestFlight, no ad hoc, no build you can hand to anyone |

### The 7-day profile problem, plainly

**Mechanically trivial: ~2 minutes a week.** Connect the phone, Cmd-R; Xcode silently mints a fresh profile. The app's **data container is preserved**, so App Group state, Keychain tokens and UserDefaults survive.

**The cost that actually matters: you cannot live with the app.** After 7 days away from the Mac it refuses to launch. For a *daily ritual product* that is precisely the thing you most want to do — carry it for a month and find out whether the 9 pm notification is delightful or annoying. That is a real product-learning cost, and no amount of Simulator time substitutes for it.

**Verdict: develop on the Simulator by default** (zero limits, no signing, no ATS friction), and **hold a device pass every Friday**, which doubles as the weekly re-sign. Device-only, never simulator-verifiable: **haptics** (no Taptic Engine — and haptic comic timing is the largest native win in the design), notification delivery timing under Focus/Scheduled Summary, widget rendering and the 40–70/day reload budget, Keychain-in-widget while genuinely locked, performance, camera/HEIC, and ATS to a raw LAN IP.

---

## 9. Risks

| # | Risk | P | Mitigation |
|---|---|---|---|
| **R1** | **Guideline 4.8** — Google Sign-In ships without SIWA. No exemption applies | ~1.0 | Build SIWA in M4. Not optional, not deferrable |
| **R2** | **Tips violate 3.2.1(vii)** — funds land in the platform account (not 100 % to creator) and the `Tip.joke` FK makes every tip "connected to digital content" | High | **Hide tips on iOS v1.** Zero engineering, removes the risk entirely |
| **R3** | **IAP commission** | 1.0 | **Enroll in SBP before the first transaction** — see below |
| **R6** | **Runtime decode failure from taxonomy drift** — non-optional `Codable` enums throw and kill the whole response | High | Lenient enum decoding with unknown-case fallback; CI contract test against prod `/api/schema/` |
| **R9** | **1-day refresh + rotation + blacklist logs out anyone who skips a day** — in a *daily ritual* product | 1.0 if unchanged | B3: 30-day native refresh |
| **R7** | 18+ rating blocks unconfirmed downloads in AU/BR/SG | Med | Exclude `tier_2` from iOS v1 |
| **R8** | **Guideline 1.2** — 24 h SLA, EULA gate, in-app contact | Med-High | Ship all five controls as demonstrable artifacts; write the SLA down |
| **R10** | 15–19 s cold start on first launch | 1.0 until fixed | One `gcloud` flag |
| **R11** | Prod Stripe is test-mode; secret + webhook keys are **plaintext env vars** | 1.0 | Live keys + Secret Manager + **rotate** |
| **R13** | Apple Intelligence summaries garble or delay the joke | Med | Setup-only in `body`; `relevance-score: 1.0` |

### R3 quantified — the number that should drive the decision

Assuming Supporter at **$4.99/mo** *(never stated in any doc — confirm)*:

| Channel | Net/month | Take |
|---|---|---|
| Stripe (2.9 % + $0.30) | $4.55 | **91.1 %** |
| Apple IAP, **SBP-enrolled** (15 %) | $4.24 | **85.0 %** |
| Apple IAP, standard (30 %) | $3.49 | **70.0 %** |

**Enrolled in SBP, IAP costs ~6 points versus Stripe, not 30.** Un-enrolled it costs ~21. On 1,000 subscribers for a year that difference is **$8,982**. Enrollment is a same-day form.

**Do not architect around the 0 % US link-out.** It is live-litigated — Ninth Circuit reversed the ban 11 Dec 2025, SCOTUS granted review 30 Jun 2026 and a pause 12 Aug 2026, Apple proposed 15/10/5 % on 13 Aug 2026. Any link-out must be storefront-gated *and* server-killable without an app update.

### R4 — why local notifications sidestep an entire class of problem

Gunicorn runs `--workers 2 --threads 4` with `maxScale: 3` → a 24-thread ceiling. Serialized APNs at ~50 ms round-trip is ~20/s per thread, so a naive single-shot fan-out **times out above roughly 6,000 devices**. And the APNs provider JWT must be cached in the shared `DatabaseCache` — N Cloud Run instances each minting their own hits `429 TooManyProviderTokenUpdates`.

All of this disappears with local notifications. The 64-pending-request limit yields ~2 months of dated daily jokes per app open, and `UNCalendarNotificationTrigger` follows the user across time zones on device wall-clock — removing the per-user timezone column, the scheduler, the APNs sender, and the Cloud Scheduler enablement.

---

## 10. Decisions — status after the local-first call

### Settled — close these

| # | Decision | Resolution |
|---|---|---|
| **D3** | Paid tier on iOS v1 | **Deferred.** No StoreKit revenue path exists at $0. The paywall UI reads the live server-side freemium state, which already works locally. |
| **D4** | Tips on iOS | **Hidden.** Compliance landmine, zero revenue, no payout rail. Zero engineering. |
| **D5** | Push vs local notifications | **Local — and now forced, not merely chosen.** `aps-environment` is paid-only. It was the right call anyway: the fan-out capacity risk disappears entirely. |
| **D8** | Existing Xcode project | **New target, cherry-pick ~530 LOC.** |
| **D12** | Staffing | **Phase A = 14 ew** ≈ 4.5 months solo, 9–10 weeks with two. |
| **Q3** | Is `LK93ZVLL6Y` paid or personal? | **Answered: free personal team.** `TimeToLive => 7`, Development identity only. |
| §7 | "Start the admin track first" | **Reversed. It is now last.** |

### Still open

| # | Decision | Recommendation |
|---|---|---|
| **D1** | Auth transport | **Native body endpoints anyway.** Stakes are lower than stated — URLSession's cookie jar demonstrably works — but 40 LOC removes an intermittent CSRF-403 failure class. |
| **D2** | Anonymous browse | **Re-opened, and the lean has flipped to *allow it*.** The backend already supports it (`AllowAny` + the `jf_anon_reads` signed-cookie ledger). With no distribution, the demo is a recording — and a forced sign-in wall is the worst possible first frame of an accelerator pitch. |
| **D6** | `tier_2` mature content | Exclude from v1. Only 2 rows exist anyway. |
| **D7** | Media jokes | Playback only. |
| **D9** | Deployment target | **26.0, not 26.4.** Nothing in Liquid Glass postdates 26.0. |
| **D10** | Information architecture | Mirror the web's 5-tab bar. |
| **D11** | Visual direction | All three by layer; `.glassEffect` banned outside `Chrome/`. |
| **Q1** | What does Supporter cost? | Still unanswered. Less urgent now (no IAP in Phase A), but blocks A8 and B-IAP. |
| **Q2** | Platform fee on tips? | Still unanswered. Moot while tips are hidden. |

### New decisions the local-first approach forces

| # | Decision | Recommendation |
|---|---|---|
| **ND1** | Which backend does the Simulator point at by default? | **Local** for development. A *Debug-Prod* scheme against live Cloud Run for read-path realism and demos — it costs nothing, it is already deployed. |
| **ND2** | Hand-written models + a drift lock | Confirm. Then decide the watched-operations list — *that list is the contract*, and it must grow as the app grows. |
| **ND3** | **Accelerator demo format** | **A recorded or live Simulator session.** This is forced, not preferred: a free team cannot produce a build any other human can install. Decide it now, because it shapes what you build first — Today and Reader must be beautiful; Settings need not be. |
| **ND4** | Widget data channel | App Group container (`group.com.narekmeloyan.JokesFor`, already registered). App fetches → writes → `reloadAllTimelines()`. Keychain holds the token, not content. |
| **ND5** | Anonymous ledger on iOS | The `jf_anon_reads` cookie is per-install and evadable by deleting the app. Decide deliberately — do not let it be settled by whether someone remembered to configure `HTTPCookieStorage`. |
| **ND6** | Does A8 (StoreKit local) run at all? | **No, until enrollment is imminent.** It is the one Phase A block whose output cannot be validated. Build the ~30-LOC `EntitlementResolver` seam and stop. |
| **ND7** | **What triggers the first dollar?** | Write the condition down now so it is not an anxious open loop. Any one of: (a) someone who is not you must install the app; (b) you need to verify a real purchase; (c) you are submitting. Until one fires, $99 buys nothing you can use. |
| **ND8** | Freeze the bundle-ID namespace | app + `.Widget` + `.NotificationContent` + UI-test runner = 4 of 10 App IDs. Churning names burns slots and orphans app groups. Pick once. |
| **ND9** | Dogfood cadence | Simulator daily; **device pass every Friday**, which doubles as the weekly re-sign. |

---

## 11. What I would NOT build in v1

**Creator submission/editor** — autosave, `useBlocker` guards, per-format validation across 9 formats, media upload, draft management. ~3 ew serving your smallest audience. Link to the web editor. *(The existing `SubmitJokeView` at 233 LOC models 4 formats with free-text fields — the largest "looks done but isn't" screen in the project.)*

**Creator insights** — every stat degrades to `—` without dense telemetry.

**Tips** — compliance landmine, zero revenue today, payout rail does not exist.

**Media upload** — playback only.

**`tier_2` mature content** — drives the rating to 16+/18+.

**Push notifications** — local scheduling is strictly better for this product shape.

**Live Activities** — killed explicitly so it does not resurface. A static joke has no beginning, no end, no progression and no live data; it fails all three HIG criteria, and a persistent Dynamic Island presence is exactly the promotional misuse the HIG names.

**Onboarding step 2 (formats)** — the web code comment states outright there is "nowhere to persist a format preference anyway." Cut the step rather than ship a screen that discards the answer.

**Trending / Daily / Favorites as tabs** — desktop-only top-nav items; secondary destinations inside Today and Library.

**Follows, packs, achievements, recently-viewed, streak-freeze UI** — keep Today to four blocks: JOTD hero, streak rail, mystery box, tomorrow teaser. *(Keep the mystery box — two endpoints, and it is the variable-reward mechanic.)*

---

## 12. The first five things — revised for local-first

1. **Add a DEBUG-guarded `/media/` route** to `JokesForProject/urls.py`. Three lines. **563 media files are on disk and every one 404s locally today** — every media joke and share card is invisible without it.
2. **Raise `THROTTLE_ANON` / `THROTTLE_USER` in a git-ignored `.env.ios-dev`.** 100/hour will bite an iOS dev loop within the first hour.
3. **Write `POST /auth/native/login|refresh` (B1) + the 30-day native refresh lifetime (B3).** ~40 LOC. Demoted from *blocker* to *hygiene* — URLSession's cookie jar demonstrably works today — but `REFRESH_TOKEN_LIFETIME` is **1 day** with rotation and blacklisting, so this is not a launch problem, it is a Tuesday-morning problem you hit within 24 hours of your first login.
4. **Fill the seed gaps.** There are 0 audio jokes, 1 video and 2 `tier_2` rows. You cannot build the audio skin against zero rows.
5. **Start the new Xcode target** — Swift 6, deployment target 26.0, `Config/` as a *sibling* of `JokesFor/` (it is a synchronized buildable folder; an Info.plist inside it is a hard build failure).

**Explicitly NOT now:** the Paid Applications Agreement, `--min-instances=1`, and any StoreKit work. `min-instances` costs money continuously and buys nothing while you develop against localhost — it matters on exactly one day, launch. For a demo against production, a `curl` 30 seconds beforehand warms the service for free.

**Still worth doing at $0, unrelated to iOS:** rotate the Stripe test keys currently sitting in plaintext Cloud Run env vars.
