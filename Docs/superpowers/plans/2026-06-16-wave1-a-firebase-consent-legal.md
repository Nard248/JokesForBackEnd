# Wave 1A — Firebase Analytics Gate + Consent Banner + Legal Pages (frontend)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes. Wave 1 (launch-gating compliance); decisions CD1-CD6 locked in 2026-06-16-wave1-decisions-and-user-action-items.md.

---
## Wave 1 Work-Stream A — Firebase analytics consent gate, cookie-consent banner, DRAFT legal pages, and dead-link fixes (frontend)

**Goal:** Make the frontend launch-gating compliant for the TEXT-ONLY MVP (Wave 1, Work-Stream A): stop Firebase analytics from firing at boot, gate it behind explicit consent AND adult age, add a simple Accept/Reject cookie-consent banner with a versioned localStorage record, ship engineer-drafted DRAFT legal pages (Privacy / Terms / Cookie / Children's Privacy) with real routes, and fix the dead/bare legal links in Footer.tsx and RegisterPage.tsx — all under full TDD with vitest.

**Architecture:** Four cohesive, mostly-independent slices, all in the React 18 + Vite + TS app at /Users/narekmeloyan/WebstormProjects/jokes-for-frontend.

1) ANALYTICS GATE (CD1). Today src/main.tsx does `import './lib/firebase'` purely for side effects, and src/lib/firebase.ts eagerly runs `initializeApp(...)` at module top-level AND immediately resolves `analyticsPromise = isSupported().then(getAnalytics)`. That promise is the eager boot-time analytics init and nothing else imports it. Refactor firebase.ts so module import has ZERO side effects: keep the config object, lazily build the FirebaseApp only when first needed, and replace the eager `analyticsPromise` with an idempotent `initAnalytics(): Promise<Analytics | null>` that (a) returns the same in-flight/resolved promise on repeat calls (module-level memo), (b) calls `isSupported()` then `getAnalytics()` only when invoked, and (c) no-ops returning null if measurementId is absent. Add a tiny `isAnalyticsInitialized()` for tests. Remove the `import './lib/firebase'` line from main.tsx entirely so nothing fires on load. Nothing in the app calls initAnalytics() except the consent flow (Accept + adult).

2) CONSENT (CD4). A pure storage module src/features/consent/storage.ts owns the versioned localStorage record `{ version: number, analytics: boolean, ts: number }` under a stable key, exporting CONSENT_VERSION, readConsent(), writeConsent(analytics), clearConsent(). A decision is considered "made" only if a record exists AND its version === CONSENT_VERSION (so bumping CONSENT_VERSION re-prompts). A useConsent() hook (src/features/consent/useConsent.ts) exposes { consent, decided, accept, reject } and is the single integration point: accept() writes {analytics:true} then, if the current user is an adult, calls initAnalytics(); reject() writes {analytics:false} and never touches analytics. A ConsentBanner component (src/features/consent/ConsentBanner.tsx) renders only while !decided, with two buttons (Accept / Reject — essential only, no category toggles), and is mounted once in App.tsx alongside the router so it shows app-wide. Adult determination: add optional `date_of_birth?: string | null` to the User interface in src/lib/api.ts and a pure helper isAdult(dob) (src/features/consent/age.ts) returning true only for a valid DOB that is >= 18 years ago; anon/null/under-18 => false (so analytics stays OFF by default, matching CD1 "defaults OFF; only after consent AND adult age"). The hook reads the user via useAuthStore.getState() at accept() time (not as a render dep) so consent works for both anon and authed users.

3) LEGAL PAGES (CD5). New typed content modules under src/content/legal/{privacy,terms,cookie,children}.ts. Each default-exports a typed LegalDoc `{ title: string; lastUpdated: string; draftNotice: string; sections: { heading: string; body: string[] }[] }`, with draftNotice = "DRAFT — pending counsel review" and complete engineer-drafted copy appropriate to a text-only joke app (no rich-media/UGC-moderation claims beyond MVP). A shared src/content/legal/types.ts holds the LegalDoc type, and src/content/legal/index.ts re-exports the four docs. A single reusable presentational component src/pages/legal/LegalDocPage.tsx renders any LegalDoc (visible DRAFT banner at top + lastUpdated + sections). Four thin route components PrivacyPage/TermsPage/CookiePolicyPage/ChildrenPrivacyPage (in src/pages/legal/) each render LegalDocPage with their doc. Export them from the src/pages barrel and wire public routes /privacy, /terms, /cookie-policy (alias /cookies), /childrens-privacy in app/routes.tsx.

4) DEAD-LINK FIXES. Footer.tsx: point /privacy and /terms at the real routes (already correct strings — but the routes did not exist; adding the routes fixes them) and replace the dead /about link with a real legal link (Cookie Policy) so the footer has no dead targets; add a Children's Privacy link too. RegisterPage.tsx lines 404-405: replace the bare `<a style=...>Terms</a>` / `<a>Privacy</a>` (no href) with react-router `<Link to="/terms">` / `<Link to="/privacy">` (open in same tab is fine; target stays internal).

Testing strategy mirrors existing suite: vitest + jsdom + @testing-library/react, setup at src/test/setup.ts, route tests via createMemoryRouter with mocked @/pages (see src/app/routes.test.tsx). For analytics, vi.mock('firebase/analytics') and vi.mock('firebase/app') so we can assert getAnalytics is NOT called on import and IS called after accept-as-adult. localStorage is available in jsdom; clear it in beforeEach.

**Tech Stack:** React 18 (pkg shows react 19.2 actually installed), TypeScript ~5.9, Vite 7, react-router 7 (createBrowserRouter/RouterProvider, import from 'react-router'), zustand 5 auth store, firebase 12 (firebase/app + firebase/analytics), vitest 2 + jsdom + @testing-library/react + @testing-library/jest-dom. Path alias '@' -> ./src. Test command: npm run test (vitest run). No new dependencies required.

**Files:**

| Action | Path | Responsibility |
|---|---|---|
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/firebase.ts` | Remove eager side effects: drop top-level initializeApp and the eager analyticsPromise. Keep firebaseConfig. Add lazy memoized getFirebaseApp(), idempotent initAnalytics(): Promise<Analytics\|null> (only place getAnalytics is ever called), and isAnalyticsInitialized() for tests. Nothing runs on import. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/firebase.test.ts` | vitest: importing the module does NOT call initializeApp/getAnalytics (mocked); initAnalytics() calls getAnalytics exactly once even when called multiple times (idempotent); returns null when measurementId missing or isSupported()=>false. |
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/main.tsx` | Delete the `import './lib/firebase'` side-effect line so analytics never initializes at boot. No other change. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/storage.ts` | Pure consent persistence: CONSENT_VERSION constant, ConsentRecord type {version,analytics,ts}, readConsent()/writeConsent(analytics:boolean)/clearConsent() over localStorage under key 'jokesfor-consent'; readConsent returns null if missing, malformed, or version mismatch. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/storage.test.ts` | vitest: writeConsent persists a versioned record; readConsent round-trips; version bump (or stale version) makes readConsent return null (re-prompt); malformed JSON tolerated; clearConsent removes it. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/age.ts` | Pure isAdult(dob?: string\|null): boolean — true only for a valid ISO date >= 18 years before today; null/undefined/invalid/under-18 => false. Used to gate analytics on Accept. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/age.test.ts` | vitest: 18+ DOB => true; exactly-18-today boundary; 17 => false; null/undefined/garbage => false. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/useConsent.ts` | useConsent() hook: state {consent, decided}, accept()/reject(). accept() => writeConsent(true) then if isAdult(currentUser.date_of_birth) call initAnalytics(); reject() => writeConsent(false), never touches analytics. Reads user via useAuthStore.getState() inside accept (not a render dep). |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/useConsent.test.tsx` | vitest (renderHook): accept persists analytics:true and calls initAnalytics when user is adult; accept by non-adult/anon persists true but does NOT call initAnalytics; reject persists analytics:false and never calls initAnalytics; decided flips true after a decision. Mocks @/lib/firebase initAnalytics + auth store. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/ConsentBanner.tsx` | Presentational banner using useConsent; renders null when decided; otherwise a fixed-bottom bar with short copy, a link to /cookie-policy, and Accept / Reject buttons wired to hook. No category toggles (CD4). |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/ConsentBanner.test.tsx` | vitest: banner visible with no stored decision; clicking Accept hides it + persists; clicking Reject hides it + persists; with a current-version record already in localStorage the banner does not render. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/index.ts` | Barrel: export useConsent, ConsentBanner, readConsent/writeConsent/clearConsent, CONSENT_VERSION, isAdult. |
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/app/App.tsx` | Mount <ConsentBanner /> once inside <Providers> next to <AppRoutes /> so it shows app-wide above the router. |
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api.ts` | Add optional `date_of_birth?: string \| null` to the User interface (cross-agent contract field that backend will populate) so isAdult/consent can read it type-safely. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/content/legal/types.ts` | Export LegalDoc type {title,lastUpdated,draftNotice,sections:{heading,body:string[]}[]} and a DRAFT_NOTICE constant = 'DRAFT — pending counsel review'. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/content/legal/privacy.ts` | Typed Privacy Policy DRAFT content module (engineer-drafted, text-only MVP scope: account data, email verification, optional analytics-with-consent, GDPR export/delete reference, no rich media). |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/content/legal/terms.ts` | Typed Terms of Service DRAFT content module (acceptable use, 13+ minimum age, account/termination, text-only content rules). |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/content/legal/cookie.ts` | Typed Cookie Policy DRAFT content module (essential vs optional analytics cookies, consent banner, how to change choice). |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/content/legal/children.ts` | Typed Children's Privacy DRAFT content module (under-13 blocked at registration, no parental-consent vendor flow, COPPA/age-gate statement aligned to CD2). |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/content/legal/index.ts` | Re-export the four LegalDoc modules and the LegalDoc type. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/legal/LegalDocPage.tsx` | Reusable presentational page: renders any LegalDoc with a prominent DRAFT banner, lastUpdated line, and rendered sections. Single source of legal layout. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/legal/PrivacyPage.tsx` | Route component rendering <LegalDocPage doc={privacy} />. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/legal/TermsPage.tsx` | Route component rendering <LegalDocPage doc={terms} />. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/legal/CookiePolicyPage.tsx` | Route component rendering <LegalDocPage doc={cookie} />. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/legal/ChildrenPrivacyPage.tsx` | Route component rendering <LegalDocPage doc={children} />. |
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/index.ts` | Export PrivacyPage, TermsPage, CookiePolicyPage, ChildrenPrivacyPage from the barrel so routes.tsx imports them like the other pages. |
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/app/routes.tsx` | Import the four legal pages from @/pages and add public routes: /privacy, /terms, /cookie-policy (+ /cookies alias via Navigate), /childrens-privacy. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/legal/LegalPages.test.tsx` | vitest: each legal route (mounted via createMemoryRouter with the REAL legal pages, other pages mocked) renders its doc title AND the visible 'DRAFT — pending counsel review' notice. |
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/components/Footer.tsx` | Replace dead /about link; keep /privacy + /terms (now real); add Cookie Policy (/cookie-policy) and Children's Privacy (/childrens-privacy) links so no footer link is dead. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/components/Footer.test.tsx` | vitest (render in MemoryRouter): footer renders anchors whose hrefs resolve to /privacy, /terms, /cookie-policy, /childrens-privacy and no link points at the removed /about. |
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/RegisterPage.tsx` | Replace the two bare hrefless <a>Terms</a>/<a>Privacy</a> anchors (lines ~404-405) with react-router <Link to="/terms"> / <Link to="/privacy">. |

### Task 1: Task 1 — Firebase analytics gate (CD1): no boot-time init, idempotent initAnalytics()

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/firebase.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/firebase.test.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/main.tsx`

- [ ] **Step 1 (test): Write src/lib/firebase.test.ts FIRST. Mock 'firebase/app' (initializeApp -> stub app) and 'firebase/analytics' (isSupported -> Promise<true>, getAnalytics -> stub). Assert: (a) after importing '@/lib/firebase', getAnalytics has NOT been called and initializeApp has NOT been called (zero side effects on import); (b) after `await initAnalytics()` getAnalytics called exactly once; (c) calling initAnalytics() twice still results in exactly one getAnalytics call (idempotent); (d) when measurementId is undefined OR isSupported resolves false, initAnalytics() resolves null and getAnalytics is not called.**

```
import { describe, it, expect, vi, beforeEach } from 'vitest'
const initializeApp = vi.fn(() => ({ name: 'app' }))
const getAnalytics = vi.fn(() => ({ kind: 'analytics' }))
const isSupported = vi.fn(async () => true)
vi.mock('firebase/app', () => ({ initializeApp }))
vi.mock('firebase/analytics', () => ({ getAnalytics, isSupported }))
beforeEach(() => { vi.clearAllMocks(); vi.resetModules() })
it('no analytics on import', async () => {
  await import('./firebase')
  expect(getAnalytics).not.toHaveBeenCalled()
})
it('initAnalytics is idempotent', async () => {
  const mod = await import('./firebase')
  await mod.initAnalytics(); await mod.initAnalytics()
  expect(getAnalytics).toHaveBeenCalledTimes(1)
})
```

  - Expected: FAILS to compile/run: initAnalytics export does not exist yet; current module also calls getAnalytics at import time.

- [ ] **Step 2 (impl): Rewrite firebase.ts: keep firebaseConfig. Remove top-level `export const firebaseApp = initializeApp(...)` and the eager `analyticsPromise`. Add module-level memo vars `let appMemo`, `let analyticsMemo: Promise<Analytics|null> | undefined`. getFirebaseApp() lazily initializes the app once. initAnalytics() returns analyticsMemo if set; else sets analyticsMemo = (config.measurementId ? isSupported().then(s => s ? getAnalytics(getFirebaseApp()) : null) : Promise.resolve(null)) and returns it. Add isAnalyticsInitialized() => analyticsMemo !== undefined.**

  - Expected: firebase.test.ts passes (npm run test -- src/lib/firebase.test.ts).

- [ ] **Step 3 (impl): Edit main.tsx: delete line `import './lib/firebase'`. Confirm no other module imports analyticsPromise/firebaseApp (grep already showed none) so removal is safe.**

  - Expected: App boots with zero analytics initialization; grep for analyticsPromise/firebaseApp returns no consumers.

- [ ] **Step 4 (run): Run the firebase suite and a typecheck.**

```
npm run test -- src/lib/firebase.test.ts && npx tsc -b --noEmit
```

  - Expected: Green; no type errors from the firebase changes.

- [ ] **Step 5 (commit): Commit: 'consent: stop firebase analytics from initializing at boot; add idempotent initAnalytics()' (plain message, no footers).**

### Task 2: Task 2 — Consent storage + age helper (pure modules, CD4 + adult gate)

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/storage.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/storage.test.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/age.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/age.test.ts`

- [ ] **Step 1 (test): Write storage.test.ts: beforeEach localStorage.clear(). writeConsent(true) then readConsent() returns {version:CONSENT_VERSION, analytics:true, ts:number}. Manually seed an older-version record -> readConsent() returns null (re-prompt on version bump). Seed malformed JSON -> readConsent() returns null without throwing. clearConsent() removes the key.**

  - Expected: FAILS: module/exports do not exist yet.

- [ ] **Step 2 (impl): Create storage.ts: export CONSENT_VERSION = 1, KEY = 'jokesfor-consent', ConsentRecord type. writeConsent(analytics) writes JSON {version:CONSENT_VERSION,analytics,ts:Date.now()}. readConsent() parses, try/catch -> null on error, returns null if parsed.version !== CONSENT_VERSION. clearConsent() removes KEY.**

  - Expected: storage.test.ts passes.

- [ ] **Step 3 (test): Write age.test.ts: isAdult(dob 25y ago)=>true; isAdult(dob exactly 18y ago today)=>true; isAdult(dob 17y ago)=>false; isAdult(null)/undefined/'not-a-date'=>false.**

  - Expected: FAILS: age module not created.

- [ ] **Step 4 (impl): Create age.ts: isAdult(dob?: string|null): boolean — parse dob; if invalid return false; compute age vs today (use date math, not just year subtraction) and return age >= 18.**

  - Expected: age.test.ts passes.

- [ ] **Step 5 (run): Run the consent unit suites.**

```
npm run test -- src/features/consent
```

  - Expected: storage + age tests green.

- [ ] **Step 6 (commit): Commit: 'consent: versioned localStorage record + isAdult age helper'.**

### Task 3: Task 3 — useConsent hook + ConsentBanner, mounted in App (CD4 + CD1 wiring)

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/useConsent.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/useConsent.test.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/ConsentBanner.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/ConsentBanner.test.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/features/consent/index.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/app/App.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api.ts`

- [ ] **Step 1 (impl): Add optional `date_of_birth?: string | null` to the User interface in src/lib/api.ts (cross-agent contract field) so the hook can read it without casts.**

  - Expected: Type compiles; existing code unaffected (field optional).

- [ ] **Step 2 (test): Write useConsent.test.tsx with renderHook. vi.mock('@/lib/firebase', () => ({ initAnalytics: vi.fn() })). vi.mock the auth store so useAuthStore.getState().user can be set per-test. beforeEach localStorage.clear(). Cases: (1) adult user -> act(accept) -> readConsent().analytics===true AND initAnalytics called once; (2) under-18/anon user -> act(accept) -> readConsent().analytics===true but initAnalytics NOT called; (3) act(reject) -> readConsent().analytics===false AND initAnalytics NOT called; (4) decided is false initially, true after a decision.**

  - Expected: FAILS: useConsent not created.

- [ ] **Step 3 (impl): Create useConsent.ts: useState seeded from readConsent(); decided = consent !== null. accept(): writeConsent(true); set state; read user via useAuthStore.getState().user; if isAdult(user?.date_of_birth) call initAnalytics(). reject(): writeConsent(false); set state. Return {consent, decided, accept, reject}.**

  - Expected: useConsent.test.tsx passes.

- [ ] **Step 4 (test): Write ConsentBanner.test.tsx: render <ConsentBanner/> (wrap in MemoryRouter for the cookie-policy <Link>). With empty localStorage the Accept and Reject buttons are visible; clicking Accept removes the banner and persists; clicking Reject removes + persists; pre-seeding a current-version record -> banner renders nothing.**

  - Expected: FAILS: ConsentBanner not created.

- [ ] **Step 5 (impl): Create ConsentBanner.tsx: const {decided, accept, reject} = useConsent(); if (decided) return null; render a fixed bottom bar: short essential-cookies copy, a <Link to='/cookie-policy'>Cookie Policy</Link>, and Accept / Reject buttons (Reject = essential only). No toggles.**

  - Expected: ConsentBanner.test.tsx passes.

- [ ] **Step 6 (impl): Create features/consent/index.ts barrel (useConsent, ConsentBanner, readConsent/writeConsent/clearConsent, CONSENT_VERSION, isAdult). Edit App.tsx to render <ConsentBanner/> inside <Providers> next to <AppRoutes/>.**

  - Expected: App renders banner app-wide; typecheck clean.

- [ ] **Step 7 (run): Run consent suite + typecheck.**

```
npm run test -- src/features/consent && npx tsc -b --noEmit
```

  - Expected: All consent tests green; no type errors.

- [ ] **Step 8 (commit): Commit: 'consent: Accept/Reject banner gated to analytics-on-consent-and-adult, mounted app-wide'.**

### Task 4: Task 4 — DRAFT legal content modules + pages + routes (CD5)

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/content/legal/types.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/content/legal/privacy.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/content/legal/terms.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/content/legal/cookie.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/content/legal/children.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/content/legal/index.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/legal/LegalDocPage.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/legal/PrivacyPage.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/legal/TermsPage.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/legal/CookiePolicyPage.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/legal/ChildrenPrivacyPage.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/index.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/app/routes.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/legal/LegalPages.test.tsx`

- [ ] **Step 1 (impl): Create content/legal/types.ts: export LegalDoc {title,lastUpdated,draftNotice,sections:{heading,body:string[]}[]} and DRAFT_NOTICE = 'DRAFT — pending counsel review'.**

  - Expected: Type module compiles.

- [ ] **Step 2 (impl): Create the four content modules (privacy/terms/cookie/children).ts, each default-exporting a LegalDoc with draftNotice = DRAFT_NOTICE, a real lastUpdated date, and complete engineer-drafted sections scoped to the TEXT-ONLY MVP (no rich-media/CSAM/moderation claims). children.ts states under-13 are blocked at registration and no parental-consent vendor flow exists (per CD2). Create content/legal/index.ts re-exporting all four + the type.**

  - Expected: All modules compile; each contains the DRAFT notice string.

- [ ] **Step 3 (impl): Create pages/legal/LegalDocPage.tsx: props {doc: LegalDoc}; renders the draftNotice prominently (e.g. role='note'), the title, 'Last updated: {lastUpdated}', then each section heading + paragraphs. Create the four thin route components PrivacyPage/TermsPage/CookiePolicyPage/ChildrenPrivacyPage rendering <LegalDocPage doc={...}/>.**

  - Expected: Components compile.

- [ ] **Step 4 (impl): Edit pages/index.ts to export the four legal pages. Edit app/routes.tsx: import them from @/pages; add public routes { path:'/privacy' }, { path:'/terms' }, { path:'/cookie-policy' }, { path:'/cookies', element:<Navigate to='/cookie-policy' replace/> }, { path:'/childrens-privacy' }.**

  - Expected: Routes registered; typecheck clean.

- [ ] **Step 5 (test): Write LegalPages.test.tsx: mock @/pages for the NON-legal pages but use the real legal pages (partial: importActual then spread, overriding only non-legal). Simpler: build a minimal routes array OR follow routes.test.tsx and mock @/pages while providing the real legal components. For each of /privacy /terms /cookie-policy /childrens-privacy, renderAt(path) via createMemoryRouter(routes) and assert the doc title AND 'DRAFT — pending counsel review' are in the document. Also assert /cookies redirects to the cookie policy.**

  - Expected: FAILS before routes exist, then PASSES once routes wired.

- [ ] **Step 6 (run): Run legal suite + typecheck.**

```
npm run test -- src/pages/legal && npx tsc -b --noEmit
```

  - Expected: All four routes render DRAFT content; redirect works; no type errors.

- [ ] **Step 7 (commit): Commit: 'legal: DRAFT privacy/terms/cookie/childrens pages with routes'.**

### Task 5: Task 5 — Fix dead/bare legal links (Footer + RegisterPage)

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/components/Footer.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/components/Footer.test.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/RegisterPage.tsx`

- [ ] **Step 1 (test): Write Footer.test.tsx: render <Footer/> inside <MemoryRouter>. Assert links resolve to /privacy, /terms, /cookie-policy, /childrens-privacy (query by role 'link' name and check href) and that NO link points to /about (the dead route is gone).**

  - Expected: FAILS: footer still has /about and lacks cookie/children links.

- [ ] **Step 2 (impl): Edit Footer.tsx: remove the /about <Link>; keep Privacy(/privacy) + Terms(/terms); add Cookie Policy(/cookie-policy) and Children's Privacy(/childrens-privacy) links.**

  - Expected: Footer.test.tsx passes; all footer links target real routes.

- [ ] **Step 3 (impl): Edit RegisterPage.tsx lines ~404-405: replace bare <a style={{color:'#6A1CF6'}}>Terms</a> / <a ...>Privacy</a> with <Link to='/terms' style=...>Terms</Link> / <Link to='/privacy' ...>Privacy</Link> (Link already imported from 'react-router').**

  - Expected: Register footer legal links navigate to real routes; existing RegisterPage tests still pass.

- [ ] **Step 4 (run): Run the full frontend suite + typecheck + lint as the final gate.**

```
npm run test && npx tsc -b --noEmit && npm run lint
```

  - Expected: Entire vitest suite green (including pre-existing routes.test.tsx and RegisterPage.verify.test.tsx), no type errors, lint clean.

- [ ] **Step 5 (commit): Commit: 'fix: wire dead legal links in footer and registration to real routes'.**

**Decisions in this plan:**

- *How should 'is adult' be determined on the frontend given the User type has no date_of_birth field yet?* → Add optional `date_of_birth?: string|null` to the User interface in src/lib/api.ts (the cross-agent contract field the backend Work-Stream B will populate on /auth/user/). Compute adult status with a pure isAdult(dob) helper that returns false for null/invalid/under-18. This makes analytics default OFF for anon and DOB-less users exactly as CD1 requires, and seamlessly turns on for adults once the backend ships the field — no frontend change needed later.
- *localStorage for consent vs the auth store's sessionStorage?* → Use localStorage per CD4 (the decision must persist across sessions/tabs, unlike the auth store which intentionally uses sessionStorage). Key 'jokesfor-consent'. Treat a record as a valid decision only when version === CONSENT_VERSION so bumping the constant re-prompts everyone.
- *Where should the ConsentBanner mount so it shows app-wide without coupling to the legacy Layout?* → Mount it once in App.tsx inside <Providers>, as a sibling of <AppRoutes/>. The canonical routes use FlowAppShell (not the legacy Layout), so putting it in App guarantees it appears on every route, including /register and the legal pages, regardless of shell.
- *Should accept() fire analytics for a non-adult who clicks Accept?* → No. Persist analytics:true (their stated cookie choice) but do NOT call initAnalytics() unless isAdult is true — analytics requires consent AND adult age (CD1). If/when such a user later supplies an adult DOB, the next accept (or an app-start reconciliation, out of scope here) can initialize. For this work-stream, gate strictly at accept() time.
- *Should the firebase app itself be lazy too, or only analytics?* → Make both lazy. Since nothing else in src/ imports firebaseApp/analyticsPromise (verified via grep), there is no reason to call initializeApp at boot. Lazily create the app inside getFirebaseApp() the first time initAnalytics() needs it. This guarantees the module import has zero side effects, which is the cleanest thing to assert in the boot test.
- *Routes for the cookie page — /cookie-policy vs /cookies?* → Canonical /cookie-policy (descriptive, matches the doc), with /cookies as a Navigate-redirect alias for resilience. Footer and ConsentBanner link to the canonical /cookie-policy.
- *How to render legal copy — Markdown/MDX or typed TS?* → Typed TS content modules under src/content/legal/*.ts per CD5 (no new deps, type-checked structure, trivial to test). A single LegalDocPage renders the shared LegalDoc shape so all four pages stay consistent and the DRAFT notice is guaranteed present.

**Risks:**

- Cross-stream coupling: isAdult depends on the backend adding date_of_birth to the /auth/user/ payload (Work-Stream B). Until then every authed user reads as non-adult and analytics stays off — safe by design, but coordinate so the field name matches exactly ('date_of_birth', ISO 'YYYY-MM-DD').
- Removing `import './lib/firebase'` from main.tsx is only safe because no module imports firebaseApp/analyticsPromise today (verified by grep). If a later branch re-adds such an import, analytics could re-initialize at boot — keep the boot test (getAnalytics not called on import) as the regression guard.
- measurementId is currently present in .env, so initAnalytics() will actually hit Firebase in real builds once called; ensure tests mock firebase/analytics so the suite never makes network calls.
- Mounting ConsentBanner in App.tsx means it overlays every page including auth/legal screens; verify z-index/position:fixed doesn't cover critical buttons on small screens (visual check, not covered by unit tests).
- Legal copy is engineer-drafted DRAFT only; the visible 'DRAFT — pending counsel review' notice is load-bearing for compliance posture — the LegalPages test asserts its presence so it can't be accidentally removed.
- The installed React is 19.2 (package.json) despite the brief saying React 18; renderHook/act patterns and react-router 7 APIs used here are compatible, but follow the existing test files' import style ('react-router', @testing-library/react) rather than introducing react-dom/test-utils.
