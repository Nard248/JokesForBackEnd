# FE Data / API Layer — Deep Dive (`fe-data-layer`)

Frontend repo: `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend` (FE)
Backend repo:  `/Users/narekmeloyan/PycharmProjects/JokesForProject` (BE)
All paths below are relative to those roots unless absolute. All facts are from code read on 2026-08-25; where docs disagree with code it is called out explicitly.

---

## 0. TL;DR — headline findings

| # | Finding | Severity | Where |
|---|---------|----------|-------|
| 1 | **Telemetry is almost certainly dropped in prod.** `send()` prefers `navigator.sendBeacon` for *every* flush (not only page-hide). A beacon cannot carry `Authorization` or `X-CSRFToken`. The request therefore authenticates via the httpOnly JWT cookie, which (with `JWT_AUTH_COOKIE_USE_CSRF=True`) triggers `enforce_csrf` → 403 `CSRF Failed`. `sendBeacon()` returns `true` (queued), so the `fetch` fallback (which *does* attach Bearer) never runs. Impressions/reveals/dwell/watch never reach `TelemetryIngestView`; creator-insights reach/payoff/read-time stay empty. | HIGH | FE `src/lib/telemetry.ts:95-127`; BE `JokesForProject/settings.py:424-441`; `.venv/.../dj_rest_auth/jwt_auth.py:135-144` |
| 2 | **`GET /daily-jokes/history/` shape mismatch.** BE returns a bare JSON array (`Response(serializer.data)`, backend tests iterate `r.data` directly). FE types it as `PaginatedResponse` and reads `history?.results` → always `undefined` → "Previous daily jokes" grid and the 7-day archive render empty. FE doc `Docs/API_Specification_For_Frontend.md:312-330` documents a paginated shape — **doc is wrong, code is authoritative**. | HIGH | BE `jokes/views.py:1299-1336`, `jokes/test_time_progression.py:287-298`; FE `src/lib/api.ts:266-267`, `src/pages/DailyJokePage.tsx:112-121`, `src/pages/FlowCanvasPage.tsx:61,275` |
| 3 | **FlowCanvas "For You" query never fires.** `useJokeSearch` is `enabled` only when `hasSearchParams()` sees `q/joke_format/age_rating/tones/context_tags/culture_tags/language/page`. FlowCanvasPage passes `{vibe, page_size:3}` or `{page_size:3, ordering}` → none of those keys → `enabled:false` → `forYouJokes` is always `undefined` → fallback copy always shown. | MEDIUM | FE `src/features/jokes/api.ts:12-32`, `src/pages/FlowCanvasPage.tsx:67,262` |
| 4 | **`page_size` query param is ignored by the backend.** DRF `PageNumberPagination` with `PAGE_SIZE=10` and no `page_size_query_param` anywhere. FE sends `page_size=30` (Explore/Search), `page_size=3` (FlowCanvas), `?page_size=100` (create drafts list). Every list is capped at 10/page; the creator hub only ever sees the 10 most recent drafts/submissions. | MEDIUM | BE `JokesForProject/settings.py:301-302` (grep: no `page_size_query_param` in repo); FE `src/features/create/api.ts:25`, `src/pages/ExplorePage.tsx:40`, `src/pages/SearchPage.tsx:54` |
| 5 | **Multi-format Explore filter returns nothing.** ExplorePage joins several format slugs with commas into `joke_format`; BE does `format__slug=filters['format']` (exact match, no split) → zero results when ≥2 format chips are selected. `tones`/`context_tags`/`culture_tags` *are* comma-split. | MEDIUM | FE `src/pages/ExplorePage.tsx:41-43`; BE `jokes/views.py:300-312`, `jokes/managers.py:44-45` |
| 6 | **Legacy drafts adapter is wired to the wrong contract** (only reachable via `/legacy/drafts`, `/legacy/submit`): `draftsApi.create` POSTs to `/jokes/submit/` (creates a *pending* submission, not a draft; response is `{id,status,created_at}` not a DTO); `DraftJokeDTO.status` enum (`submitted/approved`) doesn't match BE (`pending/published`); `format` is a slug string on BE, object on FE. Non-legacy `/create` uses `features/create/api.ts` which is correct. | LOW (legacy) | FE `src/lib/api.ts:398-426`, `src/lib/api-adapter.ts:218-279`; BE `jokes/views.py:1629-1645`, `jokes/serializers.py:766-792`, `jokes/models.py:627-631` |
| 7 | Preferences PATCH silently drops fields the FE sends (`tones`, `age_rating`, `languages`, `notification_*`, `streak_saver_enabled`, `onboarding_completed`); BE only handles `humor_types`, `notifications`, `privacy`, `theme`. GET never returns them. | LOW | FE `src/lib/api-adapter.ts:679-703`; BE `jokes/views.py:2084-2149` |
| 8 | `POST /packs/{slug}/progress/` returns `{last_read_entry, completed_at, is_complete}`; FE types `PackProgress` as `{last_read_entry,total_entries,completed_at,started_at}`. FE ignores the body (invalidates queries), so harmless today. | LOW | FE `src/lib/api.ts:725-730,764-765`; BE `jokes/views.py:3038-3072` |
| 9 | Mystery-box roll success hard-codes `max_per_day: 3` in the cache instead of using the server's entitlement-derived value. | LOW | FE `src/features/mystery-box/api.ts:23-29`; BE `jokes/views.py:2774-2789` |
| 10 | Cookie-policy legal copy says the auth token lives in `localStorage`; the store actually uses `sessionStorage` (`jokesfor-auth`). | LOW (copy) | FE `src/content/legal/cookie.ts:18`, `src/features/auth/store.ts:58-70` |
| 11 | PR-preview workflow omits `VITE_USE_REAL_CREATE` → preview channels build the creator flow against mocks while merge builds use the real API. | LOW (CI) | FE `.github/workflows/firebase-hosting-pull-request.yml` vs `firebase-hosting-merge.yml:31` |

Every FE endpoint string was cross-checked against the BE URLconfs; **no FE call targets a non-existent backend route** (details in §9).

---

## 1. Build-time configuration & the mock switch

`src/lib/api-adapter.ts:33-34`, `src/lib/telemetry.ts:54-55`, `src/features/daily-reads/api.ts:15-17`, `src/features/telemetry/recordShare.ts:5-6` all compute the same gate:

```ts
const USE_MOCKS = !import.meta.env.VITE_API_URL || import.meta.env.VITE_USE_MOCKS === 'true'
```

Additional per-feature flags:

| Flag | Effect | Default (`.env.example`) | CI (`ci.yml`) | Merge deploy | PR preview |
|---|---|---|---|---|---|
| `VITE_API_URL` | axios `baseURL` (fallback `http://localhost:8000/api/v1`) | `http://localhost:8000/api/v1` | prod Cloud Run URL | prod URL | prod URL |
| `VITE_USE_MOCKS` | forces mock adapters | `true` | `'false'` | `'false'` | `'false'` |
| `VITE_USE_REAL_PREFERENCES` | real `/users/me/preferences/` even in mock mode (`api-adapter.ts:676-677`: real when flag **or** `!USE_MOCKS`) | empty | `'true'` | `'true'` | `'true'` |
| `VITE_USE_REAL_CREATE` | creator editor uses `contentApi` (`features/create/adapter.ts:22`) — **independent of `USE_MOCKS`**; without it the editor is mock even in prod builds | unset | `'true'` | `'true'` | **unset** (finding 11) |
| `VITE_FIREBASE_*` (7) | `firebase.ts` config; `MEASUREMENT_ID` gates analytics | empty | placeholders | secrets | secrets |
| `VITE_GOOGLE_CLIENT_ID`, `VITE_GOOGLE_OAUTH_REDIRECT_URI` | Google OAuth (features/auth/google-oauth.ts) | empty | placeholder / prod callback | prod | prod |

`vite.config.ts` only sets the `@` alias; no proxy. `firebase.json` is a pure SPA rewrite with immutable caching for hashed assets. `prebuild` runs `scripts/gen-sitemap.mjs` (fetches BE `/sitemap.xml` at build time).

---

## 2. `src/lib/axios.ts` — transport, CSRF, refresh

* **Instance**: `axios.create({ baseURL: VITE_API_URL || 'http://localhost:8000/api/v1', withCredentials: true, headers: {'Content-Type':'application/json'} })` (lines 4-13).
* **Access token**: module-level `accessToken` (in memory), set via `setAccessToken()` from the Zustand auth store. Request interceptor adds `Authorization: Bearer <token>` when present (lines 123-127).
* **CSRF** (lines 20-99, 128-133):
  * Token value obtained by `GET {API_URL}/auth/csrf/` → `{csrfToken}` (BE `jokes/views.py:797-814`, `authentication_classes=[]`). Cached in module state **and** `sessionStorage['jokesfor-csrf']`.
  * `X-CSRFToken` header attached only on `post/put/patch/delete`.
  * `ensureCsrfToken()` called once in `AuthProvider` on mount; `fetchCsrfToken()` re-run after login / register (non-gated) / verify-email / Google auth (`features/auth/api.ts:47,73,101,125`).
  * Why: BE `REST_AUTH.JWT_AUTH_COOKIE_USE_CSRF=True` → `JWTCookieAuthentication.enforce_csrf` runs when the JWT cookie is present **and** there is no `Authorization` header. Bearer requests bypass CSRF entirely (jwt_auth.py:135-144). So the header is defence-in-depth for the reload window before the token is rehydrated.
* **Response interceptor** (lines 139-213), in order:
  1. **CSRF retry**: if 403 and `detail` contains `'CSRF'` and method mutating and not already `_csrfRetry` → fetch a fresh token, set header, replay **once**.
  2. Non-401 → reject.
  3. 401 on `/auth/token/refresh/` or already `_retry` → reject.
  4. If a refresh is in flight → queue the request (`refreshSubscribers`) and replay with the new token.
  5. Otherwise raw `axios.post(`${API_URL}/auth/token/refresh/`, {}, {withCredentials:true})` → `response.data.access` → update `accessToken`, notify queue, replay original. On failure `accessToken=null`, error rejected; **no redirect** ("let the auth store handle it" — but nothing in the store listens; the Zustand store is not cleared on refresh failure, so `isAuthenticated` can stay `true` with a dead token until the next explicit logout).
* No generic retry/backoff for 5xx/network errors — retries are left to TanStack (`retry: 1` global).
* Refresh endpoint contract (BE `dj_rest_auth/jwt_auth.py:95-112`): returns `{access, access_expiration}`; refresh token is rotated (`ROTATE_REFRESH_TOKENS=True`, `BLACKLIST_AFTER_ROTATION=True`) and re-set as httpOnly cookie `jokes-refresh-token` (1 day); access cookie `jokes-access-token` (15 min). `SESSION_LOGIN=False`.

---

## 3. Auth bootstrap & session persistence

* `src/app/providers/AuthProvider.tsx`: on mount, `ensureCsrfToken()` then raw `axios.post(/auth/token/refresh/)` → `axios.get(/auth/user/, Bearer)` → `setAuth(user, access)`; any failure → `setLoading(false)` (anonymous). Guarded by a `hasCheckedAuth` ref (StrictMode-safe).
* `src/features/auth/store.ts`: Zustand `persist` named **`jokesfor-auth`** in **`sessionStorage`**, `partialize` → `{user, accessToken, isAuthenticated}`; `onRehydrateStorage` pushes the stored token into axios and sets `isLoading=false`. So a tab reload starts with the (possibly expired, ≤15 min) token in memory, and the first 401 triggers the cookie refresh.
* Login/Google (`features/auth/api.ts`): BE `dj_rest_auth` login returns `{user, access, refresh: ""}` (httpOnly mode blanks `refresh`, `dj_rest_auth/views.py:87-97`); FE `AuthResponse` type expects `refresh: string` — fine.
* Register (`CookieRegisterView`, BE `jokes/views.py:821-892`): gated mode (`EMAIL_VERIFICATION_REQUIRED=true`, LIVE in prod per memory) returns `201 {detail, email}` and **no tokens**; FE `useRegister` checks `'access' in data` before logging in; RegisterPage routes to `/verify-email`.
* Verify email (`notifications/views.py:VerifyEmailView`): sets cookies, returns `{user}` (no access in body). FE `useVerifyEmail` then calls `authApi.refreshToken()` to pull an access token; on failure it still calls `setAuth(user, '')` and relies on the 401 interceptor.
* Logout: `POST /auth/logout/` then `logout()` + `queryClient.clear()` on both success and error.
* Delete account: `DELETE /users/me/` with body `{password?, confirm:'DELETE'}` (both sent). Data export: `GET /users/me/data-export/` as blob → programmatic download.

---

## 4. `src/lib/query-client.ts` and per-hook cache policy

Global defaults (`query-client.ts:3-14`): `staleTime: 5 min`, `retry: 1`, `refetchOnWindowFocus: false`, mutations `retry: 0`.

| Hook (file) | Key | staleTime | Notes |
|---|---|---|---|
| `useCurrentUser` (auth/api.ts) | `['auth','user']` | default | `retry:false`; **unused** by any page |
| `useJokeSearch` (jokes/api.ts) | `['jokes','search',params]` | 5 min | `enabled: hasSearchParams(params)` (finding 3); `keepPreviousData` |
| `useRandomJoke` / `useJoke` | … | 0 / 10 min | unused by pages |
| `useTodaysJoke` (daily-joke) | `['daily-joke','today']` | 60 min | |
| `useDailyJokeHistory` | `['daily-joke','history']` | 5 min | shape mismatch (finding 2) |
| `useDailyReads` (daily-reads/api.ts) | `['daily-reads']` | 30 s | `retry:false`; queryFn **never throws** (404/network → `null` = "no cap"); mock mode short-circuits to `null` |
| `useTasteProfile` / `useTodayAugmented` / `useTomorrowTeaser` (insights) | `['insights',…]` | 5 / 60 / 30 min | tomorrow `retry:false` (404 possible) |
| `useMysteryBoxStatus` | `['mystery-box','status']` | 1 min | roll mutation writes cache with hard-coded `max_per_day:3` |
| `useReactions` | `['reactions',id]` | 30 s | react mutation `setQueryData` |
| `useStreak` | `['streak','state']` | 1 min | `enabled: isAuthenticated` |
| `usePacks`/`usePack`/`useFeaturedPack`/`usePacksInProgress` | `['packs',…]` | 5/5/5/1 min | featured `retry:false` |
| `useTodayStatus` | `['today-status']` | 5 min | `refetchOnWindowFocus:true`; **unused** |
| `useRecentlyViewed` | `['recently-viewed',limit]` | 30 s | **unused** |
| `useVibesCatalog` / `useMyVibes` | `['vibes',…]` | 24 h / 5 min | |
| `useCollections` / `useCollectionJokes` | `['collections',…]` | 5 min | |
| `useSavedJokes` | `['saved-jokes','list']` | 5 min | save cascades invalidation to collections/favorites/profile |
| `useFavorites` / `useFavoriteStats` | `['favorites',…]` | 5 min | remove = list-then-delete (2 requests, `api-adapter.ts:199-206`) |
| `useTrending*` (trending) | `['trending',…]` | 5–15 min | |
| `useCreatorInsights` | `['creator-insights',period]` | 5 min | custom retry: none on 401/403, else <2 |
| `useCreatorProfile` / `useFollowStatus` | `['creator-profile',id]` / `['follows','status',id]` | 2 / 1 min | optimistic follow/unfollow with rollback |
| `useNotifications` / `useUnreadCount` | `['notifications',…]` | 30 s | |
| `useMyBlocks` | `['moderation','blocks']` | 1 min | block invalidates `['creator-profile']`, `['jokes']` |
| `useMyAppeals` | `['appeals','mine']` | 30 s | adapter maps 404 → `[]` |
| `useProfile`/`useActivity`/`useAchievements`/`usePublicIdentity` | `['profile',…]` | 5/2/10/5 min | |
| `usePreferences` | `['preferences']` | 10 min | update sets cache + invalidates `['daily-joke','today']` |
| `useBillingPlans`/`useMySubscription`/`useEntitlements` | `['billing',…]` | 10/2/2 min | |
| `useCreatorTipsSummary` / `useMyTips` | `['tips',…]` | 1 min / 30 s | `useMyTips` **unused** |
| `useDrafts` (legacy drafts) | `['drafts','list']` | 2 min | legacy pages only |
| create: `useFormats`…`useLanguages` | `['formats']`, `['taxonomy',…]` | 60 min | |
| create: `useDrafts` / `useDraft` | `['create','drafts']`, `['create','drafts',id]` | 30 s / `refetchOnMount:'always'` | patch is optimistic w/ rollback |

Note the create feature's `useDrafts` and the legacy drafts feature's `useDrafts` share a name but different keys (`['create','drafts']` vs `['drafts','list']`).

---

## 5. `src/lib/telemetry.ts` — audience telemetry

* **Events**: `impression`, `reveal` (deduped client-side per `type:joke:source` for the page-session), `dwell` (`value` ms, optional `scroll_pct`, min 1000 ms client / 500 ms server, clamp 600 000), `watch` (`watch_ms`, optional `watch_pct`, clamp 600 000, server drops <500 ms). Sources: `feed|explore|search|daily|pack|other` (16-char cap server-side).
* **Gate** (`gateOpen`, lines 73-89): real-API mode AND in-memory access token AND `isAuthenticated` AND `isAdult(user.date_of_birth)` (18+) AND `localStorage['jokesfor-consent'].analytics === true`. Any throw → closed. Anonymous readers are never tracked (their reveals go through `POST /jokes/{id}/reveal/` instead).
* **Batching**: in-memory queue; flush at 10 events, max 50/batch (BE `MAX_BATCH=50`), plus on `visibilitychange→hidden` and `pagehide`. `useWatchTracking` also calls `flush()` explicitly.
* **Endpoint**: `${VITE_API_URL}/telemetry/events` (no trailing slash — matches BE `path('telemetry/events', …)`, `jokes/urls.py:66`). BE returns `202 {accepted}`; `IsAuthenticated`.
* **Transport** (lines 95-127): tries `navigator.sendBeacon(ENDPOINT, Blob(application/json))` **first on every flush**; only if the beacon call throws or returns `false` does it fall back to `fetch(..., {keepalive:true, credentials:'include', Authorization: Bearer})`.
  * **Finding 1**: beacon → no `Authorization` header → `JWTCookieAuthentication` cookie path → `enforce_csrf` (`JWT_AUTH_COOKIE_USE_CSRF=True`) → no `X-CSRFToken` header on a beacon → `403 CSRF Failed`. (Additionally, a JSON-typed Blob beacon needs a CORS preflight; `x-csrftoken` is allowed but irrelevant because the beacon can't send it.) The in-code comment "the backend also accepts the httpOnly refresh/session cookie… so beacon stays authenticated" predates CSRF enforcement (memory: CSRF enforcement shipped after telemetry). Unit tests stub `sendBeacon` to return `true` and assert on it, so tests pass while prod drops events. Fix options (not applied): use `fetch keepalive` for normal flushes and reserve beacon for `pagehide`; or exempt/`authentication_classes` the ingest view from CSRF for cookie auth; or have the FE append the CSRF token as a query param/form field (Django checks `csrfmiddlewaretoken` form field or header only — a `multipart/form-data` beacon could carry it).
* `recordShare()` (`features/telemetry/recordShare.ts`) is separate: `POST /jokes/{id}/share/ {platform}` via axios (Bearer), only in real mode + authenticated; FE `SharePlatform` set == BE `ShareEvent.PLATFORM_CHOICES` (`copy,twitter,facebook,whatsapp,other`).

---

## 6. `src/lib/dailyReset.ts` and client-side paywall

* `nextDailyResetInstant(resetAt?, now)` → parses server `reset_at` if valid, else next 00:00:00 UTC. `timeUntilDailyReset` → `{h,m}` never negative. `dailyResetLocalLabel` → local-time string. Pure/injectable `now` for tests. (Comment notes this replaced an older "9 AM local" assumption.)
* Paywall client logic (`features/daily-reads/api.ts` + `store.ts`): server `GET /jokes/daily-reads/` (AllowAny; BE `jokes/views.py:400-413` returns `{limit, used, remaining, over, reset_at}`; `limit:null` = unlimited). FE `active` only when `limit` is numeric. Session store keeps `revealedIds` (Set), `optimisticSpent` (decrements `remaining` immediately; reset to 0 whenever `dataUpdatedAt` changes) and `nudgeDismissed`. `canReveal(id)` = already revealed OR not active OR remaining>0. Hard boundary is server-side `is_locked` stripping in `JokeSerializer`.
* Anonymous reveal: `FlowJokeCard.handleReveal` (lines 116-131) → `registerReveal` → if authenticated `trackReveal` (telemetry); else `POST /jokes/{id}/reveal/` (BE `JokeRevealView`, AllowAny; 204 for authenticated users, 200 with counters for anon and sets the anon-read cookie via `record_anon_read`) then invalidates `['daily-reads']`.
* `KNOWN_LIMITS.free_joke_reads_per_day = 10` (BE `billing/entitlements.py:33`); FE `BillingEntitlements.limits` type omits this key (extra key ignored at runtime).

---

## 7. `src/lib/firebase.ts`

Lazy, idempotent: nothing runs at import. `initAnalytics()` memoises a promise; returns `null` when `VITE_FIREBASE_MEASUREMENT_ID` is empty or `isSupported()` is false. Called only from `features/consent/useConsent.ts:25` after analytics consent. No Firebase Auth/Firestore usage anywhere in the data layer.

---

## 8. `src/lib/api-adapter.ts` — mock vs real per feature

Adapters are the seam every feature hook uses (except those that import `api.ts` objects directly). `USE_MOCKS` selects `mock-api.ts` implementations; real path unwraps `r.data` and maps DTO→view-model where the UI is camelCase.

| Adapter | Mock impl | Real impl (api.ts) | DTO mapping in real path |
|---|---|---|---|
| `jokesAdapter` | `mockJokesApi` (filters `mockJokes` by q/tones/age_rating/context_tags; `paginateMock`) | `jokesApi` | passthrough |
| `dailyJokeAdapter` | `mockDailyJokeApi` | `dailyJokeApi` | passthrough (history **wrongly** assumed paginated) |
| `collectionsAdapter` | `mockCollectionsApi` | `collectionsApi` | passthrough |
| `savedJokesAdapter` | `mockSavedJokesApi` | `savedJokesApi` | omits `collection` unless truthy id |
| `trendingAdapter` | `mockTrendingApi` | `trendingApi` | snake→camel (`trending_since→trendingSince`, `growth_percent→growth`, `punchline_count→punchlineCount`) |
| `favoritesAdapter` | `mockFavoritesApi` | `favoritesApi` | `favorited_at→favoritedAt`; `remove(jokeId)` = list then DELETE by favorite id; stats snake→camel |
| `draftsAdapter` (legacy) | `mockDraftsApi` | `draftsApi` | `draftFromDTO`/`draftToDTO` (broken vs BE, finding 6) |
| `profileAdapter` | `mockProfileApi` | `profileApi` | maps real `/users/me/profile/` (`name, username, display_name, handle, email, bio, avatar_url, member_since, is_premium, stats{…}, humor_dna[]`) → `ProfileView`; activity rows `{id:'rating_5', type, description, created_at}` → icon+relative time; achievements `{id:slug,title,description,icon,unlocked,unlocked_at}` |
| `accountIdentityAdapter` | in-memory `mockIdentity` | `profileApi.get/update` | `{display_name, handle, name, username}` |
| `notificationsAdapter` | seeded 5-item inbox (all 5 verbs) | `notificationsApi` | list → `.results`; unread → `.count` |
| `moderationAdapter` | in-memory `mockBlocked`, report no-op | `moderationApi` | `myBlocks` → `.results` |
| `appealsAdapter` | in-memory `mockAppeals` | `appealsApi` | `myAppeals` maps 404 → `[]` |
| `creatorInsightsAdapter` | `mockCreatorInsightsApi` | `creatorInsightsApi` | passthrough |
| `followsAdapter` | `mockFollowsApi` (Set) | `followsApi` | passthrough |
| `creatorProfileAdapter` | `mockCreatorProfileApi` | `creatorProfileApi` | `normalizeProfileJoke`: BE `JokeListSerializer` emits tones/categories/format/age_rating as **slug strings**; adapter converts to `{id,name,slug}` objects (negative synthetic ids) so `JokeCard` works |
| `preferencesAdapter` | `mockPreferencesApi` | `preferencesApi` | camel↔snake (`toDTO`/`fromDTO`); gated by `USE_REAL_PREFERENCES` |
| `billingAdapter` | `mockBillingApi` (stateful plan slug) | `billingApi` | passthrough |
| `tipsAdapter` | `mockTipsApi` (stateful sent list, tier allowlist) | `tipsApi` | passthrough |
| `contentAdapter` (`features/create/adapter.ts`) | `features/create/mock.ts` | `contentApi` (`features/create/api.ts`) | `fromDTO`/`toPatchBody`; `unwrapList` tolerates array **or** `{results}`; submit = POST then re-GET detail; gated by `VITE_USE_REAL_CREATE` only |

**Never mocked (always real when called)**: `authApi`, `dailyReadsApi` (hook short-circuits to `null` in mock mode), `revealApi`, `reactionsApi`, `sharesApi` (no-op in mock mode), `activityApi`, `streakApi`, `packsApi`, `todayStatusApi`, `insightsApi`, `jokeDetailApi`, `vibesApi`, `mysteryBoxApi`, `contentApi` catalog endpoints when `VITE_USE_REAL_CREATE`. In `VITE_USE_MOCKS=true` local dev these hooks hit `localhost:8000` and fail (they are all on `/flow`, `/flow-canvas`, `/explore`, `/jokes/:id`, `/packs/:slug`, onboarding). `mockAuthApi` exists in `mock-api.ts:182-187` but is unused.

`mock-data.ts` exports: `mockUser`, `mockJokes`, `mockDailyJoke(+History)`, `mockCollections`, `mockSavedJokes`, `mockVibeCards`, `mockTopJokesters`, `mockPopularThemes`, `mockHotNowTags`, `mockTrendingTags(+WithStats)`, `mockAuthors`, `mockRisingTopics`, `mockTrendingJokes`, `mockFavorites`, `mockDrafts`, `mockUserProfile`, `mockActivity`, `mockAchievements`, `mockPreferences`, `mockCreatorInsights`, `mockCreatorProfile`, `mockPublicUsers`, `mockBillingPlans`, `mockMySubscription`, `mockBillingEntitlements`, `paginateMock()` plus the legacy camelCase view types (`TrendingJoke`, `TrendingTag`, `TopJokester`, `FavoriteJoke`, `DraftJoke`, `UserProfile`, `ActivityItem`, `Achievement`, `UserPreferences`). Mock delays are 200–800 ms random.

---

## 9. FE feature → backend endpoint matrix (cross-checked against BE URLconfs)

BE mount points (`JokesForProject/urls.py:50-79`): `api/v1/` → `jokes.urls`; `api/v1/creators/` → `creator_insights.urls`; `api/v1/follows/` → `follows.urls`; `api/v1/users/` → `follows.user_urls`; `api/v1/billing/` → `billing.urls`; `api/v1/tips/` → `billing.tip_urls`; `api/v1/auth/` → dj_rest_auth + `notifications.urls`; `api/v1/notifications/` → `inbox.urls`.

Legend — Mode: R = always real, M/R = adapter mock in mock mode / real otherwise, R* = real only with an extra flag. Shape: ✓ matches, ⚠ divergence noted.

| FE feature / caller | Method + path (relative to `/api/v1`) | BE view (file:line) | Auth | Mode | Shape |
|---|---|---|---|---|---|
| auth login | POST `/auth/login/` | dj_rest_auth `LoginView` | anon | R | ✓ `{user, access, refresh:""}` |
| auth register | POST `/auth/registration/` | `CookieRegisterView` jokes/views.py:821 | anon | R | ✓ gated → `{detail,email}` 201; 502 on email-send failure |
| auth logout | POST `/auth/logout/` | dj_rest_auth | cookie | R | ✓ |
| auth google | POST `/auth/google/` `{code, redirect_uri?, date_of_birth?}` | `GoogleLogin` :893 | anon | R | ✓ (400 `dob_required` handled) |
| auth user | GET/PATCH `/auth/user/` | dj_rest_auth `UserDetailsView` (`JokesForUserDetailsSerializer` adds read-only `date_of_birth`) | Bearer | R | ✓ |
| auth refresh | POST `/auth/token/refresh/` | `RefreshViewWithCookieSupport` | cookie | R | ✓ `{access, access_expiration}` |
| auth verify token | POST `/auth/token/verify/` | simplejwt | – | R | defined, unused |
| auth password change/reset/confirm | POST `/auth/password/change/`, `/auth/password/reset/`, `/auth/password/reset/confirm/` | dj_rest_auth (`FrontendPasswordResetSerializer`) | – | R | ✓ |
| auth verify email / resend | POST `/auth/verify-email/`, `/auth/resend-verification/` | notifications/views.py `VerifyEmailView`, `ResendVerificationView` (throttle `3/15min`) | anon | R | ✓ `{user}` / `{detail}` |
| auth CSRF | GET `/auth/csrf/` | `csrf_token_view` :797 | none | R | ✓ `{csrfToken}` |
| account delete | DELETE `/users/me/` | `UserAccountDeleteView` :2399 | Bearer | R | ✓ 204 |
| data export | GET `/users/me/data-export/` | `DataExportView` :2499 | Bearer | R | ✓ zip blob |
| jokes search (Explore/Search/FlowCanvas) | GET `/jokes/?q&joke_format&age_rating&tones&context_tags&culture_tags&language&page&page_size&vibe&ordering` | `JokeViewSet.list` :270 | AllowAny | M/R | ⚠ `page_size` ignored (finding 4); `joke_format` not comma-split (finding 5); `categories`/`themes` synonyms **not** read by BE (FE comment at api.ts:228 is wrong, but FE never sends them) |
| joke detail | GET `/jokes/{id}/?source=` | `JokeViewSet.retrieve` :175 (logs `JokeView`, 60 s debounce; sources `daily,search,explore,mystery,pack,saved,share,other` == FE `JokeSource`) | AllowAny | R (`jokeDetailApi`), M/R (`jokesAdapter.getById`, unused) | ✓ |
| joke random | GET `/jokes/random/` | `.random` :363 | – | M/R | unused by pages |
| rate / my-rating | POST `/jokes/{id}/rate/`, GET `/jokes/{id}/my-rating/` | `.rate` :424 (`{rating,created,joke_score}`), `.get_rating` :455 | Bearer | M/R | ✓ (FE ignores `created`); unused by pages |
| reactions | POST `/jokes/{id}/react/ {reaction}`, GET `/jokes/{id}/reactions/` | `.react` :491, `.reactions` :532 | Bearer / any | R | ✓ `{my_reaction, counts}` |
| share | POST `/jokes/{id}/share/ {platform}` | `.share` :614 → 201 `{status,share_url,joke_id}` | any | R (no-op in mock) | ✓ (FE ignores body) |
| trending jokes | GET `/jokes/trending/?period=` | `.trending` :552 (period `today|week|month`) | AllowAny | M/R | ✓ paginated `{rank,joke,likes,shares,comments:0,trending_since}` |
| daily reads | GET `/jokes/daily-reads/` | `.daily_reads` :400 | AllowAny | R (null in mock) | ✓ |
| reveal (anon) | POST `/jokes/{id}/reveal/` | `JokeRevealView` :647 | AllowAny | R | ✓ 204 auth / 200 counters anon |
| telemetry | POST `/telemetry/events` (fetch/beacon, not axios) | `TelemetryIngestView` :3287 | **IsAuthenticated** | R | ⚠ beacon path 403 (finding 1) |
| daily today | GET `/daily-jokes/today/` | `DailyJokeViewSet.today` :1169 | AllowAny (anon = random editorial, **no `issue_label`**, no `id/delivered_at`) | M/R + R (`insightsApi.todayAugmented`) | ✓ (FE `issue_label` optional; `DailyJokeToday.id/delivered_at` absent for anon) |
| daily history | GET `/daily-jokes/history/` | `.history` :1299 (entitlement window) | Bearer | M/R | ⚠ **bare array vs `PaginatedResponse`** (finding 2) |
| daily tomorrow | GET `/daily-jokes/tomorrow/` | `.tomorrow` :1255 | Bearer | R | ✓ `{date, issue_label, preview, format}` (`format` may be `null`; FE type says `string`) |
| collections | GET/POST `/collections/`, PATCH/DELETE `/collections/{id}/`, GET `/collections/{id}/jokes/` | `CollectionViewSet` :936 | Bearer | M/R | ✓ |
| saved jokes | GET/POST `/saved-jokes/`, DELETE `/saved-jokes/{id}/`, GET `/saved-jokes/search/?q` | `SavedJokeViewSet` :1030 (search 400 without `q`) | Bearer | M/R | ✓ |
| favorites | GET/POST `/favorites/`, DELETE `/favorites/{id}/`, GET `/favorites/stats/` | `FavoriteViewSet` :1814 | Bearer | M/R | ✓ `{total_count, top_tone, this_week_count}` |
| legacy drafts | GET `/jokes/my-drafts/`, GET/PATCH/DELETE `/jokes/my-drafts/{id}/`, POST `/jokes/my-drafts/{id}/submit/`, POST `/jokes/submit/` | `JokeDraftListView` :1648, `JokeDraftDetailView` :1726, `JokeDraftSubmitView` :1774, `JokeSubmitView` :1629 | Bearer | M/R | ⚠ finding 6 (legacy only) |
| create (editor) | GET `/jokes/my-drafts/?page_size=100`, POST `/jokes/my-drafts/ {format, age_rating?}`, GET/PATCH/DELETE `/jokes/my-drafts/{id}/`, POST `/jokes/my-drafts/{id}/submit/` | same views; list serializer `JokeSubmissionListSerializer` (slug strings, `status: draft|pending|published|rejected`, `last_edited_at`, `media`, `likes`, `rejection_reason`) | Bearer | R* (`VITE_USE_REAL_CREATE`) | ✓ except `page_size` cap 10 (finding 4); PATCH response omits `media` (handled by re-GET) |
| media upload | POST `/media/uploads/` multipart `{file, kind}` | `MediaUploadView` :1480 (throttle `30/hour`) | Bearer | R* | ✓ `MediaAssetDTO` |
| catalog | GET `/formats/`, `/age-ratings/`, `/tones/`, `/context-tags/`, `/culture-tags/`, `/languages/` | router ReadOnlyModelViewSets :691-721 (**paginated**, 10/page) | any | R* | ✓ via `unwrapList`; ⚠ any catalog with >10 rows is truncated |
| profile | GET/PATCH `/users/me/profile/` | `UserProfileView` :1922 (PATCH accepts `first_name,last_name,bio,display_name,handle`) | Bearer | M/R | ✓ (FE `UserProfileDTO` is stale/speculative; adapter maps the real shape) |
| activity / achievements | GET `/users/me/activity/?limit`, GET `/users/me/achievements/` | :2008 / :2059 → `{results:[…]}` (not DRF-paginated) | Bearer | M/R | ✓ (adapter reads `.results`) |
| preferences | GET/PATCH `/users/me/preferences/` | `UserPreferencesView` :2084 | Bearer | R* (`USE_REAL_PREFERENCES`, true in prod) | ⚠ finding 7 |
| complete onboarding | POST `/preferences/complete-onboarding/` | `UserPreferenceViewSet.complete_onboarding` :778 | Bearer | R | defined, **unused** |
| vibes | GET `/vibes/`, GET `/vibes/{slug}/`, GET/PUT `/users/me/vibes/ {slugs}` | `VibeViewSet` :2664 (`pagination_class=None`), `UserVibesView` :2676 | any / Bearer | R | ✓ |
| mystery box | GET `/mystery-box/status/`, POST `/mystery-box/roll/` | :2774 / :2792 (429 cap, 404 pool exhausted) | Bearer | R | ✓ (`source_vibe` is a full `VibeSerializer` object, FE types subset) |
| recently viewed | GET `/users/me/recently-viewed/?limit` | `RecentlyViewedView` :2854 → array of `JokeViewSerializer` (`joke, source, revealed_punchline, viewed_at`) | Bearer | R | ✓ (hook unused) |
| streak | GET `/users/me/streak/`, POST `/users/me/streak/freeze/`, POST `/users/me/streak/freeze/remove/` | :2915 / :2929 / :2960 | Bearer | R | ✓ |
| packs | GET `/packs/`, GET `/packs/{slug}/`, GET `/packs/featured/`, POST `/packs/{slug}/progress/ {entry_order}`, GET `/users/me/packs/in-progress/` | `JokePackViewSet` :2988, `JokePackProgressView` :3038, `JokePackInProgressView` :3074 | any / Bearer | R | ⚠ progress response shape (finding 8, harmless) |
| today status | GET `/users/me/today-status/` | `DailyRitualStatusView` :3096 | Bearer | R | ✓ (hook unused) |
| taste profile | GET `/users/me/taste-profile/?period` | `TasteProfileView` :3201 | Bearer | R | ✓ |
| trending tags / rising / themes / jokesters | GET `/tags/trending/`, `/tags/rising/`, `/themes/popular/`, `/users/top-jokesters/?limit&period` | :2153 / :2178 / :2257 / :2206 → `{results:[…]}` | AllowAny | M/R | ✓ (`growth_percent` always 0 for trending tags; `avatar_url` always null) |
| creator insights | GET `/creators/me/insights/?period` | creator_insights/views.py:21 (`IsCreator`, `HasFeature('creator_analytics')`, throttle `120/hour`) | Bearer | M/R | ✓ |
| creator profile | GET `/creators/{id}/profile/?page` | :48 (404 if no published jokes or blocked pair; jokes via `JokeListSerializer` slug strings) | AllowAny | M/R | ✓ via `normalizeProfileJoke` |
| follows | POST/DELETE `/follows/{id}/`, GET `/follows/{id}/status/` | follows/views.py:18 / :43 | Bearer | M/R | ✓ (`FollowStatus`) |
| moderation | POST `/reports/ {joke, reason, description?}`, POST/DELETE `/users/{id}/block/`, GET `/users/me/blocks/` | :2275 / :2355 / :2384 (`PublicUserSerializer` = `{id,name,username,avatar_url}` == FE `BlockedUser`) | Bearer | M/R | ✓ |
| appeals | POST `/appeals/ {joke_id?|submission_id?, reason_text}`, GET `/users/me/appeals/` | :2308 (throttle `10/day`) / :2343 (paginated) | Bearer | M/R | ✓ `AppealSerializer` verbatim |
| notifications | GET `/notifications/`, GET `/notifications/unread-count/`, POST `/notifications/mark-read/` | inbox/views.py:10 / :25 / :34 | Bearer | M/R | ✓ (`data` always present on BE; FE optional) |
| billing | GET `/billing/plans`, GET `/billing/my-subscription`, GET `/billing/entitlements`, POST `/billing/checkout-session {plan_slug}`, POST `/billing/portal-session` | billing/views.py:35 / :290 / :310 / :44 / :219 (no trailing slashes — matches) | anon / Bearer | M/R | ✓; 503 `billing_unavailable`, 409 `active_subscription`+`portal_url`, 422, 404 handled; no-subscription fallback returns `stripe_customer_id: ''` (FE type `string|null`) |
| tips | POST `/tips/checkout/ {creator_id, joke_id?, amount_cents}`, GET `/creators/{id}/tips/summary/`, GET `/users/me/tips/` | `TipCheckoutView` :101 (throttle `30/hour`, tiers 100/300/500/1000), `CreatorTipsSummaryView` :187, `MyTipsView` :206 (paginated, `TipSerializer` adds `creator_name`) | Bearer / anon / Bearer | M/R | ✓ |

### Backend routes the FE never calls
`GET /collections/trending/` (:999), `GET /follows/{id}/followers/`, `GET /users/me/following/`, `GET /preferences/me/` (router `UserPreferenceViewSet.me`), `POST /preferences/complete-onboarding/` (defined in FE, unused), `POST /billing/webhook`, `/email/unsubscribe/`, `/internal/run-digests/`, `/jokes/{id}/share/` HTML page (non-API), `/sitemap.xml` (used only at build time), `/healthz`, `/readyz`, `/api/schema|docs|redoc`.

---

## 10. Browser storage keys (complete list)

| Key | Storage | Owner | Contents |
|---|---|---|---|
| `jokesfor-auth` | `sessionStorage` (custom storage adapter) | `features/auth/store.ts:58-76` | Zustand persist JSON `{state:{user, accessToken, isAuthenticated}, version}` — **access token in sessionStorage** |
| `jokesfor-csrf` | `sessionStorage` | `lib/axios.ts:39` | CSRF token value string |
| `jokesfor-consent` | `localStorage` | `features/consent/storage.ts:2` | `{version:1, analytics:boolean, ts}` — gates GA + telemetry |
| `jokesfor-onboarding` | `localStorage` (zustand default) | `stores/onboarding.store.ts:40` | `{currentStep,totalSteps,selectedHumorTypes,isComplete}` |
| `jokesfor-creator` | `localStorage` (zustand default) | `features/create/store.ts:25` | `{lastSeenAt}` (creator hub "unseen change" dot) |
| `auth.returnTo` | `sessionStorage` | `features/auth/google-oauth.ts:18` | post-OAuth redirect path (read-and-clear) |
| `auth.signupDob` | `sessionStorage` | `features/auth/google-oauth.ts:19` | DOB stashed across the Google redirect for new users |

Server-set cookies relevant to the FE (not JS-readable except `csrftoken`): `jokes-access-token` (httpOnly, 15 min), `jokes-refresh-token` (httpOnly, 1 day, rotated), `csrftoken` (`CSRF_COOKIE_HTTPONLY=False`, but cross-site so unreadable anyway), plus the anonymous paywall ledger cookie written by `record_anon_read` (BE `jokes/serving.py`, name not inspected here).

---

## 11. Hooks/functions defined in the data layer but with no page/component consumer
`useCurrentUser`, `useRandomJoke`, `useJoke`, `useUnsaveJoke`, `useAddFavorite`, `useRemoveFavorite`, `useDeleteCollection`, `useFreezeStreak`, `useUnfreezeStreak`, `useRecentlyViewed`, `useTodayStatus`, `usePacks`, `useFollowStatus` (used only inside `features/follows` `FollowButton`? — grep excluded feature internals; verify), `useMyTips`, `useUpdateProfile`, `usePatchDraft` (autosave engine calls `contentAdapter` directly), `authApi.verifyToken`, `preferencesApi.completeOnboarding`, `vibesApi.get`, `mockAuthApi`, `mockPublicUsers`, `mockBillingEntitlements`, FE type `PublicUser` (`{id, display_name, handle}` — does **not** match BE `PublicUserSerializer` `{id,name,username,avatar_url}`; only used by unused mock data).

---

## 12. Doc vs code disagreements observed
* `Docs/API_Specification_For_Frontend.md:312-330` — `/daily-jokes/history/` documented as paginated; BE returns array (tests `jokes/test_paywall.py:235`, `jokes/test_time_progression.py:288`).
* `src/lib/api.ts:228` comment "backend accepts either name" for `categories`/`themes` search params — BE `JokeViewSet.list` only reads `tones`/`context_tags`.
* `src/lib/api.ts:363-376` block comment says adapters "default to mocks until shapes confirmed" — in reality every adapter is real whenever `VITE_USE_MOCKS !== 'true'` (prod); only `create` and `preferences` have extra flags, both `'true'` in merge deploys.
* `src/lib/telemetry.ts:101-103` comment claims the beacon "stays authenticated" via cookie — no longer true with CSRF enforcement.
* `src/content/legal/cookie.ts:18` says the token is in `localStorage`; it is in `sessionStorage`.
* `src/lib/api.ts:429-446` `UserProfileDTO` is marked speculative and does not match `UserProfileView`; the adapter uses its own `RealUserProfile` interface instead.

---

## 13. Behaviours the test pipeline should verify (GIVEN/WHEN/THEN)
See the structured summary; the same list is reproduced here for completeness.

1. GIVEN a logged-in reader with analytics consent and an 18+ DOB in real-API mode, WHEN 10 joke cards become visible, THEN exactly one `POST /api/v1/telemetry/events` reaches the backend and returns 202 with `accepted ≥ 1` (currently expected to FAIL with 403 via the beacon path).
2. GIVEN a request with the `jokes-access-token` cookie, no `Authorization` header and no `X-CSRFToken`, WHEN it POSTs to `/api/v1/telemetry/events`, THEN the backend responds 403 `detail: "CSRF Failed: …"`.
3. GIVEN an authenticated user with ≥1 past `DailyJoke`, WHEN the FE calls `GET /api/v1/daily-jokes/history/`, THEN the body is a JSON array (not `{count,next,previous,results}`) and the `/daily` "Previous daily jokes" section should render those entries (currently renders empty).
4. GIVEN `hasSearchParams` in `features/jokes/api.ts`, WHEN `useJokeSearch({vibe:'puns', page_size:3})` is rendered, THEN the query is `enabled` and a `GET /jokes/?vibe=puns&page_size=3` request is issued (currently `enabled:false`).
5. GIVEN any list endpoint, WHEN `?page_size=30` is sent, THEN the backend still returns at most 10 `results` (documenting the cap; a fix would add `page_size_query_param`).
6. GIVEN a creator with 11+ drafts/submissions, WHEN the creator hub loads (`GET /jokes/my-drafts/?page_size=100`), THEN only 10 appear (regression target).
7. GIVEN Explore with two format chips selected, WHEN `GET /jokes/?joke_format=setup,oneliner` is issued, THEN the backend returns 0 results (documenting finding 5).
8. GIVEN a cookie-authenticated mutation that 403s with `detail` containing `CSRF`, WHEN the axios interceptor runs, THEN it fetches `/auth/csrf/` once and replays the request exactly once with the new `X-CSRFToken`, and never loops.
9. GIVEN an expired in-memory access token, WHEN two API calls 401 concurrently, THEN exactly one `POST /auth/token/refresh/` is made and both originals are replayed with the new Bearer token.
10. GIVEN refresh fails (401 on `/auth/token/refresh/`), WHEN the interceptor rejects, THEN `accessToken` is null but the Zustand store is unchanged (no automatic logout/redirect) — verify the UX consequence.
11. GIVEN a fresh tab with the `jokes-refresh-token` cookie, WHEN `AuthProvider` mounts, THEN it calls `GET /auth/csrf/`, `POST /auth/token/refresh/`, `GET /auth/user/` (Bearer) and sets `isAuthenticated=true`; without the cookie it sets `isLoading=false` and stays anonymous with no retry.
12. GIVEN `EMAIL_VERIFICATION_REQUIRED=true`, WHEN registration succeeds, THEN the response is 201 `{detail,email}` and the FE does **not** set auth state; WHEN `POST /auth/verify-email/` succeeds, THEN the FE performs a refresh and ends authenticated.
13. GIVEN `VITE_USE_MOCKS=true` (or no `VITE_API_URL`), WHEN `useDailyReads` runs, THEN no network request is made and `active=false`; GIVEN real mode and `GET /jokes/daily-reads/` 404s, THEN `active=false` and nothing is thrown.
14. GIVEN a free user with `remaining=1`, WHEN they reveal a new joke, THEN `remaining` shows 0 immediately (optimistic), the joke stays open, `canReveal` of another unseen joke is false, and after the next `/daily-reads/` refetch `optimisticSpent` resets to 0.
15. GIVEN an anonymous reader, WHEN they reveal a joke, THEN `POST /jokes/{id}/reveal/` is called and returns 200 with `{limit,used,remaining,over,reset_at}` and the `['daily-reads']` query is invalidated; GIVEN an authenticated reader, THEN no reveal POST is made and a telemetry `reveal` event is enqueued instead.
16. GIVEN `reset_at` is absent, WHEN `nextDailyResetInstant(undefined, now)` is called, THEN it returns the next 00:00:00 UTC; GIVEN a valid `reset_at`, THEN that instant is returned; `timeUntilDailyReset` never returns negative values.
17. GIVEN telemetry, WHEN the same `(type,joke,source)` impression/reveal is tracked twice in a page-session, THEN only one event is enqueued; WHEN dwell/watch are tracked twice, THEN both are enqueued; dwell <1000 ms and non-finite values are dropped; watch is clamped to 600000.
18. GIVEN a logged-out or under-18 or non-consenting user, WHEN any `track*` is called, THEN the queue stays empty and no request is sent; GIVEN the gate closes mid-session, WHEN `flush()` runs, THEN the queue is discarded silently.
19. GIVEN a mutating request, WHEN `csrfToken` is known, THEN `X-CSRFToken` is present; GIVEN a GET, THEN it is absent.
20. GIVEN a favorite removal by joke id, WHEN `favoritesAdapter.remove` runs in real mode, THEN it first `GET /favorites/` and then `DELETE /favorites/{favoriteId}/`; if the joke is not in the first page of favorites the delete is skipped silently.
21. GIVEN a creator profile response with slug-string `tones`/`format`, WHEN `normalizeProfileJoke` runs, THEN each becomes `{id,name,slug}` objects and `JokeCard` renders without throwing.
22. GIVEN `GET /users/me/appeals/` returns 404, WHEN `useMyAppeals` runs, THEN it resolves to `[]`; any other error propagates.
23. GIVEN `POST /billing/checkout-session` returns 409 `{code:'active_subscription', portal_url}`, WHEN the billing page handles the error, THEN `isActiveSubscriptionConflict` is true and `getConflictPortalUrl` returns the URL; 503 → `isBillingUnavailable`.
24. GIVEN `POST /tips/checkout/` with `amount_cents` not in `{100,300,500,1000}`, THEN 400 `code:'invalid_amount'`; self-tip → 400 `self_tip`; non-creator → 400 `not_a_creator`.
25. GIVEN `VITE_USE_REAL_CREATE` unset, WHEN a prod-like build runs, THEN the editor uses `features/create/mock.ts` (PR previews); GIVEN it is `'true'`, THEN `POST /jokes/my-drafts/ {format}` creates a `status:'draft'` row and PATCH autosave returns 200 even when per-format validation would fail, while `POST /jokes/my-drafts/{id}/submit/` returns 400 with field errors for an incomplete draft and `{id,status:'pending'}` on success.
26. GIVEN `PATCH /users/me/preferences/` with `notification_time`, `tones`, `streak_saver_enabled`, THEN the backend ignores them and the GET response never contains those keys (documenting finding 7).
27. GIVEN mock mode (`VITE_USE_MOCKS=true`), WHEN `/flow-canvas` renders, THEN hooks that bypass adapters (`useStreak`, `useMysteryBoxStatus`, `useTomorrowTeaser`, `useFeaturedPack`, `usePacksInProgress`, `useTasteProfile`, `useVibes*`, `useReactions`) issue real requests to `localhost:8000` and fail — mock mode is not a complete offline demo for the flow surfaces.
28. GIVEN a `sessionStorage` `jokesfor-auth` record, WHEN the app reloads, THEN axios immediately carries the stored Bearer token (possibly expired) and `isAuthenticated` is true before `AuthProvider`'s refresh completes.
