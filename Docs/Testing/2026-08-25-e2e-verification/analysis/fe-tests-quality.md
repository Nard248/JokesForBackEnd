# Frontend Testing & Quality Map — `fe-tests-quality`

Repo: `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend` (React 19 / Vite 7.3.1 / TS 5.9.3 / Vitest 2.1.9 / jsdom 25.0.1 / Playwright 1.57.0 / ESLint 9.39.2)
Analysis date: 2026-08-25. All facts below are from code; docs that disagree are called out.

---

## 1. Headline numbers

| Metric | Value | Source |
|---|---|---|
| Vitest test files | **109** (108 real + `src/test/harness.test.tsx` smoke) | `find src -name '*.test.ts*'` |
| Vitest test cases (`it(`/`test(` at line start) | **796** | grep count |
| Test LOC | 12,569 | `wc -l` |
| App source (non-test) | 238 files / 32,186 LOC | |
| Playwright spec files | **1** (`e2e/example.spec.ts`, 6 tests, dated 2026-01-12) | |
| Skipped/todo/only tests | **0** (`it.skip`, `test.skip`, `describe.skip`, `.todo`, `.only`, `xit` — none found) | grep |
| MSW | **not used** (no dependency, no `__mocks__` dirs) | `package.json` |
| Coverage tooling | **none** (`@vitest/coverage-*` not installed; no `coverage` block in `vitest.config.ts`) | `node_modules/@vitest` |
| ESLint (read-only run, today) | **0 errors, 26 warnings** across 353 files | `npx eslint . -f json` |
| `tsc -p tsconfig.app.json --noEmit` | clean (no output) | read-only run |
| `prettier --check .` | **279 files fail** (Prettier not enforced in CI) | read-only run |

---

## 2. Vitest configuration

`/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/vitest.config.ts` (18 lines):

```ts
import { defaultExclude, defineConfig } from 'vitest/config'
plugins: [react() as any]                 // eslint-disable for the cast
resolve.alias: { '@': path.resolve(__dirname, './src') }
test: {
  globals: true,                          // describe/it/expect are globals
  environment: 'jsdom',
  setupFiles: ['./src/test/setup.ts'],
  exclude: [...defaultExclude, 'e2e/**'], // keeps Playwright specs out of vitest
}
```

- `vite.config.ts` is separate (plugins react + tailwindcss, same alias). Vitest does **not** load the Tailwind plugin, so CSS is not processed in tests.
- `tsconfig.app.json` line 8: `"types": ["vite/client", "vitest/globals"]` — gives global `describe/it/expect/vi` types. Many tests still import from `'vitest'` explicitly (both styles coexist).
- `tsconfig.node.json` includes `vite.config.ts` and `vitest.config.ts` only.
- No `test.include` override → Vitest default glob `**/*.{test,spec}.?(c|m)[jt]s?(x)`.
- No `coverage`, `reporters`, `testTimeout`, `pool`, or `css` settings → all defaults (5 s test timeout, `threads`/`forks` default pool).
- Vitest 2.1.9 with Vite 7.3.1: Vitest 2.x does not declare a `vite` peerDependency at all (`node_modules/vitest/package.json` peerDeps: `@edge-runtime/vm, @types/node, happy-dom, jsdom, @vitest/browser, @vitest/ui`), so no peer conflict, but it is an old major sitting on a new Vite.

### Setup files — `src/test/`
- `src/test/setup.ts` (1 line): `import '@testing-library/jest-dom/vitest'` — that is the **entire** global setup. No MSW server, no global fetch stub, no `matchMedia`/`IntersectionObserver`/`ResizeObserver` polyfills, no `afterEach(cleanup)` (RTL auto-cleanup works because `globals: true`).
- `src/test/harness.test.tsx` (6 lines): single smoke test `render(<div>hello</div>)` → `toBeInTheDocument()`.
- **No shared render helper / test-utils module exists.** Every test that needs providers builds its own `wrapper` (16 files define `wrapper`/`makeWrapper`, 29 files construct `QueryClientProvider`, 37 use `MemoryRouter`/`createMemoryRouter`/`RouterProvider`, 8 wrap with `HelmetProvider`).

### Env handling in tests
Vitest (via Vite) loads the repo-root `.env`. Locally `.env` has `VITE_API_URL=http://localhost:8000/api/v1` and `VITE_USE_MOCKS=true`; in CI no `.env` exists so `VITE_API_URL` is undefined. Both resolve to the **mock path** because of the shared idiom:

```ts
// src/lib/api-adapter.ts:34, src/lib/telemetry.ts:55, src/features/daily-reads/api.ts:16,
// src/features/tips/TipButton.tsx:11, src/features/telemetry/recordShare.ts:6, src/pages/BillingPage.tsx:19
const USE_MOCKS = !import.meta.env.VITE_API_URL || import.meta.env.VITE_USE_MOCKS === 'true'
```

`src/features/create/adapter.ts:22` uses a separate flag `VITE_USE_REAL_CREATE === 'true'` (unset locally and in vitest → mock content store).

Tests that need the real-API branch flip it with `vi.stubEnv` (+ `vi.resetModules()` + dynamic import because the flag is evaluated at module load): `src/lib/api-adapter.test.ts:29-41`, `src/lib/telemetry.test.ts:24-29`, `src/features/daily-reads/useDailyReads.test.tsx:28-29`, and one more (4 files stub `VITE_API_URL`, 4 stub `VITE_USE_MOCKS`).

**Risk:** if a developer sets `VITE_USE_MOCKS=false` (or `VITE_USE_REAL_CREATE=true`) in `.env`, tests that do not stub env and do not mock `@/lib/api` (e.g. `src/features/create/queries.test.tsx`, `mutations.test.tsx`, `adapter.test.ts`) would attempt real axios calls to `localhost:8000` and fail/hang. The suite is env-sensitive by construction rather than isolated.

---

## 3. Test inventory by directory

| Directory | Files | Notable |
|---|---|---|
| `src/app` | 2 | `App.test.tsx` (4 tests, mocks `axios` module wholesale at lines 104-116 so `AuthProvider` bootstrap rejects instantly); `routes.test.tsx` (10 tests: imports real `routes` array into `createMemoryRouter`, mocks all of `@/pages`, `ProtectedRoute`, `GuestOnlyRoute`, `Layout`; asserts `/submit→/create/new`, `/drafts→/create`, `/create/*`, `/collections/*` resolution) |
| `src/components` | 16 | `FlowAppShell` (12), `FlowJokeCard.{anon,paywall,jokeToFlowData}`, `JokeRenderer.{format,locked,media,wave2,default}` (40 tests total on the renderer), `NotificationsPanel` (10), `AppealButton`, `ReportJokeButton`, `ProfileMenu`, `PublicIdentityEditor`, `Footer`, `JokeCard` (legacy) |
| `src/components/ui` | 6 | modal, otp-input, radio-group, skeleton, textarea, toast — pure component tests |
| `src/features/auth` | 2 | `api.verify.test.tsx` (useVerifyEmail → auth store), `parseAuthError.test.ts` |
| `src/features/consent` | 4 | `age.test.ts` (13), `storage.test.ts` (10), `useConsent.test.tsx` (9), `ConsentBanner.test.tsx` (5) |
| `src/features/create` | 13 | `validation.test.ts` (22), `editor-state.test.ts` (27), `api.test.ts` (16, DTO mapping), `autosave.test.tsx` (12, fake timers, 560 lines), `barrel.test.ts` (21 export-existence checks), `mock.test.ts` (13), `store`, `queries`, `mutations`, `adapter`, `analytics`, `media-draft`, `types` (1 trivial) |
| `src/features/create/components` | 13 | one file per editor-chrome component (AgeRatingRadio, ChangeFormatModal, DeleteDraftModal, DialogueLine, DraftCard, EditorShell, FormatTile, PreviewPane, PublishedStats, SaveIndicator, StatusBadge, SubmitConfirmModal, TagPicker) |
| `src/features/create/editors` | 9 | one per format editor (Audio, Image, Knock (12), Observational, OneLiner, SetupPunchline, Story, Video) + `registry` |
| `src/features/daily-reads` | 2 | `useDailyReads.test.tsx` (paywall status hook; 404 → no cap), `DailyReadsNudge` |
| `src/features/follows` | 1 | `FollowButton` (6) |
| `src/features/telemetry` | 3 | `useDwell` (5), `useImpression` (4, fake timers + IntersectionObserver stub), `useWatchTracking` (12) |
| `src/features/tips` | 2 | `TipButton` (9, Stripe checkout URL redirect), `TipsReceived` (6) |
| `src/hooks` | 2 | `useBreakpoint` (7, matchMedia stub), `usePrefersReducedMotion` (4) |
| `src/lib` | 4 | `api-adapter.test.ts` (**50 tests, 698 lines** — largest; real vs mock path per adapter), `telemetry.test.ts` (24; sendBeacon/fetch fallback, consent/age gate), `dailyReset.test.ts` (7), `firebase.test.ts` (8, mocks `firebase/app` + `firebase/analytics`) |
| `src/lib/seo` | 2 | `Seo.test.tsx` (13, Helmet meta/OG/canonical/JSON-LD), `jsonld.test.ts` (3) |
| `src/pages` | 26 | `BillingPage` (27), `CreatorInsightsPage` (23), `SubmissionDetailPage` (14), `CreatorHubPage` (13), `CreatorProfilePage` (12), `ExplorePage` (10), `VerifyEmailPage` (9), `SearchPage` (7), `DailyJokePage`, `FormatPickerPage`, `LandingPage`, `LibraryPage` (6 each), `EditorPage`, `FavoritesPage`, `SettingsPage` (5), `GoogleCallbackPage`, `ProfilePage` (4), `JokeDetailPage.{locked,media}`, `RegisterPage.{agegate,googledob,verify}`, `LoginPage`, `HomePage`, `CollectionsPage`, `CollectionDetailPage` (2-3) |
| `src/pages/legal` | 1 | `LegalPages.test.tsx` (5) |
| `src/test` | 1 | harness smoke |

### Kinds of tests present
1. **Pure unit** (no DOM): validation, editor-state, age, storage, dailyReset, parseAuthError, jsonld, api DTO mapping, api-adapter mapping, telemetry queue/gate, mock store.
2. **Hook tests** via `renderHook` + `QueryClientProvider` wrapper: useVerifyEmail, useDailyReads, useAutosave, useFormats/useDrafts, mutations, useDwell/useImpression/useWatchTracking, useConsent, useBreakpoint, usePrefersReducedMotion.
3. **Component tests** via RTL `render` + `userEvent` (13 files use `@testing-library/user-event`; the rest use `fireEvent`).
4. **Page tests**: render a page inside `MemoryRouter` (+ QueryClient/Helmet) with heavy `vi.mock` of `@/components/FlowAppShell` (19 files), `@/features/auth` (16), `@/lib/telemetry` (9), feature hooks, and the page's data layer. Assertions target visible text/roles and mocked-mutation calls.
5. **Route-table tests** (`routes.test.tsx`) — the only test that exercises `createMemoryRouter` on the production `routes` array.
6. **App composition test** (`App.test.tsx`) — consent banner + router mount.
7. **Export-surface tests** (`barrel.test.ts`, `types.test.ts`) — assert named exports exist.

### Mocking strategy (manual `vi.mock`, no MSW)
57 of 108 test files call `vi.mock`. Most-mocked modules (count of files):
`@/components/FlowAppShell` 19, `@/features/auth` 16, `react-router` 9 (partial — usually `useNavigate`/`useParams`), `@/lib/telemetry` 9, `@/features/auth/store` 7, `@/lib/api` 6, `@/features/saved-jokes` 6, `@/components/ui/toast` 6, `@/components/FlowJokeCard` 6, `@/features/telemetry` 5, `@/lib/firebase` 4, `@/features/{reactions,jokes,create}` 4 each, `@/pages` 3, `@/app/providers/{ProtectedRoute,GuestOnlyRoute}` 3, `@/components/Layout` 3, `axios` 1 (`App.test.tsx`), `@/lib/axios` 1 (`telemetry.test.ts`).

Pattern is **module-boundary mocking at the hooks/adapter layer**, never at HTTP level. Partial mocks use `vi.mock('@/lib/api', async (orig) => ({ ...(await orig()), dailyReadsApi: {...} }))` (e.g. `useDailyReads.test.tsx:9-12`).

Browser-API stubs are done per-file, not globally: `IntersectionObserver`/`matchMedia`/`ResizeObserver`/`scrollIntoView` stubs appear in 5 files (`useDwell`, `useImpression`, `JokeRenderer.wave2`, `usePrefersReducedMotion`, `useBreakpoint`). `vi.stubGlobal('navigator', { sendBeacon })` and `vi.stubGlobal('fetch', reject)` in `telemetry.test.ts:37,165`.

Fake timers: 3 files (`useImpression.test.tsx`, `autosave.test.tsx`, `SearchPage.test.tsx`). `autosave.test.tsx:1-10` documents the `toFake: ['setTimeout','clearTimeout']` + `advanceTimersByTimeAsync` pattern and the `waitFor` deadlock caveat.

Console spying: 1 file (`features/create/analytics.test.ts`). `localStorage.clear()` in `beforeEach` where relevant (`App.test.tsx:120`).

### Network dependence
- **No Vitest test performs a real network call** when run with the committed `.env` or in CI. Verified: every page/component test either mocks the data layer or exercises the in-memory mock APIs (`src/lib/mock-api.ts`, `src/features/create/mock.ts`). The URL literals found in tests (`cdn.example.com`, `http://x/...`, `checkout.stripe.com/demo`) are fixture data only.
- Tests that go through the **mock API layer** and thus incur real `setTimeout` delays: `features/create/queries.test.tsx`, `mutations.test.tsx`, `adapter.test.ts` (mock delay 100-400 ms per call at `src/features/create/mock.ts:15-16`); `src/lib/mock-api.ts:38` uses 400-800 ms delays for any test that reaches it unmocked. These make the suite slower and are the env-sensitive files noted in §2.
- Files with **no API mock at all** (safe — pure render): `Footer`, `JokeCard` (uses `mockAuthors` from `@/lib/mock-data`), `JokeRenderer.{format,locked,media,default}`, `JokeRenderer.wave2` (mocks only telemetry), and all `ui/*` tests.
- **Build-time network**: `scripts/gen-sitemap.mjs` (npm `prebuild` hook) fetches `${backend}/sitemap.xml` from the **prod backend** during `npm run build` — including in CI (`ci.yml` sets `VITE_API_URL` to prod). It is fail-soft (warns and exits 0 on any failure, lines 17-23, 105-108) and writes `public/sitemap.xml` (gitignored).
- **Playwright** starts the Vite dev server (`webServer.command: 'npm run dev'`) and drives the real app; with `.env` `VITE_USE_MOCKS=true` the app uses in-memory mocks, but auth bootstrap (`AuthProvider` → `axios.post(.../auth/token/refresh/)`) and CSRF fetch would still hit `VITE_API_URL` (localhost:8000) and fail silently.

---

## 4. Playwright e2e

`/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/playwright.config.ts` (34 lines):
- `testDir: './e2e'`, `fullyParallel: true`, `forbidOnly: !!CI`, `retries: CI ? 2 : 0`, `workers: CI ? 1 : undefined`, `reporter: 'html'`.
- `use.baseURL: 'http://localhost:5173'`, `trace: 'on-first-retry'`, `screenshot: 'only-on-failure'`.
- Projects: `chromium` (Desktop Chrome) and `mobile` (Pixel 5, Chromium). No Firefox/WebKit.
- `webServer: { command: 'npm run dev', url: 'http://localhost:5173', reuseExistingServer: !CI, timeout: 120s }`.

`e2e/example.spec.ts` (72 lines, 6 tests, last touched commits `e25b83c`/`73f0b4b`, Jan 2026):
- `Homepage` (3): expects `h1` containing "Find Your" / "Perfect Joke", placeholder "Search for jokes about...", button "Dad Jokes"; header link "Jokes For", desktop links Daily/Saved or mobile `aria-label="Toggle menu"`; navigate to `/daily` and see "Daily Joke".
- `Mobile Navigation` (1): 375×667 viewport, toggle menu.
- `Auth Pages` (1): `/login` shows text "Login" and `header` is not visible.

**All e2e tests are stale against current code** (docs/code disagree with the spec's assumptions):
- Current anon landing `src/pages/LandingPage.tsx:96-98` h1 = "You're ten seconds from your new favorite joke." — not "Find Your Perfect Joke".
- `aria-label="Toggle menu"` exists only in `src/components/Header.tsx:86`, which is **not imported anywhere** (dead legacy component); live layouts are `layout/DesktopHeader.tsx`, `layout/MobileHeader.tsx`, `FlowAppShell.tsx`.
- "Search for jokes about..." placeholder and "Dad Jokes" button: not present in `src/` (grep returns nothing).
- "Daily Joke" text exists only in `SettingsPageLegacy.tsx:123`.
- Conclusion: `npm run e2e` would fail today; it is not wired into CI.

`playwright-report/index.html` (521 KB) and `test-results/.last-run.json` (`{"status":"passed","failedTests":[]}`) are dated 2026-01-12 — the last successful e2e run was against the pre-pivot template app. Both dirs are gitignored (`.gitignore:35-36`).

Browser binaries: Playwright 1.57 wants `chromium@1200` (`playwright-core/browsers.json`); `~/Library/Caches/ms-playwright` has `chromium-1200` and `chromium_headless_shell-1200` present, so the runner can start locally.

Spec disagreement: `Docs/superpowers/specs/2026-05-23-content-creation-frontend-design.md:49,209` says "Repo has Playwright e2e only; no Vitest/Jest, no existing unit tests" — **stale**; Vitest+RTL were added 2026-05-23 (`vitest.config.ts`, `src/test/*` mtime May 23) and now hold 796 tests.

---

## 5. Lint / format / types

### ESLint — `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/eslint.config.js`
- Flat config; `globalIgnores(['dist', '.remember'])`; applies to `**/*.{ts,tsx}` (JS files such as `scripts/gen-sitemap.mjs` are **not** linted).
- Extends: `@eslint/js` recommended, `typescript-eslint` recommended (**not** type-checked), `eslint-plugin-react-hooks` v7 `flat.recommended`, `eslint-plugin-react-refresh` `vite`.
- `ecmaVersion: 2020`, `globals.browser`.
- Explicit rule overrides:
  - `@typescript-eslint/no-unused-vars`: **error**, with `argsIgnorePattern/varsIgnorePattern/caughtErrorsIgnorePattern: '^_'`.
  - `react-refresh/only-export-components`: **warn** (demoted; comment explains shadcn/route-config exports).
  - `react-hooks/set-state-in-effect`: **warn** (demoted; comment says re-promote after cleanup).
- Everything else from the presets stays at preset severity (errors for recommended rules; `react-hooks/exhaustive-deps` is `warn` in the preset; `react-hooks/rules-of-hooks` is error).
- Current state (read-only run): **0 errors / 26 warnings** — `react-refresh/only-export-components` 13, `react-hooks/set-state-in-effect` 10, `react-hooks/exhaustive-deps` 3. Worst files: `src/components/JokeRenderer.tsx` (6), `src/pages/FavoritesPage.tsx` (3), `src/pages/LibraryPage.tsx` (3), `ExplorePage.tsx` (2), `SearchPage.tsx` (2).
- `npm run lint` = `eslint .` (no `--max-warnings 0`), so warnings never fail CI.

### Prettier
- `.prettierrc`: `semi: false, singleQuote: true, trailingComma: 'all', printWidth: 100, tabWidth: 2`.
- `.prettierignore`: `dist node_modules build coverage playwright-report test-results`.
- Scripts: `format` (`prettier --write .`), `format:check` (`prettier --check .`).
- **Not in CI** (commit `e0afac6` message: "format:check … isn't wired into the CI gate yet, to avoid a mass-reformat diff"). Today `prettier --check .` reports 279 files with style issues, including `tsconfig.json` and `vite.config.ts`.

### TypeScript
- `npm run build` = `tsc -b && vite build` — project references (`tsconfig.json` → `tsconfig.app.json`, `tsconfig.node.json`), `strict: true`, `noUnusedLocals`, `noUnusedParameters`, `erasableSyntaxOnly`, `noFallthroughCasesInSwitch`, `noUncheckedSideEffectImports`, `verbatimModuleSyntax`, `moduleResolution: bundler`, `noEmit`. `tsconfig.app.json` `include: ["src"]` → **test files are type-checked by the build** (they live in `src/`).
- `tsc -p tsconfig.app.json --noEmit` and `tsc -p tsconfig.node.json --noEmit` both clean today.

---

## 6. CI / CD workflows (`.github/`)

### `.github/workflows/ci.yml` (added 2026-08-04, commit `e0afac6`)
- Triggers: `pull_request`, and `push` to every branch **except `main`**.
- Single job `test` on `ubuntu-latest`: `actions/checkout@v6` → `actions/setup-node@v6` (node 24, npm cache) → `npm ci` → `npm run lint` → `npm test -- --run` → `npm run build` (with `VITE_API_URL` = prod backend, `VITE_USE_MOCKS='false'`, placeholder Firebase vars, `VITE_USE_REAL_PREFERENCES='true'`, `VITE_USE_REAL_CREATE='true'`).
- Note: `npm test -- --run` expands to `vitest run --run` (harmless duplicate flag).
- The env vars are only set on the **build** step; the vitest step runs with no `VITE_*` env → mock path everywhere (see §2).
- Not run: Playwright, prettier, `tsc` separately (covered by `tsc -b` inside build), coverage thresholds.
- **Gap:** pushes directly to `main` skip `ci.yml` entirely; only the deploy workflow runs there, which does not lint or test.

### `.github/workflows/firebase-hosting-merge.yml`
- On push to `main`: checkout → `npm ci && npm run build` (real Firebase secrets, `VITE_USE_MOCKS` default `'false'`, `VITE_USE_REAL_PREFERENCES`/`VITE_USE_REAL_CREATE` default `'true'`) → `FirebaseExtended/action-hosting-deploy@v0` with `channelId: live`, `projectId: jokesforfront`. No Node version pinned (comment explains the floating `@v0`).

### `.github/workflows/firebase-hosting-pull-request.yml`
- On `pull_request` from same-repo branches: same build (but **does not set `VITE_USE_REAL_CREATE`** — the PR preview therefore builds with the mock create path, unlike merge/CI) → preview channel deploy.

### `.github/dependabot.yml`
- Weekly `npm` and `github-actions` updates.

### Firebase hosting (`firebase.json`)
- `public: dist`, SPA rewrite `** → /index.html`, immutable 1-year cache on hashed assets, `no-cache` on `index.html`.

---

## 7. Exact local commands

```bash
cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend
npm ci                                   # Node 24 to match CI (package.json has no "engines")

# Unit / component / route tests (Vitest, jsdom)
npm test                                 # = vitest run  (what CI runs, minus the redundant --run)
npm run test:watch                       # = vitest (watch mode)
npx vitest run src/pages/BillingPage.test.tsx           # single file
npx vitest run -t "redirects"                          # filter by name
npx vitest run --reporter=verbose

# Lint / format / types
npm run lint                             # eslint .   (0 errors, 26 warnings today; warnings don't fail)
npx eslint . --max-warnings 0            # strict variant (would fail today)
npm run format:check                     # prettier --check .  (279 files fail today; NOT in CI)
npm run format                           # prettier --write .  (mass reformat — deliberately not done)
npx tsc -b                               # type-check both projects (writes node_modules/.tmp/*.tsbuildinfo)
npx tsc -p tsconfig.app.json --noEmit    # app-only, no buildinfo write

# Build (runs prebuild sitemap fetch against VITE_API_URL / prod fallback; fail-soft)
npm run build                            # tsc -b && vite build
npm run preview

# Playwright e2e (currently stale — will fail on the first homepage assertion)
npx playwright install chromium          # if browsers missing
npm run e2e                              # playwright test  (boots `npm run dev` on :5173)
npm run e2e:ui / e2e:headed / e2e:debug
npx playwright show-report               # opens playwright-report/index.html

# Full CI-equivalent gate
npm ci && npm run lint && npm test && npm run build
```

Environment: copy `.env.example` → `.env`. For Vitest, leave `VITE_USE_MOCKS=true` (or unset `VITE_API_URL`); setting `VITE_USE_MOCKS=false` or `VITE_USE_REAL_CREATE=true` would make un-mocked adapter tests hit `localhost:8000`.

---

## 8. Coverage gaps (by feature/page)

- **Pages with no test file:** `DraftsPage`, `FlowCanvasPage`, `FlowPage`, `ForgotPasswordPage`, `NotFoundPage`, `OnboardingPage`, `PackDetailPage`, `SubmitJokePage`, `TrendingPage`, and all `*Legacy` pages (`HomePageLegacy`, `TrendingPageLegacy`, `FavoritesPageLegacy`, `DraftsPageLegacy`, `ProfilePageLegacy`, `SettingsPageLegacy`, `SubmitJokePageLegacy`). `FlowPage`/`FlowCanvasPage` (the main reader feed) having zero direct tests is the most significant gap; `FlowJokeCard` and `FlowAppShell` are tested in isolation.
- **Feature dirs with zero test files** (some are covered indirectly via component/page tests): `appeals` (via `AppealButton.test`), `billing` (via `BillingPage.test`), `collections`, `creator-insights`/`insights` (via `CreatorInsightsPage.test`), `daily-joke` (via `DailyJokePage.test`), `drafts`, `favorites` (via `FavoritesPage.test`), `jokes`, `moderation` (via `ReportJokeButton.test`), `mystery-box`, `notifications` (via `NotificationsPanel.test`), `packs`, `preferences`, `profile`, `reactions`, `recently-viewed`, `saved-jokes`, `streak`, `today-status`, `trending`, `vibes`.
- **`src/lib/axios.ts`** (token refresh queue, CSRF fetch/retry-once on 403, 401 refresh) has **no direct tests**; `App.test.tsx` mocks `axios` entirely and `telemetry.test.ts` mocks `@/lib/axios`.
- **`src/lib/api.ts`** (the axios endpoint catalogue) has no tests beyond being mocked.
- **Auth store** (`src/features/auth/store`) is only exercised indirectly (`api.verify.test.tsx`); `ProtectedRoute`/`GuestOnlyRoute` are always mocked to passthrough — redirect-on-unauthenticated behaviour is untested.
- No accessibility (axe) tests, no visual/snapshot tests (`toMatchSnapshot` not used), no coverage thresholds.
- Only 1 axios-level mock; nothing verifies request shapes/headers (Authorization/X-CSRFToken) end-to-end.

---

## 9. Quality observations

1. Suite is broad (796 tests) but built entirely on manual `vi.mock` of internal modules; no HTTP-level contract tests, so backend response-shape drift is caught only where adapters are tested against literal fixtures (`api-adapter.test.ts`).
2. Test files are type-checked by `tsc -b` in the build (they are under `src/`), which is a useful extra gate but also means test-only type errors break the production build.
3. `npm run lint` passes with 26 warnings; two rule demotions are explicitly labelled as a ratchet to be re-promoted.
4. Prettier is configured but 279 files are non-conformant and it is not enforced — formatting-only diffs are likely if anyone runs `npm run format`.
5. Playwright infrastructure exists but the single spec is dead code relative to the current UI; `playwright-report`/`test-results` on disk are 7-month-old artifacts.
6. `ci.yml` does not run on `main` pushes; the merge-deploy workflow builds without lint/test, so a direct push to `main` can deploy untested code.
7. `firebase-hosting-pull-request.yml` omits `VITE_USE_REAL_CREATE`, so PR previews exercise the mock create adapter while prod uses the real one.
8. `.env` (untracked, present locally) is loaded by Vitest; test determinism depends on it keeping `VITE_USE_MOCKS=true`.
9. `README.md` is the untouched Vite template; there is no project-level testing doc. The only design doc that discusses testing (`Docs/superpowers/specs/2026-05-23-content-creation-frontend-design.md` §8) predates Vitest and is stale.
10. Vitest 2.1.9 is one major behind (3.x) while Vite is 7.x; works today, but Dependabot will propose the bump weekly.
