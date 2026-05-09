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

## 6. Endpoint catalog (live count: 80)

For request/response shapes per endpoint, see [`API_Specification_For_Frontend.md`](./API_Specification_For_Frontend.md). Quick tour:

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
