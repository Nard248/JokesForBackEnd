# Frontend Integration Handout

> **What this is:** Everything the frontend team needs to consume the deployed backend.
> URLs, CORS contract, cookie behavior, auth flows with working snippets, common
> errors with fixes, and the OAuth client setup steps.
>
> **What this is *not*:** A per-endpoint reference — that's [`API_Specification_For_Frontend.md`](./API_Specification_For_Frontend.md). Refer to it for request/response shapes of every route.

**Last verified live:** 2026-05-09 against revision `jokesforbackend-00010-7pw` on Cloud Run.

> **Vocabulary update (P1 of Pivot Plan, 2026-05-09)**: every joke + preference response now includes the new design-aligned field names alongside the originals. Both work indefinitely — pick one and stick with it.
>
> - `tones` ⇄ `categories` (synonyms — "how the joke feels")
> - `context_tags` ⇄ `themes` (synonyms — "what the joke is about")
> - `preferred_tones` ⇄ `preferred_categories`
> - `preferred_contexts` ⇄ `preferred_themes`
>
> Write paths accept either name. If both are present, the new name wins. See [Pivot_Plan.md §2](../Pivot_Plan.md) for the full taxonomy rationale.

---

## 1. Production endpoints

| Surface | URL |
|---|---|
| **Backend (Django on Cloud Run)** | `https://jokesforbackend-332865216810.us-east1.run.app` |
| API base path | `/api/v1` |
| OpenAPI schema (live) | `/api/schema/` (YAML) — also reachable as `/api/docs/` (Swagger UI) and `/api/redoc/` (ReDoc) |
| **Frontend origins (whitelisted)** | `https://jokesforfront.web.app` |
| | `https://jokesforfront.firebaseapp.com` |
| | `https://jokesfor.net` |
| Local dev origin | `http://localhost:5173` |

**Architecture is cross-origin (not same-site).** Browser requests go directly from `jokesforfront.web.app` (or `jokesfor.net`) to `*.run.app`. CORS is the contract that lets this work; cookies traverse origins because of `SameSite=None; Secure`.

---

## 2. The CORS contract — everything depends on this

The backend will accept credentialed requests **only** from the three frontend origins above. From any other origin, the browser blocks the response.

| Backend response header | Value |
|---|---|
| `Access-Control-Allow-Origin` | echoes the request's `Origin` if it's whitelisted |
| `Access-Control-Allow-Credentials` | `true` |
| `Access-Control-Allow-Methods` | `DELETE, GET, OPTIONS, PATCH, POST, PUT` |
| `Vary` | `origin` (so caches don't mix per-origin responses) |

Verified live by OPTIONS preflight from each origin — see verification probe in §10.

---

## 3. The single most important client-side rule

**Every request to the API must opt into credentials mode**, otherwise the browser sends no cookies and you get `401 Authentication credentials were not provided.`

### `fetch`
```js
fetch('https://jokesforbackend-332865216810.us-east1.run.app/api/v1/auth/user/', {
  credentials: 'include',           // ← required
})
```

### `axios`
```ts
import axios from 'axios';

export const api = axios.create({
  baseURL: 'https://jokesforbackend-332865216810.us-east1.run.app/api/v1',
  withCredentials: true,            // ← required
  headers: { 'Content-Type': 'application/json' },
});
```

### `XMLHttpRequest`
```js
xhr.withCredentials = true;         // ← required
```

**You cannot read the auth cookies from JS.** They're `HttpOnly`. That's intentional — XSS can't exfiltrate them. Trust the browser to attach them automatically once `credentials: 'include'` is set.

---

## 4. Cookies the backend sets — what to expect

After a successful login / registration / OAuth, the response will include these `Set-Cookie` headers:

| Cookie | Lifetime | Purpose | JS-readable? |
|---|---|---|---|
| `jokes-access-token` | 15 min | JWT access token; sent on every API call | No (HttpOnly) |
| `jokes-refresh-token` | 24 h | Used by `/auth/token/refresh/` to mint a new access | No (HttpOnly) |
| `csrftoken` | 1 yr | Django CSRF token; **the API doesn't enforce CSRF**, ignore from JS | Yes |
| `sessionid` | 14 d | Django session — only used by allauth's OAuth flow internals | No (HttpOnly) |
| `messages` | session | Django messages framework | No (HttpOnly) |

All five are set with `SameSite=None; Secure`. The first two are the only ones the frontend needs to care about; the rest are Django machinery.

**Logout** sends `Max-Age=0` for `jokes-access-token` and `jokes-refresh-token`, clearing them.

---

## 5. Authentication flows (working snippets)

The backend supports **two equivalent auth modes** — cookie or Bearer header. Cookie is safer (HttpOnly = no XSS read). Examples below use cookie mode.

### 5.1 Email/password registration

```ts
// POST /api/v1/auth/registration/
const res = await api.post('/auth/registration/', {
  email: 'user@example.com',
  password1: 'SuperSecret123!',
  password2: 'SuperSecret123!',
});
// res.status === 201
// Cookies are now set by the browser; user is authenticated.
// res.data also contains: { access, refresh, user: { pk, username, email, first_name, last_name } }
// You can ignore access/refresh in the body — cookies handle it.
```

### 5.2 Email/password login

```ts
// POST /api/v1/auth/login/
const res = await api.post('/auth/login/', {
  email: 'user@example.com',
  password: 'SuperSecret123!',
});
// res.status === 200, cookies set
```

### 5.3 Google OAuth (server-side code exchange)

This is a **two-step flow** with the auth code as the bridge. The frontend never sees the access token from Google; the backend exchanges the code in privacy.

```ts
// Step 1 — redirect user to Google's consent screen
const params = new URLSearchParams({
  client_id: '332865216810-7kouajjg51jiceqk4g2h0qa3t3nbk4ga.apps.googleusercontent.com',
  redirect_uri: 'https://jokesforfront.web.app/auth/google/callback',
  response_type: 'code',
  scope: 'openid email profile',
  access_type: 'offline',
  prompt: 'consent',
});
window.location.href = `https://accounts.google.com/o/oauth2/v2/auth?${params}`;

// Step 2 — Google redirects back to /auth/google/callback?code=AUTH_CODE
// The callback page extracts `code` from the URL and posts it to the backend:
const url = new URL(window.location.href);
const code = url.searchParams.get('code');
const res = await api.post('/auth/google/', { code });
// res.status === 200, cookies set
// Cookies include the same jokes-access-token / jokes-refresh-token as a regular login.
```

**OAuth client constraints — critical:**
- The OAuth `redirect_uri` you send to Google **must match exactly** what's configured on the OAuth client in GCP Console (scheme + host + path). Currently registered: `https://jokesforfront.web.app/auth/google/callback`, `https://jokesfor.net/auth/google/callback`, plus localhost variants.
- The backend's `GOOGLE_OAUTH_CALLBACK_URL` env var is currently `https://jokesforfront.web.app/auth/google/callback`. **If you initiate OAuth from a different origin (e.g. `jokesfor.net`) using a matching redirect_uri, the backend will reject the code exchange** with `400 redirect_uri_mismatch` because the backend tells Google a different URI when redeeming the code.
- For the demo, use `jokesforfront.web.app`. To switch the canonical OAuth origin to `jokesfor.net`, the backend env var must change too — ping the backend team.

### 5.4 Get current user

```ts
// GET /api/v1/auth/user/
const res = await api.get('/auth/user/');
// 200: { pk, username, email, first_name, last_name }
// 401 if no/expired access cookie — call refresh, then retry (see 5.5)
```

### 5.5 Refresh access token

The access token expires after 15 min. When you get a `401`, refresh:

```ts
// POST /api/v1/auth/token/refresh/
// No body needed — refresh cookie travels automatically.
await api.post('/auth/token/refresh/');
// 200, cookies rotated. Old refresh is blacklisted (replay protection).
```

A typical axios interceptor:

```ts
api.interceptors.response.use(
  res => res,
  async (err) => {
    if (err.response?.status === 401 && !err.config._retried) {
      err.config._retried = true;
      try {
        await api.post('/auth/token/refresh/');
        return api(err.config);    // retry the original request
      } catch {
        // refresh also failed — user must log in again
        window.location.href = '/login';
      }
    }
    return Promise.reject(err);
  }
);
```

### 5.6 Logout

```ts
// POST /api/v1/auth/logout/
await api.post('/auth/logout/');
// 200, both jokes-access-token and jokes-refresh-token cookies cleared.
// The refresh token is also blacklisted server-side.
```

### 5.7 Password reset (email)

```ts
// 1. User submits their email — backend sends them a magic link
await api.post('/auth/password/reset/', { email: 'user@example.com' });

// 2. Email contains a link like:
//    https://app.example.com/reset-confirm?uid=NQ&token=abc123
//    Frontend reads uid and token from URL.

// 3. User submits new password
await api.post('/auth/password/reset/confirm/', {
  uid: 'NQ',
  token: 'abc123',
  new_password1: 'NewSecret123!',
  new_password2: 'NewSecret123!',
});
```

**Email backend is currently `console`** (Django prints emails to Cloud Run logs instead of sending them). To enable real email, set `EMAIL_BACKEND` and SMTP env vars on the Cloud Run service. For demo purposes, the password-reset link can be read from `gcloud run services logs read jokesforbackend --region=us-east1 --project=jokesfor`.

---

## 6. Endpoint catalog (live count: 96)

For request/response shapes per endpoint, see [`API_Specification_For_Frontend.md`](./API_Specification_For_Frontend.md). Quick tour:

### Polish — knock-knock lines + top-jokester vibes (P10 of Pivot Plan)
- `Joke` schema now includes `lines: string[] | null` — array of dialogue lines for `format=knock-knock` jokes; `null` for all other formats. Render as alternating bubbles in the UI.
- `GET /users/top-jokesters/` results now include `top_vibes: [{slug, label, icon}, ...]` (up to 2 vibes per user) — for the "Office · Observ." vibe pill on each leaderboard row.

### Insights — taste profile + tomorrow teaser + issue label (3 endpoints, P9 of Pivot Plan)
- `GET    /users/me/taste-profile/?period=month|week|all` → derived analytics: `{ period, jokes_read, jokes_saved, peak_read_hour, top_vibe, top_themes, top_categories, top_formats, daily_reads_28d }`. Pure computation from JokeView + SavedJoke + UserVibe; no caching layer.
- `GET    /daily-jokes/today/` → existing endpoint, now augmented with `issue_label: "Vol. I · No. 042"` (newspaper-style, computed from earliest DailyJoke date).
- `GET    /daily-jokes/tomorrow/` → preview tomorrow's joke (12-word truncated text for the blurred teaser) + `issue_label`. **Lazy-generates** the DailyJoke row inline if it doesn't exist yet (replaces the Celery beat task per the no-cron constraint).

### Daily ritual settings (1 new endpoint, P8 of Pivot Plan)
- `GET    /users/me/today-status/` → `{ daily_joke_due, has_read_today, today_is_a_notification_day, now_past_notification_time }`. Frontend polls this on Today screen load and renders "Today's joke is ready" hero when `daily_joke_due=true`. Replaces the 9 AM scheduled push (no cron in single-Cloud-Run setup).
- Existing `GET /users/me/preferences/` and `PATCH /preferences/me/` extended with two new fields:
  - `notification_days: ["mon","tue","wed","thu","fri"]` — 7 string-name array
  - `streak_saver_enabled: bool` — gates the in-app `streak_at_risk_today` flag (see Streak section)

### Joke Packs — editorial bundles (5 endpoints, P7 of Pivot Plan)
- `GET    /packs/` → published packs (paginated). Each pack: `{ slug, title, subtitle, description, cover_color, is_featured, joke_count, publish_at, expires_at, user_progress }`. `user_progress` is null for anonymous or new-to-pack users.
- `GET    /packs/{slug}/` → pack detail with `jokes: [{order, joke}]` embedded. 404 for unpublished or expired.
- `GET    /packs/featured/` → single featured pack (Today screen Weekly Special). 404 if none featured.
- `POST   /packs/{slug}/progress/` body `{ "entry_order": N }` → record where the user is. Reaching the last entry sets `completed_at`. Going back un-completes (supports replay).
- `GET    /users/me/packs/in-progress/` → packs the user has started (`last_read_entry > 0`) but not completed. Powers the "Continue mid-sip" surface.

Different from `Collection` (user-private library): packs are editor-curated and shipped to all users; collections are user-owned and private.

### Streak — daily commitment with forgiveness (3 endpoints, P6 of Pivot Plan)
- `GET    /users/me/streak/` → `{ current_count, longest_count, last_active_date, freeze_days_available, freezes_used_total, started_at, last_14_days: [{date, status: read|frozen|missed|pending}], streak_at_risk_today }`
- `POST   /users/me/streak/freeze/` → manually use a freeze day (vacation mode). Returns updated streak. 400 if no freezes available or today already counted as read.
- `POST   /users/me/streak/freeze/remove/` → undo today's accidental freeze. Returns updated streak. 400 if today wasn't frozen.

**Mechanics**: Reading any joke synchronously increments the streak (via `JokeView` post-save signal). Gap reconciliation is **lazy**: when you fetch `/streak/`, the backend walks any gap from `last_active_date+1` to today, burning freezes (2/month, refreshes lazily) for each missed day; if freezes run out, `current_count` resets to 0. `streak_at_risk_today` is true when the user hasn't read today and it's past 8 PM UTC — frontend renders the in-app nudge (no push notifications).

### Activity log + recently viewed (1 endpoint, P5 of Pivot Plan)
- `GET    /users/me/recently-viewed/?limit=20` → chronological list of recently-viewed jokes; powers "continue mid-sip" + Today's "what you've been laughing at" rail
- Every authenticated `GET /jokes/{id}/` automatically logs a `JokeView`. Pass `?source=daily|search|explore|mystery|pack|saved|share|other` so the backend knows the surface — used for taste-profile insights and Mystery Box recent-exclusion. Debounced server-side: same (user, joke) within 60 sec doesn't double-log.

### Reactions — 4-emoji reactions (2 endpoints, P4 of Pivot Plan)
- `POST   /jokes/{id}/react/` body `{ "reaction": "lol" | "crying" | "hmm" | "eyeroll" }` → toggles off if same, switches if different. Returns `{ my_reaction, counts: { lol, crying, hmm, eyeroll } }`.
- `GET    /jokes/{id}/reactions/` → same shape, no-op for the user's reaction; useful for hydrating the joke detail card without an extra `?include=` param.

The legacy `POST /jokes/{id}/rate/` (like/dislike) is **still available** and unchanged — historical analytics keep working. New surfaces should use react/.

### Mystery Box — variable reward (2 endpoints, P3 of Pivot Plan)
- `GET    /mystery-box/status/` → `{ rolls_used_today, rolls_remaining_today, max_per_day }`. Use to render "3 left today" pill.
- `POST   /mystery-box/roll/` → 200 with `{ joke, rolls_remaining_today, source_vibe }` on success. Returns **429** when daily cap (3/day) is reached, **404** if the user's pool is exhausted (rare — every joke saved or already rolled today).

**Pull algorithm**: union of jokes matching the user's selected vibes, falling back to global pool if user has no vibes. Excludes today's prior rolls (no same-day repeats) and already-saved jokes. Cap resets at midnight UTC implicitly via date-bucketed counting (no scheduled task needed).

### Vibes — humor fingerprint (3 endpoints, P2 of Pivot Plan)
- `GET    /vibes/` — catalog of all 12 active vibes (display metadata: slug, label, subtitle, icon, swatch_bg, swatch_fg, order). No pagination.
- `GET    /vibes/{slug}/` — single vibe (e.g. `/vibes/office/`)
- `GET    /users/me/vibes/` — current user's selected vibes; returns `[{ vibe: {...}, weight, created_at }]`
- `PUT    /users/me/vibes/` — replaces selection atomically; body `{ "slugs": ["office","puns","observ"] }`. **Min 3, max 12.** Unknown slugs → 400.
- `GET    /jokes/?vibe=office` — filter jokes by a vibe's recipe (resolves to format/theme/category constraints)

**Onboarding wiring** — render `GET /vibes/` as the picker grid, gate "Continue" until ≥3 selected, send `PUT /users/me/vibes/` on submit. `GET /users/me/vibes/` returns whatever was saved last so the picker can pre-select on resume.

### Auth & users (15 endpoints)
- `POST   /auth/registration/`, `POST /auth/login/`, `POST /auth/logout/`, `POST /auth/google/`
- `GET    /auth/user/`, `PATCH /auth/user/`, `PUT /auth/user/`
- `POST   /auth/token/refresh/`, `POST /auth/token/verify/`
- `POST   /auth/password/change/`, `POST /auth/password/reset/`, `POST /auth/password/reset/confirm/`
- `POST   /auth/registration/verify-email/`, `POST /auth/registration/resend-email/`

### Jokes — browse (8)
- `GET    /jokes/` (paginated, filterable), `GET /jokes/{id}/`
- `GET    /jokes/random/`, `GET /jokes/trending/`
- `POST   /jokes/{id}/rate/`, `POST /jokes/{id}/share/`, `GET /jokes/{id}/my-rating/`
- Lookup tables (read-only): `GET /formats/`, `/age-ratings/`, `/tones/`, `/context-tags/`, `/culture-tags/`, `/languages/`

### Joke submission & drafts (5)
- `POST   /jokes/submit/`
- `GET    /jokes/my-drafts/`, `GET /jokes/my-drafts/{id}/`
- `PATCH  /jokes/my-drafts/{id}/`, `PUT /jokes/my-drafts/{id}/`, `DELETE /jokes/my-drafts/{id}/`
- `POST   /jokes/my-drafts/{id}/submit/`

### Daily joke (2)
- `GET    /daily-jokes/today/`
- `GET    /daily-jokes/history/`

### Collections (5)
- `GET    /collections/`, `POST /collections/`, `GET /collections/trending/`
- `GET    /collections/{id}/`, `PATCH /collections/{id}/`, `PUT /collections/{id}/`, `DELETE /collections/{id}/`
- `GET    /collections/{id}/jokes/`

### Saved jokes & favorites (6)
- `GET    /saved-jokes/`, `POST /saved-jokes/`, `DELETE /saved-jokes/{id}/`, `GET /saved-jokes/search/`
- `GET    /favorites/`, `POST /favorites/`, `DELETE /favorites/{id}/`, `GET /favorites/stats/`

### Trending & discovery (5)
- `GET    /jokes/trending/`, `GET /collections/trending/`
- `GET    /tags/trending/`, `GET /tags/rising/`
- `GET    /themes/popular/`, `GET /users/top-jokesters/`

### User profile & preferences (8)
- `GET    /users/me/profile/`, `PATCH /users/me/profile/`
- `GET    /users/me/activity/`, `GET /users/me/achievements/`
- `GET    /users/me/preferences/`, `PATCH /users/me/preferences/`, `PUT /users/me/preferences/`
- `GET    /preferences/me/`, `PATCH /preferences/me/`, `POST /preferences/complete-onboarding/`

### Compliance & account (3)
- `POST   /reports/` (content reports)
- `POST   /users/{user_id}/block/`, `DELETE /users/{user_id}/block/`
- `DELETE /users/me/` (account deletion)
- `GET    /users/me/data-export/` (GDPR export)

### Pagination & throttling
- All list endpoints return `{ count, next, previous, results }` (DRF pagination, page size 10).
- Throttling: `100/hour` for anonymous, `1000/hour` for authenticated. Exceeding → `429 Too Many Requests`.
- API versioning via URL path: `/api/v1/...`. Future versions will be `/api/v2/`.

---

## 7. Frontend env-var contract

| Var | Production value | Local-dev value |
|---|---|---|
| `VITE_API_URL` | `https://jokesforbackend-332865216810.us-east1.run.app/api/v1` | `http://localhost:8000/api/v1` |
| `VITE_USE_MOCKS` | `false` | `true` (if mocking) |
| `VITE_FIREBASE_*` (7 keys) | from Firebase project `jokesforfront` | same |

The `VITE_API_URL` already lives in the GitHub Actions deploy workflow as a fallback. Override per-environment via repo Variables / `.env.local`.

---

## 8. Common errors → fixes

| Symptom | Root cause | Fix |
|---|---|---|
| `Network Error` / `CORS error` in console; request never reaches the server | Origin not in `CORS_ALLOWED_ORIGINS` | Use one of the three whitelisted origins, or add yours to backend env var (gcloud command in §11) |
| Request succeeds but cookies aren't stored | `credentials: 'include'` (or `withCredentials: true`) missing | Add it to fetch / axios call |
| `401 Authentication credentials were not provided` on every request | Cookies not being sent | Verify `credentials: 'include'`, check DevTools → Application → Cookies that `jokes-access-token` is present and not expired |
| OAuth: Google rejects with `redirect_uri_mismatch` | The `redirect_uri` you sent to Google isn't in the OAuth client's Authorized Redirect URIs **OR** doesn't match the backend's `GOOGLE_OAUTH_CALLBACK_URL` | Verify both. See §5.3 OAuth client constraints |
| `400 DisallowedHost: Invalid HTTP_HOST header` | You're hitting the backend with a Host header it doesn't allow | Use the canonical `jokesforbackend-….run.app` URL or one of the explicitly allowed hosts (`jokesfor.net`, `www.jokesfor.net`) |
| `400 CSRF verification failed` on POST | Origin not in `CSRF_TRUSTED_ORIGINS` | Same fix as CORS — backend's CSRF allowlist matches CORS |
| Refresh token call returns `401`/`400` after browser restart | Refresh cookie expired (24 h) | User must log in again — handle in the axios interceptor (§5.5) |

---

## 9. Pre-demo checklist

- [ ] Frontend deployed to one of the whitelisted origins (`jokesforfront.web.app` recommended for demo)
- [ ] `VITE_API_URL` points at `https://jokesforbackend-332865216810.us-east1.run.app/api/v1`
- [ ] axios/fetch wrapper sets `withCredentials: true` / `credentials: 'include'` globally
- [ ] OAuth: client has `https://jokesforfront.web.app/auth/google/callback` in **Authorized Redirect URIs** in GCP Console
- [ ] OAuth: client has `https://jokesforfront.web.app` in **Authorized JavaScript Origins**
- [ ] Open Incognito → load frontend → register / login → DevTools → Application → Cookies shows `jokes-access-token` and `jokes-refresh-token` with `SameSite=None`, `Secure`, `HttpOnly`
- [ ] Refresh page after login — still authenticated (cookies persist)
- [ ] Sign out — cookies cleared

---

## 10. Verification probe (run anytime)

```bash
URL="https://jokesforbackend-332865216810.us-east1.run.app"

# 1. Service is alive
curl -s -o /dev/null -w "%{http_code}\n" $URL/api/schema/        # → 200
curl -s -o /dev/null -w "%{http_code}\n" $URL/api/v1/auth/user/  # → 401 (auth required)

# 2. CORS preflight from the demo origin
curl -i -X OPTIONS $URL/api/v1/auth/login/ \
  -H "Origin: https://jokesforfront.web.app" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type" 2>/dev/null | grep -i access-control
# Expect: Access-Control-Allow-Origin echoes the origin, Allow-Credentials: true

# 3. Cookie shape on registration response
curl -i -X POST $URL/api/v1/auth/registration/ \
  -H "Content-Type: application/json" \
  -H "Origin: https://jokesforfront.web.app" \
  -d '{"email":"smoke-'$(date +%s)'@example.com","password1":"SuperSecret123!xyz","password2":"SuperSecret123!xyz"}' \
  2>/dev/null | grep -i "set-cookie: jokes-"
# Expect: jokes-access-token=...; HttpOnly; SameSite=None; Secure
#         jokes-refresh-token=...; HttpOnly; SameSite=None; Secure
```

---

## 11. Backend env vars (current state on Cloud Run)

For ops reference. The frontend doesn't need to do anything here, but if a CORS / cookie issue surfaces and the backend team isn't on, a frontend dev can fix it themselves with these.

```bash
GCLOUD=~/Downloads/google-cloud-sdk/bin/gcloud
SERVICE=jokesforbackend
REGION=us-east1
PROJECT=jokesfor

# Inspect everything
$GCLOUD run services describe $SERVICE --region=$REGION --project=$PROJECT \
  --format="value(spec.template.spec.containers[0].env)" | tr ';' '\n'

# Add a new origin to CORS + CSRF allowlists (atomic; replaces existing list).
# Use the ^|^ syntax because gcloud uses comma as the env-var separator
# but our values contain commas.
$GCLOUD run services update $SERVICE --region=$REGION --project=$PROJECT \
  --update-env-vars="^|^CORS_ALLOWED_ORIGINS=https://jokesforfront.web.app,https://jokesforfront.firebaseapp.com,https://jokesfor.net,https://NEW.example.com|CSRF_TRUSTED_ORIGINS=https://jokesforfront.web.app,https://jokesforfront.firebaseapp.com,https://jokesfor.net,https://NEW.example.com"

# Switch the OAuth canonical origin (e.g. when going from web.app → jokesfor.net)
$GCLOUD run services update $SERVICE --region=$REGION --project=$PROJECT \
  --update-env-vars=GOOGLE_OAUTH_CALLBACK_URL=https://jokesfor.net/auth/google/callback,SITE_DOMAIN=jokesfor.net

# Tail logs
$GCLOUD run services logs tail $SERVICE --region=$REGION --project=$PROJECT
```

Current env state (revision `jokesforbackend-00010-7pw`, verified 2026-05-09):

```
DEBUG=False
ALLOWED_HOSTS=.run.app,jokesfor.net,www.jokesfor.net
CORS_ALLOWED_ORIGINS=https://jokesfor.net,https://jokesforfront.web.app,https://jokesforfront.firebaseapp.com
CSRF_TRUSTED_ORIGINS=https://jokesfor.net,https://jokesforfront.web.app,https://jokesforfront.firebaseapp.com
JWT_COOKIE_SAMESITE=None
GOOGLE_CLIENT_ID=332865216810-7kouajjg51jiceqk4g2h0qa3t3nbk4ga.apps.googleusercontent.com
GOOGLE_OAUTH_CALLBACK_URL=https://jokesforfront.web.app/auth/google/callback
SITE_DOMAIN=jokesforfront.web.app
SITE_NAME=JokesFor

# Mounted from Secret Manager (not visible to roles/run.viewer)
SECRET_KEY            ← secret django-secret-key:latest
DATABASE_URL          ← secret database-url:latest
GOOGLE_CLIENT_SECRET  ← secret google-client-secret:latest
```

---

## 12. Future work (non-blocking)

- **Same-origin via Firebase rewrites** — abandoned for the demo because Firebase Hosting can't proxy across GCP projects (frontend in `jokesforfront`, backend in `jokesfor`). Migration plan in the frontend repo's hosting doc, §9. Once executed, this entire CORS dance goes away — `withCredentials: false` would even work, and `SameSite=Lax` becomes the safer default.
- **Real email backend** — replace Django's `console` email with SendGrid/Mailgun for password reset links.
- **Async tasks** — the `generate_daily_jokes` Celery task isn't running anywhere. To re-enable, plan is Cloud Scheduler → Cloud Run handler endpoint (no Celery worker, no Redis, $0).
- **Custom domain on the API** (`api.jokesfor.net`) via Cloud Run domain mapping — would simplify the OAuth callback story but doesn't enable same-origin (still cross-site with `app.jokesfor.net`).

---

## 13. Design components → API call wiring

> Every component in `parts/flow-screens.jsx` mapped to its endpoint(s). Use this as the build sheet: for each screen, the components are listed in render order with the exact call needed and the data path from response → UI.
>
> **All requests are authenticated** unless explicitly marked "(public)". `credentials: 'include'` everywhere.
>
> Notation: `→ METHOD /path` for the call, `· data:` for what to read from the response, `· side-effect:` for what implicitly happens server-side.

### 13.1 Universal — JokeCard component (used on Today, Explore, Search, Library, Joke Detail)

The card is **format-aware**: rendering branches on `joke.format.slug` ∈ {`oneliner`, `setup`, `knock`, `story`, `anti`, `observ`}. The same card is used everywhere; only the data source upstream differs.

| Component | Call | Data path |
|---|---|---|
| Card hydration | data passed in (no call) | parent provides `joke` object |
| Setup → Punchline reveal (tap to unblur) | no call | local state; punchline is in `joke.punchline` from the start |
| Knock-knock advance (tap to next bubble) | no call | `joke.lines[]` (P10) |
| Format badge | no call | `joke.format.slug` → label map |
| Theme/Category eyebrow | no call | `joke.themes[].name` and `joke.categories[].name` (or legacy `context_tags` / `tones`) |
| Save button (toggle) | `→ POST /api/v1/saved-jokes/` body `{ joke: <id> }` to save • `→ DELETE /api/v1/saved-jokes/{id}/` to unsave | optimistic UI; on success, store the saved-joke id locally to support unsave |
| Share button | `→ POST /api/v1/jokes/{id}/share/` body `{ platform: 'copy' \| 'twitter' \| 'whatsapp' \| ... }` | logs ShareEvent; copy-to-clipboard happens in the browser independently |
| Reaction emoji (😂🤣🤔🙄) | `→ POST /api/v1/jokes/{id}/react/` body `{ reaction: 'lol' \| 'crying' \| 'hmm' \| 'eyeroll' }` | toggles off if same; switches if different. response: `{ my_reaction, counts }` |
| Stat row (😂 612 · 💾 4.1K) | `→ GET /api/v1/jokes/{id}/reactions/` (or use counts already in joke detail) | `counts.lol`, `counts.crying`, etc.; saves count from a separate aggregate or `joke.saves_count` if added |
| Side-effect on retrieve | `→ GET /api/v1/jokes/{id}/?source=daily` | passing `?source=` so the JokeView log records the surface (powers streak + insights) |

**Source values to pass on `?source=`** when retrieving a joke from each surface:
- Today's JOTD card → `?source=daily`
- Today's "Three you'll save" 3-up → `?source=daily`
- Today's mid-sip pack continuation → `?source=pack`
- Explore results → `?source=explore`
- Search results → `?source=search`
- Mystery box modal → `?source=mystery`
- Saved/library → `?source=saved`
- Public share landing page → `?source=share`

### 13.2 Screen — Login (`LoginScreen`)

| Component | Call |
|---|---|
| Brand canvas (left, "Find the right joke. For any moment.") | static |
| Sample joke card (Setup/Punchline shown unblurred) | no call — static demo content. Optionally `→ GET /api/v1/jokes/random/` (public) for live demo of corpus |
| "Continue with Google" button | frontend-driven OAuth flow, then `→ POST /api/v1/auth/google/` body `{ code: <code from Google> }` — see §5.3 |
| Email input | local |
| Password input | local |
| "Forgot" link | navigate to `/forgot-password` page, which on submit `→ POST /api/v1/auth/password/reset/` body `{ email }` |
| "Sign in" submit | `→ POST /api/v1/auth/login/` body `{ email, password }`. On 200 the cookies are already set by the browser. Redirect to `/today`. |
| "Create an account →" | navigate to `/register` |
| 14-day streak banner ("Keep your 14-day streak alive") | static aspirational copy on this screen — render unconditionally |
| Stats footer (312K daily readers, 10K+ jokes) | static for now |

### 13.3 Screen — Register (`RegisterScreen`) — two steps

**Step 1 (account basics):**

| Component | Call |
|---|---|
| First name input | local; saved with PATCH after submit |
| Display handle input | local; saved via UserProfile (see below) |
| Email input | required for submit |
| Password input + strength meter | client-side strength only |
| "Continue" button (advance to step 2) | no API yet — gather data, hold locally |

**Step 2 (preferences) + final submit:**

| Component | Call |
|---|---|
| Pronoun pills (he/him, she/her, they/them) | held locally; PATCHed in onboarding-completion call |
| "Where will you tell these jokes most?" tile picker (Office/Friends/Group/Stage) | held locally; saved in UserProfile via `→ PATCH /api/v1/users/me/profile/` body `{ display_context: 'office' \| 'friends' \| 'group_chat' \| 'stage' }` (NOTE: this field doesn't exist in the model yet — defer or treat as a frontend-only preference for the demo) |
| "Send me the daily joke at 9 AM" toggle | passed into the registration payload as `notification_enabled: true, notification_time: '09:00'` (PATCHed after step 3) |
| **"Create account & start setup"** | sequence:<br>1. `→ POST /api/v1/auth/registration/` body `{ email, password1, password2 }` — cookies set, user authenticated<br>2. `→ PATCH /api/v1/auth/user/` body `{ first_name }` to save display name<br>3. `→ PATCH /api/v1/users/me/profile/` body `{ handle: '@alexq' }` to save handle<br>4. Navigate to `/onboarding/vibes` (step 3 of registration is the vibe picker) |

### 13.4 Screen — Onboarding · Vibes (`OnbVibesScreen`)

| Component | Call |
|---|---|
| Page render | `→ GET /api/v1/vibes/` — returns the 12 catalog entries with `slug, label, subtitle, icon, swatch_bg, swatch_fg, order`. Render as the picker grid in `order` |
| Tile click (toggle) | local state only |
| "X picked" pill | local count |
| Skip link | `→ navigate /today` (no save) |
| **"Continue"** | `→ PUT /api/v1/users/me/vibes/` body `{ slugs: ["office","puns","observ", ...] }` — **min 3, max 12**. On 400, surface the error. On 200, navigate to `/onboarding/formats` |
| Resume case (user returns to picker) | `→ GET /api/v1/users/me/vibes/` — pre-select the user's existing picks before they start toggling |

### 13.5 Screen — Onboarding · Formats (`OnbFormatsScreen`)

| Component | Call |
|---|---|
| Page render | `→ GET /api/v1/formats/` — returns the 6 format entries with `slug, name, description`. The design's `FORMATS` array (parts/flow.jsx 41-48) provides the demo strings; map by slug |
| Tile click (toggle) | local state only |
| "Continue" | **No backend persistence today** — `UserPreference` doesn't have `preferred_formats`. Two options:<br>(a) hold the selection locally and use it client-side as a `?joke_format=X` filter on subsequent feeds<br>(b) defer to a future backend addition<br>For the demo, (a) is sufficient |

### 13.6 Screen — Onboarding · Ritual (`OnbRitualScreen`)

| Component | Call |
|---|---|
| Time slot picker (07/08/09/12/17/21) | local state |
| Day-of-week tiles (M/T/W/T/F/S/S) | local state |
| Streak-saver toggle | local state |
| Notification preview card | static |
| Streak forecast "14 days" card | static aspirational copy |
| **"Done — show me today's joke"** | `→ PATCH /api/v1/preferences/me/` body `{ notification_enabled: true, notification_time: "09:00", notification_days: ["mon","tue","wed","thu","fri"], streak_saver_enabled: true, onboarding_completed: true }`. On 200, navigate to `/today` |

### 13.7 Screen — Today (`TodayScreen`) — the busiest screen

**Header bar (`TopShell`):**

| Component | Call |
|---|---|
| Logo / brand | static |
| Nav (Today/Explore/Search/Library) | router |
| Streak chip "14-day streak" | `→ GET /api/v1/users/me/streak/` (one call shared with the streak rail below) — read `current_count` |
| Bell icon w/ dot | placeholder; no notifications endpoint yet |
| Avatar | from `→ GET /api/v1/auth/user/` (already loaded by auth shell) |

**Hero strip (greeting):**

| Component | Call |
|---|---|
| "Wednesday · Feb 12 · Vol. I · No. 042" eyebrow | `→ GET /api/v1/daily-jokes/today/` → read `issue_label` |
| "Good morning, Alex" | `→ GET /api/v1/auth/user/` → `first_name` |
| "One joke today. Two if you finish yesterday's saved set." | static copy |
| "Yesterday" button | `→ GET /api/v1/daily-jokes/history/?limit=1` — show yesterday's daily |
| "Mystery box · 3 LEFT" pill button | `→ GET /api/v1/mystery-box/status/` → read `rolls_remaining_today` |

**JOTD hero card:**

| Component | Call |
|---|---|
| Card payload | `→ GET /api/v1/daily-jokes/today/` → returns `{ id, joke, date, issue_label, delivered_at }` (single shared call with the eyebrow) |
| Setup line | `joke.setup` |
| Punchline blur/reveal (tap) | `joke.punchline` (already in payload; just reveal locally) |
| Save button | `→ POST /api/v1/saved-jokes/` body `{ joke: joke.id }` |
| Share button | `→ POST /api/v1/jokes/{joke.id}/share/` body `{ platform: 'copy' \| ... }` |
| Stat row (😂 612 · 💾 4.1K · 🔁 312) | already in joke payload via reactions endpoint, OR `→ GET /api/v1/jokes/{joke.id}/reactions/` |

**Right rail (3 stacked tiles):**

| Component | Call |
|---|---|
| Streak rail "14 days" + 14-cell grid | `→ GET /api/v1/users/me/streak/` (same call as header chip — cache & share). Render `last_14_days[]` (each `{date, status}`) into the grid |
| Mystery box card "Roll for a random joke" | display from `→ GET /api/v1/mystery-box/status/` (same as header pill); Roll button → `→ POST /api/v1/mystery-box/roll/` with no body. On 200 open a modal showing `joke`; on 429 show "limit reached" toast |
| Tomorrow teaser (blurred) | `→ GET /api/v1/daily-jokes/tomorrow/` → render `preview` (truncated to 12 words by backend) blurred + `format` label below |

**Continue mid-sip strip ("You stopped mid-sip · Yesterday"):**

| Component | Call |
|---|---|
| Strip render condition | `→ GET /api/v1/users/me/packs/in-progress/` — render only if list non-empty; show first pack |
| "2/4" badge | `pack.user_progress.last_read_entry / pack.joke_count` |
| "Continue" button | navigate to `/packs/{slug}` resume view |

**"Three you'll probably save" 3-up grid:**

| Component | Call |
|---|---|
| Section render | `→ GET /api/v1/jokes/?vibe={user_top_vibe}&page_size=3&ordering=-created_at` — pick `user_top_vibe` from `taste_profile.top_vibe.slug` or first of `users/me/vibes/`; fall back to `→ GET /api/v1/jokes/trending/?limit=3` if user has no vibes |
| Each card | renders via the JokeCard component (§13.1); `?source=daily` param when user clicks through |
| "See more in Explore →" | navigate to `/explore` |

**7-day archive newspaper strip ("The Week in Punchlines"):**

| Component | Call |
|---|---|
| 7 columns | `→ GET /api/v1/daily-jokes/history/?limit=7` — returns last 7 daily jokes with `joke`, `date`, `issue_label` (if exposed; otherwise compute client-side from `date`) |
| Each column: "WED · No. 041 · 'On scientists trusting atoms.'" | column eyebrow uses date + issue_label; italic line uses `joke.text` truncated to ~50 chars; bottom label uses `joke.format.name` or `joke.categories[0].name` |

**Mixed-format showcase ("Same library. Different rhythm."):**

| Component | Call |
|---|---|
| Section render | parallel calls, one per format card slot. Each: `→ GET /api/v1/jokes/?joke_format={fmt}&ordering=-created_at&page_size=1` for `fmt` ∈ `oneliner`, `knock`, `anti` |
| Cards | render each via JokeCard |

**Top jokesters card:**

| Component | Call |
|---|---|
| Section payload | `→ GET /api/v1/users/top-jokesters/?limit=5&period=week` — returns `{ results: [{ id, name, username, punchline_count, rank, top_vibes: [{slug, label, icon}] }, ...] }` |
| Per-row render | name + handle + punchline count + first 2 `top_vibes` as pill labels |

**Weekly Special wide tile:**

| Component | Call |
|---|---|
| Tile payload | `→ GET /api/v1/packs/featured/` → `{ slug, title, subtitle, description, cover_color, jokes: [{order, joke}] }` |
| Title / subtitle / cover_color | direct |
| Preview list of 5 joke snippets | from `jokes[0..5]` truncated to short quotes |
| "Read collection →" button | navigate to `/packs/{slug}` |
| "Save list" button | not currently mapped to a single endpoint; either save each joke individually via `→ POST /api/v1/saved-jokes/` per `pack.jokes[].joke.id`, or skip for the demo |

**"How you've been laughing" stats card (dark variant):**

| Component | Call |
|---|---|
| Whole card payload | `→ GET /api/v1/users/me/taste-profile/?period=month` → `{ jokes_read, jokes_saved, peak_read_hour, top_vibe, top_themes, top_categories, top_formats, daily_reads_28d }` |
| 168 JOKES READ | `jokes_read` |
| 42 SAVED | `jokes_saved` |
| 9 AM PEAK READ | `peak_read_hour` (display as "9 AM" / "10 PM" by formatting) |
| Pun TOP VIBE | `top_vibe.label` |
| 28-day sparkline | `daily_reads_28d` (array of 28 ints) |

**"Themes you laugh at most" pill cloud:**

| Component | Call |
|---|---|
| Pills | from same `taste-profile` call: `top_themes` + `top_categories` + `top_formats` (concatenate or interleave). Each is `{ label, count }` — render with the count as a small mono badge |

**"Test it on a friend" share card:**

| Component | Call |
|---|---|
| Pre-populated message | `joke.text` from today's daily |
| "Share today's joke" button | `→ POST /api/v1/jokes/{today_joke.id}/share/` body `{ platform: <selected> }`. The "did they laugh / lied" reaction tracking isn't implemented today — frontend-only state for now |

**Pull quote / brand footer:**

| Component | Call |
|---|---|
| Quote + countdown to tomorrow 9 AM | static + client-side timer (compute `tomorrow_at_9am - now`) |

### 13.8 Screen — Explore (`ExploreScreen`)

| Component | Call |
|---|---|
| Hero ("10,432 jokes") count | `→ GET /api/v1/jokes/?page_size=1` — read `count` from paginated envelope |
| "Or describe the moment" CTA tile | navigates to `/search` |
| **Format chip rail** | `→ GET /api/v1/formats/` — render the 6 chips |
| **Theme chip rail** | `→ GET /api/v1/context-tags/` — render all 13 themes |
| **Category chip rail** | `→ GET /api/v1/tones/` — render all 9 categories |
| Active-filter bar (pills + Clear all) | client state |
| Quick prompts ("This week", "Top saves", "Trending", "New") | each maps to a preset:<br>· This week → `?ordering=-created_at`<br>· Top saves → `?ordering=popularity`<br>· Trending → `→ GET /api/v1/jokes/trending/?period=week`<br>· New → `?ordering=-created_at` |
| **Results masonry** | `→ GET /api/v1/jokes/?joke_format={f}&context_tags={t1},{t2}&tones={c1},{c2}&page=N&page_size=18` — composes whatever filters are active. Use comma-separated lists for M2M filters. |
| Inline editorial tile (curator note) | static / hard-coded for now; could later be `/editor-notes/` |
| Inline weekly-special tile | `→ GET /api/v1/packs/featured/` (cached from Today screen if user came from there) |
| Empty-state "Surprise me" | `→ POST /api/v1/mystery-box/roll/` (with auth) |

### 13.9 Screen — Search (`SearchScreen`) — the Sentence Builder

| Component | Call |
|---|---|
| Format pill dropdown | `→ GET /api/v1/formats/` (cached from Explore) |
| Theme pill dropdown | `→ GET /api/v1/context-tags/` |
| Category pill dropdown | `→ GET /api/v1/tones/` |
| Keyword refine input | added as `&q=<keyword>` to results call |
| **Results call** | `→ GET /api/v1/jokes/?q={kw}&joke_format={f}&context_tags={ts}&tones={cs}&page_size=18&ordering=relevance` — relevance ordering is server-default when `q` is present. Use comma-separated for M2M lists. |
| Quick-prompt chips ("First day at work", "Wedding toast", etc.) | each chip writes preset values into the format/theme/category pills + clears `q` + re-runs results call |
| "X matches" count | from paginated `count` |
| Empty-state "Loosen filters" | drops format + cats from state and re-queries |
| Empty-state "Surprise me" | `→ POST /api/v1/mystery-box/roll/` |

### 13.10 Screen — Library (referenced by nav; not in flow-screens.jsx but frontend will build)

| Component | Call |
|---|---|
| Saved jokes list | `→ GET /api/v1/saved-jokes/?page=N` |
| Search within saved | `→ GET /api/v1/saved-jokes/search/?q=<kw>` |
| Collections list | `→ GET /api/v1/collections/` |
| Collection detail | `→ GET /api/v1/collections/{id}/` and `→ GET /api/v1/collections/{id}/jokes/` |
| Create collection | `→ POST /api/v1/collections/` body `{ name, description?, is_public? }` |
| Move saved joke into collection | `→ PATCH /api/v1/saved-jokes/{id}/` body `{ collection: <collection_id> }` (if endpoint supports; otherwise delete+recreate) |
| Favorites list | `→ GET /api/v1/favorites/` |
| Favorite stats | `→ GET /api/v1/favorites/stats/` |
| Heart joke from list | `→ POST /api/v1/favorites/` body `{ joke }` |
| Trending collections | `→ GET /api/v1/collections/trending/` |

### 13.11 Screen — Joke Detail (`screens-4.jsx`)

| Component | Call |
|---|---|
| Detail page render | `→ GET /api/v1/jokes/{id}/?source=<surface>` — automatically logs a JokeView (debounced 60s) and powers the "Streak saved +1" rail below |
| Pills row (Puns / Work-friendly / 5/5 cleanliness) | from `joke.themes`, `joke.categories`, and `joke.age_rating` |
| Setup / Punchline display | `joke.setup` / `joke.punchline` |
| Save to "Work Icebreakers" button | `→ POST /api/v1/saved-jokes/` body `{ joke: joke.id, collection: <collection_id> }` (or just `{ joke }` to save into default Favorites) |
| Share button | `→ POST /api/v1/jokes/{joke.id}/share/` |
| Copy button | clipboard API; optionally also `→ POST /api/v1/jokes/{joke.id}/share/` body `{ platform: 'copy' }` for analytics |
| Reaction emoji row (😂🤣🤔🙄) | `→ POST /api/v1/jokes/{joke.id}/react/` body `{ reaction: <slug> }` — toggle/switch logic on backend |
| **"How the internet laughed" 4-card breakdown (😂 412 · 🤣 188 · 🤔 38 · 🙄 12)** | `→ GET /api/v1/jokes/{joke.id}/reactions/` → `{ counts, my_reaction }`. Render `counts.lol` etc. |
| **"Why you got this one" panel** | `→ GET /api/v1/users/me/taste-profile/` to derive: "Picked because you saved {top_themes[0].count} {top_themes[0].label}, opened JokesFor on... {top_vibe.label} is your top vibe." Construct copy on frontend. The "tune your feed" link → `/onboarding/vibes` |
| **"Streak saved +1 — that's 14"** rail | `→ GET /api/v1/users/me/streak/` — display `current_count`. Side-effect: viewing this page already logged a JokeView, which incremented the streak server-side. If frontend wants to react to "did the streak just tick?", compare current_count before vs after the page render |
| "Tomorrow's joke unlocks at 9 AM" line | static + client-side timer |
| **"More like this" list** | `→ GET /api/v1/jokes/?vibe={user_top_vibe}&exclude={joke.id}&limit=3` — *exclude param doesn't exist on the backend*. Workaround for the demo: `→ GET /api/v1/jokes/?vibe={user_top_vibe}&page_size=4` and drop the current joke client-side |
| "Roll a mystery joke?" CTA | `→ POST /api/v1/mystery-box/roll/` |

### 13.12 Modal — Mystery Box result

When the user taps "Roll" on Today (or "Surprise me" elsewhere), the response is a single joke:

| Field on response | Use |
|---|---|
| `joke` | render full JokeCard |
| `rolls_remaining_today` | update the "X LEFT" pill |
| `source_vibe` (optional) | small "Pulled from your Office vibe" hint at the bottom of the modal — rendered only if non-null |

On 429 (cap reached), show a friendly toast: "Out of rolls for today — check back tomorrow at midnight UTC."

### 13.13 Cross-screen polling & cache hints

To keep the frontend fast and the backend bill at $0:

- Cache `/vibes/`, `/formats/`, `/context-tags/`, `/tones/` for the session — they're effectively static (12 / 6 / 13 / 9 rows).
- Cache `/users/me/profile/` and `/users/me/vibes/` for the session; invalidate after PATCH/PUT.
- Re-fetch `/users/me/streak/` only when the user opens the Today screen, plus once after viewing a joke (the viewing causes a server-side streak tick; refresh to show the new count).
- `/users/me/today-status/` should be re-fetched on tab focus or every ~5 min while the Today screen is mounted — it's how the "Today's joke is ready" hero appears at 9 AM.
- `/mystery-box/status/` only needs refresh when the user opens the Mystery Box card or after a roll.
- `/users/me/taste-profile/` is computed on demand — don't poll; fetch once per visit to Today.
- `/daily-jokes/today/` is **idempotent for the day**; cache for 24h. `/daily-jokes/tomorrow/` lazy-creates the row on first call — cache it once and don't re-fetch.

### 13.14 Endpoints with no current frontend wiring (open hooks)

These backend endpoints exist but no design component currently uses them — leaving them in the catalog so the frontend can adopt as needed:

- `GET /api/v1/jokes/random/` — public; for the login-screen sample joke if you want it live
- `GET /api/v1/themes/popular/`, `/tags/trending/`, `/tags/rising/` — alternative pill-cloud sources for Explore
- `GET /api/v1/users/me/activity/` — denser activity stream
- `GET /api/v1/users/me/achievements/` — awarded badges, no surface in current design
- `POST /api/v1/reports/`, `POST /api/v1/users/{id}/block/`, `DELETE /api/v1/users/me/`, `GET /api/v1/users/me/data-export/` — compliance flows; will live in a Settings screen the design hasn't drawn yet
