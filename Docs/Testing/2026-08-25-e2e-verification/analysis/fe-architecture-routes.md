# Frontend Architecture & Routes — JokesFor (`jokes-for-frontend`)

Repo: `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend`
Stack (package.json): React 19.2, react-router 7.12 (`react-router` package, `createBrowserRouter`), Vite 7, TS 5.9, Tailwind 4 (`@tailwindcss/vite`), TanStack Query 5.90, Zustand 5, axios, react-helmet-async 3, firebase 12 (analytics only), lucide-react. Tests: vitest 2 + testing-library (jsdom); Playwright e2e (only `e2e/example.spec.ts`, baseURL localhost:5173).
Prod hosting: Firebase Hosting project `jokesforfront` (`firebase.json`: SPA rewrite `** -> /index.html`, immutable cache for hashed assets, `no-store` for index.html).

All findings below come from code; where a doc disagrees it is called out in §12.

---

## 1. Boot sequence & providers

- `src/main.tsx` → `ReactDOM.createRoot(...).render(<StrictMode><App/></StrictMode>)`, imports `./app/App` (NOT `src/App.tsx`).
- `src/App.tsx` is a DEAD leftover scaffold ("Jokes For / Your daily dose of humor / Get Started" button). Not imported by anything.
- `src/app/App.tsx`:
  ```
  <Providers>
    <AppRoutes />        // RouterProvider
    <ConsentBanner />    // global cookie/analytics consent banner (features/consent)
  </Providers>
  ```
- `src/app/providers/index.tsx` nesting (outer→inner): `HelmetProvider` → `QueryProvider` (QueryClientProvider + ReactQueryDevtools, initialIsOpen=false, always mounted incl. prod) → `AuthProvider` → `ToastProvider` (`@/components/ui/toast`).
- `src/lib/query-client.ts` defaults: `staleTime: 5 min`, `retry: 1`, `refetchOnWindowFocus: false`, mutations `retry: 0`.
- `AuthProvider` (`src/app/providers/AuthProvider.tsx`): on mount (guarded by a ref against StrictMode double-run) fires `ensureCsrfToken()` (GET `/auth/csrf/`) fire-and-forget, then bootstraps session with RAW axios: `POST {API_URL}/auth/token/refresh/` (withCredentials, httpOnly refresh cookie) → `GET /auth/user/` with Bearer → `setAuth(user, access)`. On any failure → `setLoading(false)` (anonymous). Note: the auth store ALSO rehydrates from `sessionStorage` synchronously (see §7), so `isAuthenticated` may already be true before the refresh completes; the refresh then overwrites user/token.

### Route guards (`src/app/providers/`)
- `ProtectedRoute`: while `isLoading` → full-screen spinner; anon → `<Navigate to="/login?returnTo=<encoded pathname+search>" replace/>`; authed → children.
- `GuestOnlyRoute`: while `isLoading` → spinner; authed → `<Navigate to={searchParams.returnTo || '/'} replace/>` (note: returnTo is NOT decoded here, but `Navigate` handles the encoded path string; `/` → LandingPage → which itself redirects authed users to `/flow-canvas`); anon → children.
- There is NO verified-email guard, NO onboarding-complete guard, NO creator-role guard anywhere in routing (grep for `is_creator`/`email_verified`/`onboarding_completed` in guards: none). Email verification is enforced server-side at registration (gated registration returns no tokens; see §6). Onboarding (`/flow`) is only reached by explicit post-register navigation and is skippable.
- Guards are only used in `routes.tsx` (no page uses `useRequireAuth`; `useRequireAuth` in `features/auth/hooks.ts` is exported but unused).

---

## 2. Route table (`src/app/routes.tsx`, verbatim order)

All pages are STATICALLY imported from `@/pages` — there is NO `React.lazy` / route-level code splitting. The only lazy code is the editor registry `src/features/create/editors/index.ts` (`React.lazy` for oneliner/observ/story/setup/anti/knock/image/video/audio editors, rendered inside `Suspense` in EditorPage).

| Path | Component | Guard | Notes |
|---|---|---|---|
| `/privacy` | `PrivacyPage` (legal/LegalDocPage) | public | `<Seo>` canonical `/privacy` |
| `/terms` | `TermsPage` | public | |
| `/cookie-policy` | `CookiePolicyPage` | public | |
| `/cookies` | `Navigate → /cookie-policy` (replace) | — | alias |
| `/childrens-privacy` | `ChildrenPrivacyPage` | public | |
| `/` | `LandingPage` | public; **authed users → `<Navigate to="/flow-canvas" replace/>` inside the page** (LandingPage.tsx:30-37, sync from sessionStorage rehydrate so no flash) | marketing page; `<Seo>` + `siteJsonLd()` (WebSite+SearchAction, Organization) |
| `/search` | `SearchPage` | public | `useJokeSearch`; `<Seo>` |
| `/daily` | `DailyJokePage` | public | `useTodaysJoke`, `useDailyJokeHistory`, `useSaveJoke`; `<Seo>` |
| `/library` | `LibraryPage` | **public in routes** but uses auth-only hooks `useCollections` + `useSavedJokes` (no `isAuthenticated` branch, no error state found in page) → anon gets 401s / empty. Also linked from the mobile bottom tab bar for anon users. **Gap.** | |
| `/trending` | `TrendingPage` | public | `useTrendingJokes/Tags/RisingTopics/TopJokesters/PopularThemes`; `<Seo>` |
| `/favorites` | `FavoritesPage` | ProtectedRoute | |
| `/profile` | `ProfilePage` | ProtectedRoute | |
| `/settings` | `SettingsPage` | ProtectedRoute | PublicIdentityEditor, BlockedUsersList, preferences, password change, delete account, data export, link to `/settings/billing` |
| `/settings/billing` | `BillingPage` | ProtectedRoute | plans / subscription / entitlements / checkout / portal; mock-mode "demo overlay"; dormant (503) state |
| `/collections` | `CollectionsPage` | ProtectedRoute | |
| `/collections/:id` | `CollectionDetailPage` | ProtectedRoute | |
| `/create` | `CreatorHubPage` | ProtectedRoute | drafts list via `features/create` `useDrafts`; ANY authed user (no creator gating) |
| `/create/insights` | `CreatorInsightsPage` | ProtectedRoute | `/creators/me/insights/` |
| `/create/new` | `FormatPickerPage` | ProtectedRoute | |
| `/create/new/:formatSlug` | `EditorPage` (NewEditor mode) | ProtectedRoute | declared BEFORE `/create/:draftId` so "new" isn't captured as a draftId (tested in routes.test.tsx:122) |
| `/create/:draftId` | `EditorPage` (ExistingEditor mode) | ProtectedRoute | `useBlocker` for unsaved changes; autosave |
| `/create/:draftId/view` | `SubmissionDetailPage` | ProtectedRoute | |
| `/submit` | `Navigate → /create/new` | — | legacy alias |
| `/drafts` | `Navigate → /create` | — | legacy alias |
| `/flow` | `FlowPage` | ProtectedRoute | 3-step onboarding (Vibes ≥3 → Formats → Ritual); PUT `/users/me/vibes/`, PATCH preferences with `onboarding_completed: true`; skip/finish → `/flow-canvas` |
| `/flow-canvas` | `FlowCanvasPage` | ProtectedRoute | "Today" hub: insights (today-augmented, tomorrow teaser, taste profile), streak, mystery box, packs, JOTD history, top jokesters, daily-reads |
| `/explore` | `ExplorePage` | ProtectedRoute | 3-axis filter over `useJokeSearch` |
| `/login` | `LoginPage` | GuestOnlyRoute | success → `returnTo` param or `/flow-canvas`; Google → `getGoogleAuthUrl(returnTo)` (clears any stashed signup DOB) |
| `/register` | `RegisterPage` | GuestOnlyRoute | DOB required, client `isAtLeast13`; email path → `/verify-email?email=…` when gated (`data.email` w/o tokens) else `/flow`; Google path stashes DOB then redirects with returnTo `/flow` |
| `/verify-email` | `VerifyEmailPage` | GuestOnlyRoute | requires `?email=` else `<Navigate to="/register">`; 6-digit code → session → `/flow`; `already_verified` → `/login` |
| `/auth/google/callback` | `GoogleCallbackPage` | public | see §6 |
| `/forgot-password` | `ForgotPasswordPage` | public | step 1 (request) |
| `/reset-password` | `ForgotPasswordPage` | public | same component; step 2 when `?uid=&token=` present |
| `/creators/:creatorId` | `CreatorProfilePage` | public | `<Seo>` + `creatorJsonLd`; Follow/Block/Tip buttons (anon → `/login`) |
| `/jokes/:id` | `JokeDetailPage` | public | `?source=` (daily/search/explore/mystery/pack/saved/share/other) passed to `GET /jokes/:id/?source=`; `is_locked` → locked hero w/ CTA (`/settings/billing` if authed else `/register`); `<Seo>` + `jokeJsonLd` (never leaks locked punchline) |
| `/packs/:slug` | `PackDetailPage` | public | `<Seo>` |
| `/onboarding` | `Navigate → /flow` | — | alias |
| `/legacy` | `<Layout><Outlet/></Layout>` | — | legacy chrome subtree |
| `/legacy` (index) | `HomePageLegacy` | public | |
| `/legacy/trending` | `TrendingPageLegacy` | public | |
| `/legacy/favorites` | `FavoritesPageLegacy` | ProtectedRoute | |
| `/legacy/drafts` | `DraftsPageLegacy` | ProtectedRoute | |
| `/legacy/profile` | `ProfilePageLegacy` | ProtectedRoute | |
| `/legacy/settings` | `SettingsPageLegacy` | ProtectedRoute | uses `useOnboardingStore` |
| `/legacy/submit` | `SubmitJokePageLegacy` | ProtectedRoute | not Layout-wrapped (by design) |
| `*` | `NotFoundPage` | — | |

`robots.txt` (`public/robots.txt`) disallows: /create /settings /profile /flow /flow-canvas /explore /collections /favorites /login /register /verify-email /forgot-password /reset-password /auth/ /legacy /library /onboarding; sitemap → `https://jokesforfront.web.app/sitemap.xml`.

---

## 3. Pages inventory (`src/pages/`)

Exported via `src/pages/index.ts`. Routed = present in `routes.tsx`.

| File | Routed? | Shell | Notes |
|---|---|---|---|
| LandingPage | `/` | FlowAppShell (imports it) | conversion landing for anon |
| HomePage | **NOT routed** (exported) | FlowAppShell | superseded by LandingPage; docs still list it at `/` |
| SearchPage, DailyJokePage, LibraryPage, TrendingPage, FavoritesPage, ProfilePage, SettingsPage, BillingPage, CollectionsPage, CollectionDetailPage, ExplorePage, FlowCanvasPage | yes | FlowAppShell | |
| FlowPage | `/flow` | own full-screen layout (no shell) | onboarding |
| OnboardingPage | **NOT routed** (legacy, exported) | own | uses `stores/onboarding.store.ts` |
| DraftsPage | **NOT routed** (exported) | FlowAppShell | superseded by CreatorHubPage; `/drafts` redirects |
| SubmitJokePage | **NOT routed** (exported) | FlowAppShell | superseded by `/create/new`; navigates to `/drafts` on success (which redirects to `/create`) |
| CreatorHubPage, CreatorInsightsPage, FormatPickerPage, EditorPage, SubmissionDetailPage | `/create/*` | FlowAppShell | Phase-5 content creation |
| CreatorProfilePage, JokeDetailPage, PackDetailPage | yes | FlowAppShell | |
| LoginPage, RegisterPage, VerifyEmailPage, ForgotPasswordPage, GoogleCallbackPage | yes | own (RegisterPage imports FlowAppShell but is split-canvas) | |
| legal/{Privacy,Terms,CookiePolicy,ChildrenPrivacy}Page → `LegalDocPage` | yes | own | content from `src/content/legal/*.ts` |
| *Legacy pages*: HomePageLegacy, TrendingPageLegacy, FavoritesPageLegacy, DraftsPageLegacy, ProfilePageLegacy, SettingsPageLegacy, SubmitJokePageLegacy | `/legacy/*` | legacy `Layout` (Header/Sidebar/MobileBottomNav/FAB/Footer) | direct URL only, not in nav |
| NotFoundPage | `*` | — | |

Unrouted-but-exported: `HomePage`, `DraftsPage`, `SubmitJokePage`, `OnboardingPage` (dead weight in the bundle since imports are static via the barrel).

---

## 4. Layout shells & responsive

- **`FlowAppShell`** (`src/components/FlowAppShell.tsx`) — the canonical chrome, rendered per-page (no layout route). Props: `active?: FlowNavKey`, `hideStreak?`. Contains:
  - Sticky header: logo → `/`; desktop/tablet top nav `NAV_ITEMS`: Today `/flow-canvas`, Explore `/explore`, Search `/search`, Trending `/trending`, Daily `/daily`, Favorites `/favorites`, Library `/library`.
  - Authed right cluster: streak chip (only desktop, `useStreak().current_count>0`), "+" → `/create` with unseen-submission dot (`useUnseenSubmissionChange`), bell + unread badge (`useUnreadCount`) → `NotificationsPanel`, avatar initial → `ProfileMenu` (links: /profile, /library, /create, /settings; logout → `/`). Anon: "Sign in" → `/login` (hidden on mobile).
  - `<main key={pathname} className="page-enter">`, fluid, `maxWidth 1200`, gutter `clamp(0px,2vw,24px)`, mobile bottom clearance `calc(64px + safe-area)`.
  - **Mobile (<640) bottom tab bar** `<nav aria-label="Primary">`: Today, Explore, Search, Library, + Profile (`/profile`) or Sign in (`/login`) for anon. Active = `active` key or pathname prefix match.
  - `DailyReadsNudge` (authed only) — fixed nudge when over free cap; on mobile lifted above tab bar (RESPONSIVE.md "known follow-up" is already done in code, DailyReadsNudge.tsx:33).
- **`useBreakpoint`** (`src/hooks/useBreakpoint.ts`): `BREAKPOINTS = {mobile:640, desktop:1024}`; mobile `<640` (query `max-width: 639.98px`), tablet 640–1023, desktop `≥1024`; matchMedia `change` + `resize` listeners; SSR/no-matchMedia fallback = desktop. `usePrefersReducedMotion` also exists.
- **Legacy `Layout`** (`src/components/Layout.tsx`): DesktopHeader (Browse `/search`, Categories `/search?view=categories`, Top Rated `/search?sort=top`, Submit `/submit`), MobileHeader, Sidebar (Home `/`, Trending, My Jokes `/library`, Favorites, Drafts `/drafts`), `MobileBottomNav` (`src/components/layout/MobileBottomNav.tsx`: Daily `/daily`, Explore `/search`, Saved `/library`, Profile `/profile`), FloatingActionButton, Footer (desktop only). Used ONLY by the `/legacy` subtree.
- Global CSS `src/index.css`: `html { overflow-x: hidden }` (line 73), `.resp-grid` utility, `prefers-reduced-motion` block (line 290). Fonts loaded from Google Fonts in `index.html` (Epilogue, Plus Jakarta Sans, Fraunces, JetBrains Mono).

---

## 5. Feature modules (`src/features/*`) — purpose / hooks / API path

Legend: **adapter** = goes through `src/lib/api-adapter.ts` (mock/real switch); **direct** = calls `src/lib/api.ts` axios object directly (NO mock branch — in mock mode these hit `VITE_API_URL` and fail).

| Feature | Purpose | Hooks | Backend calls | Path |
|---|---|---|---|---|
| appeals | DSA appeals | `useMyAppeals`, `useCreateAppeal` | `POST /appeals/`, `GET /users/me/appeals/` | adapter |
| auth | session | `useLogin/useRegister/useVerifyEmail/useGoogleAuth/useLogout/useUpdateUser/usePasswordChange/usePasswordReset/usePasswordResetConfirm/useResendVerification/useDeleteAccount/useDataExport/useCurrentUser`, `useAuth`, store | `/auth/login/ registration/ logout/ google/ user/ token/refresh/ token/verify/ password/* verify-email/ resend-verification/`, `DELETE /users/me/`, `GET /users/me/data-export/` | direct (always real) |
| billing | Stripe subs | `useBillingPlans/useMySubscription/useEntitlements/useCreateCheckoutSession/useCreatePortalSession`, `isBillingUnavailable` (503 dormant) | `/billing/plans`, `/billing/my-subscription`, `/billing/entitlements`, `POST /billing/checkout-session`, `POST /billing/portal-session` (no trailing slashes) | adapter |
| collections | user collections | `useCollections/useCollectionJokes/useCreateCollection/useDeleteCollection` | `/collections/`, `/collections/:id/`, `/collections/:id/jokes/` | adapter |
| consent | cookie consent + age helpers | `useConsent`, `ConsentBanner`, `readConsent/writeConsent/clearConsent`, `isAdult` (≥18), `isAtLeast13` | localStorage `jokesfor-consent` `{version:1, analytics, ts}` | local |
| create | content creation (drafts, catalogs, editors, autosave, media upload) | `useFormats/useAgeRatings/useTones/useContextTags/useCultureTags/useLanguages/useDrafts/useDraft`, `useCreateDraft/usePatchDraft/useSubmitDraft/useDeleteDraft/useUploadMedia`, `useAutosave`, `useCreatorStore` (persist `jokesfor-creator`), `useUnseenSubmissionChange`, `track()` | `/formats/ /age-ratings/ /tones/ /context-tags/ /culture-tags/ /languages/`, `/jokes/my-drafts/` (list/create/get/patch/delete), `POST /jokes/my-drafts/:id/submit/`, `POST /media/uploads/` (multipart) | **own adapter** `features/create/adapter.ts`, gated by `VITE_USE_REAL_CREATE==='true'` (NOT by USE_MOCKS) |
| creator-insights | creator analytics | `useCreatorInsights(period)` | `GET /creators/me/insights/?period=` | adapter |
| daily-joke | JOTD | `useTodaysJoke/useDailyJokeHistory` | `/daily-jokes/today/`, `/daily-jokes/history/` | adapter |
| daily-reads | freemium cap | `useDailyReads` (active/limit/used/remaining/over/resetAt/canReveal/registerReveal), store (session Set of revealedIds, optimisticSpent, nudgeDismissed), `DailyReadsNudge` | `GET /jokes/daily-reads/` (null on error → no cap) | direct, but returns null in mock mode |
| drafts | LEGACY drafts (camelCase DraftJoke) used by DraftsPageLegacy/SubmitJokePage | `useDrafts/useCreateDraft/useUpdateDraft/useSubmitDraft/useDeleteDraft` | `/jokes/my-drafts/`, `POST /jokes/submit/` | adapter |
| favorites | likes | `useFavorites/useFavoriteStats/useAddFavorite/useRemoveFavorite` (optimistic stats) | `/favorites/`, `/favorites/:id/`, `/favorites/stats/` | adapter |
| follows | follow + public creator profile | `useCreatorProfile/useFollowStatus/useFollow/useUnfollow` (optimistic), `FollowButton` | `/follows/:id/`, `/follows/:id/status/`, `/creators/:id/profile/` (jokes normalized via `normalizeProfileJoke`) | adapter |
| insights | reader insights | `useTasteProfile/useTodayAugmented/useTomorrowTeaser` | `/users/me/taste-profile/`, `/daily-jokes/today/`, `/daily-jokes/tomorrow/` | direct |
| jokes | search/detail/random/rate | `useJokeSearch` (enabled only with params), `useRandomJoke`, `useJoke` | `/jokes/`, `/jokes/:id/`, `/jokes/random/`, `/jokes/:id/rate/`, `/jokes/:id/my-rating/` | adapter |
| moderation | report/block | `useReportJoke/useMyBlocks/useBlockUser/useUnblockUser` | `POST /reports/`, `/users/:id/block/`, `/users/me/blocks/` | adapter |
| mystery-box | daily random roll | `useMysteryBoxStatus/useRollMysteryBox` | `/mystery-box/status/`, `POST /mystery-box/roll/` | direct |
| notifications | inbox | `useNotifications/useUnreadCount/useMarkAllRead` | `/notifications/`, `/notifications/unread-count/`, `POST /notifications/mark-read/` | adapter |
| packs | editorial packs | `usePacks/usePack/useFeaturedPack/usePacksInProgress/useRecordPackProgress` | `/packs/`, `/packs/:slug/`, `/packs/featured/`, `POST /packs/:slug/progress/`, `/users/me/packs/in-progress/` | direct |
| preferences | user prefs (+ ritual + onboarding_completed) | `usePreferences/useUpdatePreferences` (invalidates daily-joke today) | `/users/me/preferences/` (GET/PATCH) | adapter, real when `VITE_USE_REAL_PREFERENCES==='true' || !USE_MOCKS` |
| profile | own profile/identity/activity/achievements | `useProfile/useUpdateProfile/usePublicIdentity/useUpdateIdentity/useActivity/useAchievements` | `/users/me/profile/` (GET/PATCH), `/users/me/activity/`, `/users/me/achievements/` | adapter |
| reactions | emoji reactions | `useReactions/useReactToJoke` | `/jokes/:id/reactions/`, `POST /jokes/:id/react/` | direct |
| recently-viewed | | `useRecentlyViewed` | `/users/me/recently-viewed/` | direct |
| saved-jokes | saves | `useSavedJokes/useSaveJoke/useUnsaveJoke` (optimistic) | `/saved-jokes/`, `/saved-jokes/:id/`, `/saved-jokes/search/` | adapter |
| streak | | `useStreak` (enabled only when authed), `useFreezeStreak/useUnfreezeStreak` | `/users/me/streak/`, `/users/me/streak/freeze/`, `/users/me/streak/freeze/remove/` | direct |
| telemetry | audience telemetry | `useImpression/useDwell/useWatchTracking`, `recordShare`, `trackImpression/trackReveal/trackDwell/trackWatch/flushTelemetry` | `POST {API}/telemetry/events` (sendBeacon/fetch keepalive, batch ≤50, flush at 10 & pagehide); `POST /jokes/:id/share/` | direct; gate = real mode AND token AND authed AND `isAdult(dob)` AND consent.analytics |
| tips | creator tips (Stripe) | `useCreateTipCheckout/useCreatorTipsSummary/useMyTips`, `TipButton` (503 → dormant), `TipsReceived`, `TIP_TIERS` | `POST /tips/checkout/`, `/creators/:id/tips/summary/`, `/users/me/tips/` | adapter |
| today-status | ritual status | `useTodayStatus` (refetchOnWindowFocus true) | `/users/me/today-status/` | direct |
| trending | | `useTrendingJokes/useTrendingTags/useRisingTopics/useTopJokesters/usePopularThemes` | `/jokes/trending/`, `/tags/trending/`, `/tags/rising/`, `/themes/popular/`, `/users/top-jokesters/` | adapter |
| vibes | onboarding vibes | `useVibesCatalog/useMyVibes/useUpdateMyVibes` | `/vibes/`, `/users/me/vibes/` (GET/PUT) | direct |

Other `api.ts` objects not wrapped in a feature: `revealApi.post(/jokes/:id/reveal/)` (used by FlowJokeCard), `jokeDetailApi.get(/jokes/:id/?source=)` (JokeDetailPage), `sharesApi`, `preferencesApi.completeOnboarding` (`POST /preferences/complete-onboarding/`, unused — FlowPage sets `onboarding_completed` via PATCH preferences).

---

## 6. Auth / Google OAuth / verification / age gate flows

- **Access token** lives in memory (`lib/axios.ts` `setAccessToken`) AND is persisted in the Zustand auth store to **sessionStorage** key `jokesfor-auth` (user, accessToken, isAuthenticated). Refresh token = httpOnly cookie. Axios interceptors: attach Bearer; attach `X-CSRFToken` on mutating methods (token from `GET /auth/csrf/`, cached in sessionStorage `jokesfor-csrf`); on 403 "CSRF" → refetch token and retry once; on 401 → single-flight refresh via raw axios `POST /auth/token/refresh/`, queue concurrent requests, retry; refresh failure → clear token, reject (no redirect).
- **Login** (`useLogin`) → `setAuth` → LoginPage navigates to `returnTo` or `/flow-canvas`.
- **Register** (`RegisterPage`): fields incl. DOB (required; client check `isAtLeast13`, message "You must be at least 13 years old to use Jokes For."). `POST /auth/registration/` returns either tokens (ungated) → navigate `/flow`, or `{detail,email}` (gated, `EMAIL_VERIFICATION_REQUIRED`) → `/verify-email?email=…` (`&sendFailed=1` when send failed). Under-13 server error `date_of_birth[0]` shown inline, no navigation.
- **VerifyEmailPage**: `POST /auth/verify-email/ {email, code}` → cookies set → `useVerifyEmail` pulls access via refresh → `setAuth` → optionally `useUpdateUser` from `location.state` (firstName/handle) → `/flow`. Resend via `POST /auth/resend-verification/`.
- **Google OAuth** (`features/auth/google-oauth.ts`): redirect_uri = `VITE_GOOGLE_OAUTH_REDIRECT_URI` if set, else `window.location.origin + /auth/google/callback`. `getGoogleAuthUrl(returnTo)` stashes returnTo in sessionStorage `auth.returnTo`, builds `accounts.google.com/o/oauth2/v2/auth` URL (scopes openid email profile, `access_type=offline`, `prompt=consent`); throws if `VITE_GOOGLE_CLIENT_ID` unset. Register path stashes DOB in sessionStorage `auth.signupDob` (`stashSignupDob`) after `isAtLeast13`; Login path `clearSignupDob()`.
- **`GoogleCallbackPage`** (`/auth/google/callback?code=…` or `?error=…`): single exchange (ref guard vs StrictMode) `POST /auth/google/ {code, redirect_uri, date_of_birth?}` via `mutateAsync`; success → `navigate(consumeReturnTo() || '/')`; error `code==='dob_required'` → `/register` with `state.notice`; `date_of_birth[0]` → shown; else detail/non_field_errors; `error=access_denied` → "Sign-in cancelled".
- **Logout** (`ProfileMenu`, SettingsPage) → `POST /auth/logout/` → store `logout()` → `/`.
- **Delete account** → `DELETE /users/me/` → `/`. **Data export** → `GET /users/me/data-export/` blob.

## 7. Zustand stores

| Store | File | Persist | Fields |
|---|---|---|---|
| `useAuthStore` | `features/auth/store.ts` | sessionStorage `jokesfor-auth` (partialize user/accessToken/isAuthenticated; `onRehydrateStorage` syncs token to axios + `setLoading(false)`) | user, accessToken, isAuthenticated, isLoading |
| `useOnboardingStore` | `stores/onboarding.store.ts` | localStorage `jokesfor-onboarding` (zustand default) | currentStep, totalSteps=3, selectedHumorTypes, isComplete — used ONLY by unrouted `OnboardingPage` and `SettingsPageLegacy` (dead in canonical app) |
| `useUIStore` | `stores/ui.store.ts` | none | isMobileMenuOpen, isSidebarCollapsed, isSearchFocused — **unused anywhere** (grep: only its own file) |
| `useCreatorStore` | `features/create/store.ts` | localStorage `jokesfor-creator` | last-seen submission statuses → `useUnseenSubmissionChange` dot |
| `useDailyReadsStore` | `features/daily-reads/store.ts` | none (session) | revealedIds Set, optimisticSpent, nudgeDismissed |

## 8. Consent / age gate / analytics

- `ConsentBanner` (mounted globally in `app/App.tsx`) renders until `readConsent()` returns a v1 record; Accept → `writeConsent(true)` and `initAnalytics()` ONLY if `isAdult(user.date_of_birth)` (≥18) at that moment; Reject → `writeConsent(false)`. Cookie-policy link is a plain `<a>` (tested).
- `lib/firebase.ts`: **analytics only** (`firebase/app` + `firebase/analytics`, lazy `initializeApp`, `isSupported()`); no Firebase Auth/Firestore/Storage anywhere. Analytics init is gated on consent + adult; nothing else ever calls `initAnalytics` (grep: only `useConsent.ts`), so a consenting minor or an anon visitor never gets GA. Note: if a user accepts consent while anon and later logs in as an adult, analytics is NOT initialized retroactively (no re-check on auth change) — edge gap.
- Telemetry gate (§5) additionally requires adult + consent + authed + real mode.
- `features/auth/analytics.ts` and `features/create/analytics.ts` `track()` are console.debug-only scaffolds in DEV.

## 9. SEO

- `src/lib/seo/`: `Seo` (react-helmet-async: title, description, canonical `SITE_URL + canonicalPath`, OG (site_name JokesFor, type, title, description, url, image), Twitter `summary_large_image`, JSON-LD `<script type="application/ld+json">` via `toSafeJsonLdString` (escapes `<`)). `SITE_URL='https://jokesforfront.web.app'` hardcoded; `DEFAULT_OG_IMAGE=/Logos/banner_purple.svg` (SVG — noted as poor for Twitter). `BACKEND_ORIGIN` from `VITE_API_URL` minus `/api/v1`; `jokeShareUrl(id) = {BACKEND_ORIGIN}/jokes/{id}/share/` used for clipboard/navigator.share (backend serves OG + redirects humans).
- JSON-LD: `siteJsonLd()` (WebSite w/ SearchAction → `/search?q={search_term_string}`, Organization) on LandingPage; `jokeJsonLd(joke)` CreativeWork (locked → setup only, author = Organization); `creatorJsonLd(profile)` ProfilePage/Person.
- `<Seo>` used by: LandingPage, SearchPage, DailyJokePage, TrendingPage, JokeDetailPage, CreatorProfilePage, PackDetailPage, LegalDocPage. No `noindex` meta anywhere (auth pages rely on robots.txt only). Non-Seo routes fall back to `index.html` static OG tags.
- `scripts/gen-sitemap.mjs` runs as npm `prebuild`: fetches `{BACKEND_ORIGIN}/sitemap.xml` (VITE_API_URL from env or parsed from `.env`, else prod fallback), 15s timeout, writes `public/sitemap.xml` only if body looks like XML; FAIL-SOFT (warn + exit 0, leaves existing file). `public/sitemap.xml` is NOT committed (absent locally) — it only exists in `dist/` after a build with backend reachable.

## 10. Environment flags & mock vs real matrix

Flags (`src/vite-env.d.ts` not checked; usage grep):
- `VITE_API_URL` — axios baseURL (default `http://localhost:8000/api/v1`).
- `VITE_USE_MOCKS` — `USE_MOCKS = !VITE_API_URL || VITE_USE_MOCKS==='true'` (computed identically in `lib/api-adapter.ts:33`, `lib/telemetry.ts:55`, `features/daily-reads/api.ts:16`, `features/tips/TipButton.tsx:11`, `features/telemetry/recordShare.ts:6`, `pages/BillingPage.tsx:19`).
- `VITE_USE_REAL_PREFERENCES` — real prefs when `'true'` OR `!USE_MOCKS`.
- `VITE_USE_REAL_CREATE` — content-creation adapter real ONLY when `'true'` (independent of USE_MOCKS!).
- `VITE_GOOGLE_CLIENT_ID`, `VITE_GOOGLE_OAUTH_REDIRECT_URI`, `VITE_FIREBASE_*`.
- Local `.env`: `VITE_USE_MOCKS=true`, `VITE_USE_REAL_PREFERENCES` empty, no `VITE_USE_REAL_CREATE` → local dev is mock for adapter features AND mock for create. (Local `.env` also contains a `FIGMA_TOKEN` and live Firebase keys — committed? `.env` is untracked per .gitignore presumably; flag for owner.)
- CI (`.github/workflows/ci.yml`): builds with `VITE_USE_MOCKS=false`, `VITE_USE_REAL_PREFERENCES=true`, `VITE_USE_REAL_CREATE=true`; runs `npm run lint`, `npm test -- --run`, `npm run build`.
- Prod deploy (`firebase-hosting-merge.yml`, on push to main): `VITE_USE_MOCKS=false`, `VITE_USE_REAL_PREFERENCES=true`, `VITE_USE_REAL_CREATE=true`, redirect URI `https://jokesforfront.web.app/auth/google/callback`.
- **PR preview** (`firebase-hosting-pull-request.yml`): sets USE_MOCKS=false and REAL_PREFERENCES=true but **does NOT set `VITE_USE_REAL_CREATE`** → PR preview channels run the content-creation flow against the in-memory mock (drafts don't persist) while everything else is real. Discrepancy vs merge workflow.

**When mocks are OFF (prod build), what is still mock/in-memory?**
- Nothing in `api-adapter.ts` — every adapter has a real branch (jokes, daily-joke, collections, saved-jokes, trending, favorites, drafts(legacy), profile (get/update/activity/achievements), accountIdentity, notifications, moderation, appeals, creator-insights, follows, creator-profile, preferences, billing, tips). The comment at api-adapter.ts:~466 ("the rest of profileAdapter is still mock-only") is STALE — real branches exist.
- Content creation is real only because deploy sets `VITE_USE_REAL_CREATE=true`; with the flag missing it silently reverts to mock even in real mode.
- `track()` analytics in auth/create = console-only (no backend). `useUIStore`/`useOnboardingStore` unused by canonical pages.

**When mocks are ON (local default)**: adapter features use `lib/mock-api.ts`; daily-reads returns null (no cap); telemetry/recordShare/tips/billing short-circuit to demo behaviour; BUT `direct` features (insights, streak, mystery-box, packs, vibes, today-status, reactions, recently-viewed, auth, create-when-flag-off is mock) still call `VITE_API_URL` and error — FlowCanvasPage/FlowPage need a real backend even in "mock" mode.

## 11. Tests present (for the pipeline)
- `src/app/routes.test.tsx`: `/submit`→`/create/new`, `/drafts`→`/create`, `/create*` route resolution incl. `/create/new/:formatSlug` not captured by `:draftId`, `/collections`, `/collections/:id`.
- `src/app/App.test.tsx`: consent banner shows for undecided visitor, hidden when decision stored, cookie link is plain `<a>`.
- `hooks/useBreakpoint.test.ts`: bands 375/640/768/1280, no-matchMedia fallback, listener cleanup.
- Page tests: JokeDetailPage.locked/media, FlowJokeCard.paywall/anon, RegisterPage.agegate/googledob/verify, VerifyEmailPage, GoogleCallbackPage, LandingPage, LegalPages, Seo/jsonld, telemetry, daily-reads, FlowAppShell, etc.

## 12. Docs vs code discrepancies
1. `Docs/State_Management_Architecture.md` §6 says query defaults `staleTime 0 / retry 3 / refetchOnWindowFocus true` — code (`lib/query-client.ts`) is `5 min / 1 / false`.
2. Same doc §7 says trending/favorites/drafts/profile/preferences are mock-only — code has real branches for all; doc says "14 pages and 10 feature modules" — code has ~45 page files and 28 feature modules.
3. `Docs/Redesign_Plan.md` routing summary lists `/` → HomePage, `/drafts` → DraftsPage, `/submit` → SubmitJokePage, `/collections → /library` alias — code: `/` → LandingPage, `/drafts`→`/create` redirect, `/submit`→`/create/new` redirect, `/collections` is a real CollectionsPage. Plan says "/onboarding retired, redirects to /flow" (matches).
4. `Docs/RESPONSIVE.md` "known follow-up: DailyReadsNudge overlaps mobile tab bar" — already fixed in code (`DailyReadsNudge.tsx:33`).
5. `api-adapter.ts` comment "rest of profileAdapter is still mock-only" is stale (real activity/achievements mapping exists).
6. `routes.tsx` header comment says pages are "all redesigned … none wrapped in legacy Layout" — true; but `pages/index.ts` still exports unrouted HomePage/DraftsPage/SubmitJokePage/OnboardingPage.

## 13. Risks / gaps observed
- `/library` is public but auth-only data; anon mobile tab bar links to it. Likely blank/401 for anon.
- No route-level code splitting → all pages in one bundle (only editors are lazy).
- `ReactQueryDevtools` mounted in prod builds (tree-shakes to a no-op in production per TanStack, but still imported).
- `GuestOnlyRoute` redirects authed users to `returnTo` without validating it (open-redirect surface limited to same-SPA paths since `Navigate` is client-side; a `returnTo=//evil` would be treated as a path by react-router — low risk but worth a test).
- Analytics not re-evaluated on login after an earlier consent (see §8).
- PR preview workflow lacks `VITE_USE_REAL_CREATE`.
- `src/App.tsx` dead file; `useUIStore` and `useOnboardingStore` effectively dead.
- `.env` in repo dir holds a Figma token and Firebase keys (verify it is gitignored).
