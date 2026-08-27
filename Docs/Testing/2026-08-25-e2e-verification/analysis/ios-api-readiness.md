# iOS API Readiness — JokesFor backend as seen by a future native Swift/SwiftUI client

Analyzer key: `ios-api-readiness`
Date: 2026-08-25
Backend repo: `/Users/narekmeloyan/PycharmProjects/JokesForProject` (Django 5.2.17, DRF 3.16.1, dj-rest-auth 7.0.2, simplejwt 5.5.1, allauth 65.14.3, drf-spectacular 0.29.0)
Frontend repo (for contrast only): `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend`
Prod backend: `https://jokesforbackend-332865216810.us-east1.run.app` (schema fetched read-only; 110 paths / 130 operations / 79 component schemas)

All statements below are from code unless marked "(prod probe)" (a read-only `curl` against prod) or "(doc)".

---

## 0. Executive summary

The API is *mostly* usable from a non-browser client because DRF authenticates on `Authorization: Bearer <JWT>` first and only falls back to the cookie. **But the token lifecycle is browser-shaped**: with `JWT_AUTH_HTTPONLY=True` the login/social-login/verify-email responses never put the **refresh** token in the JSON body (only in an httpOnly cookie), and the refresh endpoint deletes the rotated refresh token from the body too. A native app that does not persist cookies therefore gets a 15-minute access token and no way to renew it; a native app that *does* keep the `URLSession` cookie jar works but then hits the CSRF double-submit rule on the cookie path. Google Sign-In on iOS would need an `id_token`/`access_token` path plus a second allauth `SocialApp` (which today would raise `MultipleObjectsReturned`), and **Sign in with Apple does not exist** anywhere in the backend (no provider installed, no adapter, no view). There is no device-token / push model at all. Stripe Checkout URLs are hard-wired to web routes. The OpenAPI schema is decent for Swift codegen (unique operationIds, `jwtHeaderAuth` bearer scheme declared) but 49 of 130 operations have "No response body" typed responses and several core responses are inline/untyped objects.

The prioritized change list is in section 12.

---

## 1. Authentication for non-browser clients

### 1.1 What DRF accepts

`JokesForProject/settings.py:297-301`:
```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'dj_rest_auth.jwt_auth.JWTCookieAuthentication',
    ],
```
`dj_rest_auth/jwt_auth.py:135-158` (`JWTCookieAuthentication.authenticate`): reads `self.get_header(request)` FIRST; only if the `Authorization` header is absent does it look at the `jokes-access-token` cookie. `SIMPLE_JWT['AUTH_HEADER_TYPES'] = ('Bearer',)` (`settings.py:468`). So **`Authorization: Bearer <access>` is accepted on every DRF endpoint** and takes precedence over cookies. Confirmed by the frontend itself, which sends Bearer on every request (`src/lib/axios.ts` request interceptor).

Caveat: no backend test exercises the Bearer header path directly (the only `Bearer` strings in tests are in `JokesForProject/tests/test_observability.py:77,305`, which test log scrubbing). All 21 test modules that authenticate use `force_authenticate`/`force_login`. The header path is library behaviour, not project-tested.

### 1.2 dj-rest-auth JWT settings (`settings.py:424-455`)

| Setting | Value | Effect on a native client |
|---|---|---|
| `USE_JWT` | `True` | JWT, not DRF TokenAuth |
| `JWT_AUTH_COOKIE` | `'jokes-access-token'` | access token also set as cookie |
| `JWT_AUTH_REFRESH_COOKIE` | `'jokes-refresh-token'` | refresh token set as cookie |
| `JWT_AUTH_HTTPONLY` | `True` | **refresh token is stripped from JSON bodies** (see 1.3) |
| `JWT_AUTH_RETURN_EXPIRATION` | not set → default `False` (`dj_rest_auth/app_settings.py:39`) | no `access_expiration`/`refresh_expiration` in login body; client must decode the JWT `exp` claim or assume 15 min |
| `JWT_AUTH_COOKIE_USE_CSRF` | `True` | CSRF enforced only on the cookie-auth path |
| `JWT_AUTH_SECURE` | `not DEBUG` | Secure cookies in prod |
| `JWT_AUTH_SAMESITE` | env `JWT_COOKIE_SAMESITE` (prod = `None`; prod probe shows `SameSite=None; Secure`) | irrelevant to URLSession, but see 11 |
| `SESSION_LOGIN` | `False` | no Django session |

`SIMPLE_JWT` (`settings.py:460-469`): `ACCESS_TOKEN_LIFETIME=15min`, `REFRESH_TOKEN_LIFETIME=1 day`, `ROTATE_REFRESH_TOKENS=True`, `BLACKLIST_AFTER_ROTATION=True`, HS256 signed with `SECRET_KEY`.

### 1.3 What login responses actually contain

`dj_rest_auth/views.py:77-120` (`LoginView.get_response`):
```python
data = {'user': self.user, 'access': self.access_token}
if not auth_httponly:
    data['refresh'] = self.refresh_token
else:
    data['refresh'] = ""          # <-- JWT_AUTH_HTTPONLY=True → empty string
...
set_jwt_cookies(response, self.access_token, self.refresh_token)
```
So `POST /api/v1/auth/login/` (body `{"email","password"}`; `LoginSerializer` at `dj_rest_auth/serializers.py:21-24` accepts `username`/`email`/`password`) returns **`{"access": "<jwt>", "refresh": "", "user": {...}}`** plus two `Set-Cookie` headers. The OpenAPI `JWT` component declares `refresh` as a required string, which is technically true (it is `""`) but misleading for codegen.

Same code path for `POST /api/v1/auth/google/` (`GoogleLogin(SocialLoginView)`, `jokes/views.py:893-931`; `SocialLoginView` subclasses `LoginView`, `dj_rest_auth/registration/views.py:145`). The docstring at `jokes/views.py:913-918` claims the response includes `"refresh": "jwt_refresh_token"` — **the docstring is wrong given `JWT_AUTH_HTTPONLY=True`**; the body carries `refresh: ""`.

Registration:
- Legacy mode (`EMAIL_VERIFICATION_REQUIRED=False`): `CookieRegisterView.create` (`jokes/views.py:832-849`) calls `RegisterView.create` whose `get_response_data` (`dj_rest_auth/registration/views.py:56-62`) returns `{'user','access','refresh'}` **with the real refresh token** (this path ignores `JWT_AUTH_HTTPONLY`) and then sets cookies. So only in legacy mode does a body expose a refresh token.
- Gated mode (prod: memory says email verification is LIVE since 2026-06-13; `settings.py:478`): returns `201 {"detail": "Verification code sent to your email.", "email": ...}` with **no tokens** (`jokes/views.py:851-891`). The user then calls `POST /api/v1/auth/verify-email/ {email, code}` (`notifications/views.py:40-80`), which returns **`{"user": {"id","email"}}` and cookies only — no `access`, no `refresh` in the body**. A native client that ignores cookies finishes verification with no credentials and must immediately call `/auth/login/` with the password again.

### 1.4 Token refresh

`POST /api/v1/auth/token/refresh/` → `get_refresh_view()` (`dj_rest_auth/jwt_auth.py:87-108`). `CookieTokenRefreshSerializer.extract_refresh_token` (`:66-76`) accepts `refresh` from the JSON body first, else the `jokes-refresh-token` cookie. Response `finalize_response`:
```python
if 'refresh' in response.data:
    set_jwt_refresh_cookie(response, response.data['refresh'])
    if api_settings.JWT_AUTH_HTTPONLY:
        del response.data['refresh']        # <-- rotated refresh token removed from body
```
Combined with `ROTATE_REFRESH_TOKENS=True` + `BLACKLIST_AFTER_ROTATION=True`: a native client that somehow had a refresh token in hand and POSTs it gets `{"access": "...", "access_expiration": ...}` back, the old refresh token is **blacklisted**, and the new one exists **only in the Set-Cookie header**. Unless the client parses `Set-Cookie` (or lets `HTTPCookieStorage` do it) it is locked out after the first refresh.

The view sets `authentication_classes=()` (simplejwt `TokenViewBase`), so it is never CSRF-checked (`settings.py:437-439` comment; frontend relies on this in `AuthProvider.tsx:25-38`).

### 1.5 Logout

`POST /api/v1/auth/logout/` (`dj_rest_auth/views.py:149-220`): with `JWT_AUTH_HTTPONLY=True` it reads the refresh token **only from the cookie** (`:187-191`); if absent → `401 {"detail": "Refresh token was not included in cookie data."}` (prod probe confirmed: POST with no cookie → 401 + two expiring Set-Cookie headers). A native client that authenticates by Bearer header and does not send cookies **cannot blacklist its refresh token via logout**; it can only discard it locally (the refresh token still lives up to 24 h).

### 1.6 CSRF: cookie path vs header path

`JWTCookieAuthentication.authenticate` (`dj_rest_auth/jwt_auth.py:137-150`): `enforce_csrf` runs only when `header is None` AND the JWT cookie is present AND `JWT_AUTH_COOKIE_USE_CSRF` (True). **Bearer-header requests are never CSRF-checked.** Django's `CsrfViewMiddleware` is installed (`settings.py:98`) but DRF views are `csrf_exempt` at dispatch, so the only CSRF gate for API calls is the one inside the authenticator. Consequences for iOS:
- If the app sends Bearer on every request and never stores cookies → no CSRF token needed, no `X-CSRFToken`, no `/auth/csrf/` bootstrap.
- If the app relies on `URLSession`'s default cookie jar (it will silently store `jokes-access-token`, `jokes-refresh-token`, `csrftoken`, `jf_anon_reads`) AND omits the header on some request → Django's double-submit check runs, and it also verifies `Origin`/`Referer` against `CSRF_TRUSTED_ORIGINS` (`settings.py:369-371`; a URLSession request has no `Origin`, and Django then requires a `Referer` on HTTPS → `403 CSRF Failed: Referer checking failed - no Referer.`).
- `GET /api/v1/auth/csrf/` (`jokes/views.py:794-819`) returns `{"csrfToken": ...}` and sets `csrftoken` (`SameSite=None; Secure`, 1-year, prod probe).

Recommendation is therefore "Bearer everywhere, cookies disabled" — which forces the refresh-token-in-body problem of 1.3/1.4 to be fixed.

### 1.7 Other auth endpoints available

From `dj_rest_auth/urls.py` mounted at `/api/v1/auth/` (`JokesForProject/urls.py:61`): `login/`, `logout/`, `user/` (GET/PUT/PATCH → `JokesForUserDetailsSerializer`, exposes `pk, username, email, first_name, last_name, date_of_birth(read-only)`; `JokesForProject/serializers.py:13-32`), `password/change/` (`OLD_PASSWORD_FIELD_ENABLED=True` → needs `old_password`), `password/reset/` (emails `FRONTEND_URL/reset-password?uid=&token=` — `jokes/password_reset.py:31-37`), `password/reset/confirm/`, `token/verify/`, `token/refresh/`. `registration/verify-email/` and `registration/resend-email/` are dj-rest-auth's allauth-key variants (unused; `ACCOUNT_EMAIL_VERIFICATION='none'`, `settings.py:522`); the live code-based flow is `auth/verify-email/` + `auth/resend-verification/` (`notifications/urls.py`), throttled `3/15min` (`settings.py:310`).

---

## 2. Google Sign-In and Sign in with Apple

### 2.1 What `GoogleLogin` expects today

`jokes/views.py:893-931`:
```python
class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    callback_url = settings.GOOGLE_OAUTH_CALLBACK_URL   # default http://localhost:5173/auth/google/callback; prod env → https://jokesforfront.web.app/auth/google/callback
    client_class = OAuth2Client
```
The web client uses the **authorization-code flow** (`src/features/auth/google-oauth.ts` builds `response_type=code`; `GoogleCallbackPage.tsx` POSTs `{code, date_of_birth?}` once). Tests (`jokes/tests_google_age_gate.py:69-75,90-139`) only exercise `{'code': ...}`.

`SocialLoginSerializer.validate` (`dj_rest_auth/registration/serializers.py:81-158`) accepts **three inputs**: `access_token` (Case 1, optional `id_token` alongside), or `code` (Case 2, exchanged server-side via `callback_url` = the web redirect URI). `id_token` **alone is rejected** (`'Incorrect input. access_token or code is required.'`, `:146-148`). For `provider_id == 'google' and not code` it calls `adapter.complete_login(..., response={'id_token': id_token})` (`:154-155`); allauth's `GoogleOAuth2Adapter.complete_login` (`allauth/.../google/views.py:83-94`) decodes the id_token if present, else fetches userinfo with the access token. `_decode_id_token` verifies signature against Google certs with `audience=app.client_id` (`:96-105`, `_verify_and_decode`).

So an iOS client using the GoogleSignIn SDK can POST `{"access_token": <sdk access token>, "id_token": <sdk id token>, "date_of_birth": "YYYY-MM-DD"}` **without any view change** — but only if the allauth `SocialApp.client_id` equals the **iOS OAuth client ID** (id_token `aud`), or the client omits `id_token` and sends only `access_token` (then allauth calls the userinfo endpoint; the access token issued to the iOS client works there regardless of client id — but the `SocialApp` is still needed for `app`).

The `date_of_birth` stash (`jokes/views.py:927-931` → `JokesForProject/adapters.py`) works identically for any input mode: new users without DOB get `400 {"code": "dob_required", "detail": ...}`; under-13 gets `400 {"date_of_birth": ["You must be at least 13 years old to use Jokes For."]}`.

### 2.2 Would iOS need its own SocialApp?

Yes for id_token verification (Google issues the id_token with `aud` = the iOS client ID, which differs from the web client ID). The `SocialApp` is a DB row created via Django shell/admin (`.planning/phases/06-authentication/06-03-PLAN.md:94-114`); `SOCIALACCOUNT_PROVIDERS['google']` (`settings.py:532-538`) has no `APP`/`APPS` key, so the settings source is unused.

Problem: `SocialLoginSerializer.validate` does `adapter.get_provider().app` → `DefaultSocialAccountAdapter.get_app(request, provider='google')` (`allauth/socialaccount/adapter.py:292-303`) with **no `client_id` filter**. With two google `SocialApp` rows on the site it raises `MultipleObjectsReturned` unless all but one are marked `settings={"hidden": true}` — and a hidden app is then never selected by this path either. Practical options (backend change required either way):
1. One `SocialApp` per platform + a dedicated `GoogleLoginIOS` view that overrides `adapter_class`/`get_provider` to pick the app by `client_id` (allauth supports `get_provider(request, provider, client_id=...)`), or
2. Single web `SocialApp` and have iOS use the **web client ID as `serverClientID`** in the GoogleSignIn SDK (the SDK then mints an id_token with `aud` = web client ID; this is the Google-recommended "backend auth" pattern). Then `{"access_token","id_token"}` works with the existing app row. This is the lowest-touch option but must be validated against `_decode_id_token`'s audience check.

Also: `SOCIALACCOUNT_PROVIDERS['google']['OAUTH_PKCE_ENABLED']=True` and `AUTH_PARAMS access_type=offline` only affect the code flow.

### 2.3 Sign in with Apple — NOT PRESENT

- `INSTALLED_APPS` (`settings.py:46-80`) has `allauth.socialaccount.providers.google` only; `allauth.socialaccount.providers.apple` is installed in site-packages (`.venv/.../providers/apple` exists) but not enabled.
- `grep -ri apple` across backend `*.py`/`*.md` (excluding venv): zero hits. No `AppleLogin` view, no URL, no adapter branch, no Apple `SocialApp`, no key/team/key-id settings.
- App Store Review Guideline 4.8 requires an equivalent privacy-preserving login (SIWA qualifies) when third-party/social login is offered. With Google login shipped, **SIWA is a hard requirement** for App Store submission. The `SocialAccountAdapter.pre_social_login` DOB gate (`JokesForProject/adapters.py:99-120`) is provider-agnostic and would apply to Apple too, but Apple's private relay email and "name only on first login" semantics need handling in `save_user`.

---

## 3. Registration, age gate, consent payloads

- `POST /api/v1/auth/registration/` body: `{"email","password1","password2","date_of_birth": "YYYY-MM-DD"}` — `EmailOnlyRegisterSerializer` (`JokesForProject/serializers.py:35-105`). `date_of_birth` required, write-only; future dates → `Enter a valid date of birth.`; age < 13 → `You must be at least 13 years old to use Jokes For.` `username` is set to the email (`:96`). Password validators are Django defaults (`settings.py:193-206`).
- Response: gated mode `201 {detail, email}` (no tokens); `502` if the email provider fails (`jokes/views.py:869-882`). Legacy mode `201 {user, access, refresh}` + cookies.
- Verification: `POST /api/v1/auth/verify-email/ {email, code}` → `200 {"user": {id,email}}` + cookies; errors `400 {"code": ["Incorrect code."]}` / `{"code": ["This code has expired..."]}` / `429 {"detail": "Too many attempts..."}`. Resend: `POST /api/v1/auth/resend-verification/ {email}` → always `200` (anti-enumeration).
- Adult gating (`jokes/serving.py:25-70`, `UserProfile.is_adult` `jokes/models.py:579-583`): tier_2/mature content only when `date_of_birth` gives age ≥ 18 AND `UserPreference.show_mature` (`jokes/models.py:334`). Anonymous and null-DOB users are tier_1 only. `GET /api/v1/auth/user/` exposes `date_of_birth` (read-only) so the client can compute adult status.
- **Consent is client-side only.** The web app stores analytics consent in `localStorage` (`src/features/consent/storage.ts`, key `jokesfor-consent`, `{version, analytics, ts}`) and gates telemetry locally (`src/lib/telemetry.ts:gateOpen`: authenticated AND adult AND `consent.analytics`). The backend has **no consent endpoint or field for analytics consent**; the only related server flag is `UserProfile.share_analytics` (`jokes/models.py:538`, default False), read/written via `GET/PATCH /api/v1/users/me/preferences/` (`jokes/views.py:2103,2136`) but not used to gate ingestion. An iOS client must re-implement the consent gate locally (and, if App Tracking Transparency is relevant, decide what counts as tracking — the telemetry is first-party only).
- Account deletion (App Store guideline 5.1.1(v)): `DELETE /api/v1/users/me/` exists (`jokes/views.py:2399-2425`). Password accounts must send `{"password": ...}`; OAuth/unusable-password accounts must send `{"confirm": "DELETE"}`. Data export: `GET /api/v1/users/me/data-export/`.
- Profile: `GET/PATCH /api/v1/users/me/profile/` (`jokes/views.py:1922-1988`) — PATCH accepts `first_name, last_name, bio, display_name, handle`; avatar upload is **not** exposed by any endpoint (`UserProfile.avatar` exists at `models.py:522` but no view writes it).

---

## 4. Media upload contract

`POST /api/v1/media/uploads/` — `MediaUploadView` (`jokes/views.py:1480-1626`), `IsAuthenticated`, `MultiPartParser/FormParser`, `ScopedRateThrottle` scope `media-upload` = **30/hour** (`settings.py:312`).

Request: multipart fields `kind` (`image`|`video`|`audio`, default `image`) and `file`. A `.gif` (by content-type `image/gif` or `.gif` name) is always routed through the video pipeline regardless of `kind`.

Limits (`jokes/media_processing.py`):
| kind | max bytes | source formats | other caps | output |
|---|---|---|---|---|
| image | 10 MiB (`:17`) | JPEG/PNG/WEBP (`:16`) | ≤4096 px source (`:18`), downscaled to 1600 px max (`:19`) | `image.webp` |
| video | 30 MiB (`:140`) | anything ffprobe accepts | ≤60 s (`:143`), ≤1080p×1.2 pixels (`:144`) | `video.mp4` + `poster.jpg` |
| gif | 15 MiB (`:141`) | GIF | same as video | mp4 + poster, `is_gif=true` |
| audio | 10 MiB (`:142`) | anything ffprobe accepts | ≤60 s | `audio.m4a` (AAC 128k) |

iOS-relevant format gap: **HEIC/HEIF (default iPhone camera format) is rejected** (`ALLOWED_SOURCE_FORMATS = {'JPEG','PNG','WEBP'}`, `:16,:90`) — the client must transcode to JPEG before upload. HEVC `.mov` videos go through ffmpeg (the Docker image installs ffmpeg, `Dockerfile:39`) and are re-encoded to H.264 mp4, so they work if under 30 MiB / 60 s.

Processing is synchronous, in-request: Pillow/ffmpeg → SafeSearch (`screen_image`, Vision API, fail-open) → hash matcher → storage write. `FFMPEG_TIMEOUT=240s` (`:145`), gunicorn `--timeout 300` (`Dockerfile:64-70`), Cloud Run request timeout 300 s. There is an encode-slot semaphore (`_EncodeSlot`, `:157-170`) that returns **`429 {"detail": "Media processing is busy — try again in a moment."}` with `Retry-After: 30`** when saturated (`jokes/views.py:1554-1558,1580-1584`). The iOS `URLSession` upload task must therefore use a **≥300 s timeout** and treat 429+Retry-After as retryable.

Other responses: `400 {"kind": [...]}`/`{"file": [...]}` validation; `422 {"file": ["This image was rejected by automated content screening."]}` / `["This image cannot be uploaded."]` (hash hit) / `["This clip was rejected..."]`; `201` → `MediaAssetSerializer` (`jokes/serializers.py:139-162`): `{id (uuid), kind, url, poster_url, width, height, duration_ms, is_gif, created_at}`. URLs are absolute (`request.build_absolute_uri`) — in prod they resolve to public GCS `https://storage.googleapis.com/<bucket>/...` (`settings.py:243-276`, `querystring_auth=False`, non-expiring). **No polling is needed**: the asset is final on 201. Orphan assets are swept per-upload after 24 h (`_sweep_orphan_assets`, `jokes/views.py:1436-1445`), so a client must attach the `id` via `media_asset_ids` on `POST /api/v1/jokes/my-drafts/` / `submit/` (`JokeSubmissionCreateSerializer.media_asset_ids`, `jokes/serializers.py:864-923`) within 24 h.

Platform caveat: Cloud Run's HTTP/1 request body limit is 32 MiB; a 30 MiB video plus multipart overhead sits just under it. `FILE_UPLOAD_MAX_MEMORY_SIZE`/`DATA_UPLOAD_MAX_MEMORY_SIZE` are Django defaults (not set in `settings.py`), so uploads >2.5 MiB spool to disk (`media_processing.py:216-232` relies on this).

**Schema gap**: the OpenAPI for this operation declares `"responses": {"200": {"description": "No response body"}}` and no multipart request schema (fetched schema, `/api/v1/media/uploads/`); Swift codegen would produce a `Void`-returning call and no typed request. Needs `@extend_schema(request=..., responses={201: MediaAssetSerializer})`.

---

## 5. Paywall / entitlements and Apple IAP implications

Endpoints:
- `GET /api/v1/jokes/daily-reads/` (`AllowAny`, `jokes/views.py:387-413`) → `{limit (null=unlimited), used, remaining, over, reset_at (ISO next-midnight-UTC)}`.
- `POST /api/v1/jokes/{id}/reveal/` (`AllowAny`, `:647-686`) — anonymous consumption ledger; 204 for authenticated users.
- `GET /api/v1/billing/entitlements` (`IsAuthenticated`, `billing/views.py:363-372`) → `{plan, features: {creator_analytics, daily_joke_preview, mature_content_addon}, limits: {mystery_box_rolls_per_day, submissions_per_day, daily_jokes_per_day, daily_joke_history_days, free_joke_reads_per_day}}` (`billing/entitlements.py:18-37`).
- `GET /api/v1/billing/my-subscription`, `GET /api/v1/billing/plans` (public).
- `POST /api/v1/billing/checkout-session {plan_slug}` → `{url}` (Stripe Checkout, subscription mode); `409 active_subscription` guard with optional `portal_url`; `503 billing_unavailable` when `STRIPE_SECRET_KEY` unset.
- `POST /api/v1/billing/portal-session` → `{url}`.
- `POST /api/v1/tips/checkout/ {amount_cents ∈ {100,300,500,1000}, creator_id, joke_id?}` → `{checkout_url, tip_id}` (`billing/views.py:102-190`), throttle `tips-checkout` 30/hour.
- Webhook `POST /api/v1/billing/webhook` (Stripe-signed) is the only thing that flips `Subscription` state.

Server-side enforcement is uniform: `JokeSerializer.to_representation` nulls `punchline`/`lines` (and `text` for text-only formats) and strips media URLs when `is_locked` (`jokes/serializers.py:254-318`); locked retrievals are not logged (`jokes/views.py:175-208`). The anonymous ledger is a **signed httpOnly cookie `jf_anon_reads`** (`jokes/paywall.py:39-113`), set on `GET /jokes/{id}/` and `POST /jokes/{id}/reveal/` responses. A native client that does not persist cookies will **never be "over"** as an anonymous reader (soft wall is bypassed entirely); one that does persist cookies mirrors the web. This is a product decision: either accept, or add a device-scoped header ledger.

Apple IAP decisions (flagged, not code facts):
- **Premium subscription unlock inside the app must use StoreKit/IAP** (Guideline 3.1.1); the current Stripe Checkout `url` (and `BILLING_SUCCESS_URL`/`CANCEL_URL` defaulting to `http://localhost:5173/billing/...`, prod env → web routes; `settings.py:512-514`, `billing/stripe_gateway.py:72-73,120-121,141`) cannot be surfaced as an in-app purchase path. Backend needs an **App Store Server Notifications v2 / receipt-validation path that writes `Subscription`** with a non-Stripe provider (today `Subscription` is keyed by `stripe_subscription_id`/`stripe_customer_id`; `billing/views.py:64-70`), and `effective_plan` (`billing/entitlements.py:44-70`) must resolve Apple-sourced subs.
- **Creator tips**: money to individual creators for digital content is treated by Apple as IAP-required unless it is a pure person-to-person gift with 100% pass-through and no platform fee (Guideline 3.2.1(vii)). Decision: either route tips through IAP consumables (and rebuild the `Tip` model around Apple transactions) or hide tipping in the iOS build. Stripe's fixed tiers and `Tip` ledger are web-only as written.
- "Reader" app / external-link entitlements are a possible alternative but require Apple approval and still forbid in-app Stripe checkout.
- Plan slugs/prices are Stripe-driven (`Plan.stripe_price_id`); an IAP product-id mapping column would be needed.

---

## 6. Push notifications

**No device-token model exists.** `grep -ri "apns|fcm|device_token|push_token"` over the backend returns nothing. The `inbox` app is an in-app notification list only (`inbox/views.py`: `GET /api/v1/notifications/` paginated 20/page, `GET .../unread-count/` → `{count}`, `POST .../mark-read/` → `{marked}`). The `notifications` app is email (verification, digests via `POST /internal/run-digests/` token-guarded and dormant). `UserPreference.notification_enabled/notification_time/notification_days` (`jokes/models.py:311-313`) only feed the "today-status" ritual computation (`jokes/views.py:3131-3144`) — nothing sends a push. An iOS app can poll `unread-count` or schedule **local** notifications from `notification_time`; real APNs needs a new `DeviceToken` model + registration endpoint + a request-triggered sender (no workers/cron per project constraint; memory: single Cloud Run app).

---

## 7. Deep links / universal links

- Share URL returned by `POST /api/v1/jokes/{id}/share/` is `request.build_absolute_uri('/jokes/{id}/share/')` → **backend origin** `https://jokesforbackend-...run.app/jokes/{id}/share/` (`jokes/views.py:614-645`). That page (`joke_share_page`, `:1352-1433`) renders OG/JSON-LD and redirects humans (meta-refresh + `location.replace`) to `FRONTEND_URL/jokes/{id}` (`jokes/templates/jokes/share.html:13,106`, `share_redirect.html`). Tier-gated jokes get a content-free redirect shell. Prod probe: `/jokes/1/share/` → 404 (joke 1 does not exist; not a bug).
- Other deep-link surfaces pointing at `jokesforfront.web.app`: password reset email (`/reset-password?uid=&token=`, `jokes/password_reset.py:31-37`), Google callback URL (`GOOGLE_OAUTH_CALLBACK_URL`), Stripe success/cancel/portal-return URLs, sitemap (`jokes/sitemap.py`), email digests (links built from `FRONTEND_URL`/`BACKEND_URL`; `settings.py:357,491`).
- For iOS universal links, the **frontend Firebase host** must serve `/.well-known/apple-app-site-association` (JSON, `application/json`, no redirect). `firebase.json` currently rewrites `**` → `/index.html` (`firebase.json:10-13`) and `public/` contains only `Logos`, `robots.txt`, `vite.svg`; so an AASA file would need to be added under `public/.well-known/` plus a rewrite exception. The backend share host (`*.run.app`) is a second domain — either add AASA there too (Cloud Run serving a static file; the Django app would need a route) or change `share_url` to the frontend origin. Paths to claim: `/jokes/*`, `/reset-password`, `/creators/*` etc. (frontend `src/app/routes.tsx`).
- No custom URL scheme or `.well-known` handling exists in either repo today.

---

## 8. OpenAPI schema quality for Swift codegen

`SPECTACULAR_SETTINGS` (`settings.py:327-331`) is minimal: `TITLE`, `DESCRIPTION`, `VERSION='1.0.0'`. No `SERVERS`, no `COMPONENT_SPLIT_REQUEST`, no `ENUM_NAME_OVERRIDES`, no `SCHEMA_PATH_PREFIX`, no custom `postprocessing_hooks`. Endpoints: `/api/schema/` (YAML default; `?format=json`), `/api/docs/` (Swagger), `/api/redoc/` (`JokesForProject/urls.py:80-82`). Schema is `AllowAny` (security lists `{}`), so codegen can fetch it unauthenticated.

Prod schema (fetched 2026-08-25, 146 KB YAML):
- 110 paths, 130 operations, **0 duplicate operationIds**. IDs are path-derived: `v1_jokes_list`, `v1_auth_token_refresh_create`, `v1_users_me_streak_freeze_remove_create`, etc. (drf-spectacular default; prefix `v1_` from `URLPathVersioning`). Usable, verbose; `SCHEMA_PATH_PREFIX = r'/api/v[0-9]'` would drop the prefix and produce tags per resource instead of a single `v1` tag (every op is tagged `v1`).
- `securitySchemes`: `jwtHeaderAuth` (`http bearer, bearerFormat JWT`) and `jwtCookieAuth` (`apiKey in cookie jokes-access-token`) — both auto-emitted by spectacular's dj-rest-auth extension. Per-operation `security` correctly lists `[jwtHeaderAuth] | [jwtCookieAuth] | {}` for public and without `{}` for authenticated. Good for Swift (generators map `http bearer` cleanly).
- 79 component schemas with sane names (`Joke`, `PaginatedJokeList`, `JokesForUserDetails`, `PatchedJokeSubmissionCreate`, enums `SourceEnum`, `RatingEnum`, ...). A few generic names would collide in a larger schema: `Overview`, `Audience`, `Suggestion`, `TopJoke`, `Source`/`SourceEnum`, `Streak`.
- **49 of 130 operations have no typed response** ("No response body" / status 200 only). Notable: `media/uploads/` (201 → MediaAsset), `auth/verify-email/`, `billing/entitlements`, `billing/my-subscription`, `billing/plans`, `billing/checkout-session`, `tips/checkout/`, `notifications/` (paginated), `users/me/profile/` (GET+PATCH), `users/me/preferences/`, `users/me/activity/`, `users/me/achievements/`, `follows/*`, `tags/*`, `themes/popular/`, `users/top-jokesters/`, `jokes/{id}/reveal/`. These are plain `APIView`s without `@extend_schema`. Swift codegen yields `Void` for all of them; the client would hand-write models.
- 14 inline (anonymous) response objects (`daily-reads`, `rate`, `react`, `reactions`, `share`, `telemetry/events`, `today-status`, `complete-onboarding`) and 2 bare `{type: object}` (`daily-jokes/tomorrow/`, `taste-profile/`). Swift generators emit ad-hoc `*Response200` structs or `AnyCodable` for these.
- `JWT` component requires `refresh: string` (it will be `""`); `TokenRefresh` requires `refresh` on request and marks `access` readOnly — but the real response also has `access_expiration` and lacks `refresh` (see 1.4), so the generated model is wrong in both directions.
- `Login` has `username`/`email` optional + `password` required — fine.
- `VerifyEmail {key}` describes the unused allauth-key endpoint; the live `auth/verify-email/ {email, code}` is untyped.
- Request bodies are offered as `application/json`, `application/x-www-form-urlencoded`, `multipart/form-data` for every serializer op; Swift generators handle this but produce noisier code.
- `PageNumberPagination` responses are typed `Paginated<X>List {count, next, previous, results}` with `next/previous` as absolute URLs (`?page=N`), not cursors.
- `format` query param on `/api/schema/` and `?format=json|yaml` on every op (DRF format suffix) — harmless.
- Enum for `lang` on `/api/schema/` bloats the file (Django locale list) — harmless.

Verdict: usable for Swift codegen (e.g. `swift-openapi-generator`/`openapi-generator swift5`) after adding `@extend_schema` responses to the ~49 untyped views and fixing `JWT`/`TokenRefresh` component accuracy; otherwise expect roughly a third of the client to be hand-written.

---

## 9. Pagination, versioning, throttling, headers

- Pagination: `PageNumberPagination`, `PAGE_SIZE=10` (`settings.py:302-303`), no `page_size` query override (`page_size_query_param` not set anywhere; grep of `Pagination` shows only default-class instantiations with hard-coded `page_size` 10/20 in `billing/views.py:197`, `inbox/views.py:20`, `creator_insights/views.py:71`). Responses `{count, next, previous, results}`; `next` is an absolute URL to the backend origin (`X-Forwarded-Proto` honored via `SECURE_PROXY_SSL_HEADER`). Creator profile nests a `jokes_pagination` object instead (`creator_insights/views.py:75-80`).
- Versioning: `URLPathVersioning`, `ALLOWED_VERSIONS=['v1']`, `DEFAULT_VERSION='v1'` (`settings.py:318-320`). Version is only in the path; no `Accept`-header versioning, no deprecation headers.
- Throttling (`settings.py:303-315`): anon 100/hour, user 1000/hour globally (note: anonymous browsing of the feed at 100 req/hour per IP is tight for an app that prefetches; NAT'd carriers share IPs), scoped: `verification_resend 3/15min`, `creator_insights 120/hour`, `media-upload 30/hour`, `appeals 10/day`, `tips-checkout 30/hour`. Backing store is `DatabaseCache` (`settings.py:137-147`) so limits are global across instances. On 429 DRF returns `{"detail": "Request was throttled. Expected available in N seconds."}` and a **`Retry-After` header** (`rest_framework/views.py:92`). **No `X-RateLimit-*` headers** are emitted. The media view adds its own `Retry-After: 30` on the busy-slot 429.
- Response headers (prod probe on `GET /api/v1/jokes/`): `content-type: application/json`, `vary: Accept, origin`, `allow`, `x-frame-options: DENY`, `x-request-id` (from `RequestContextMiddleware`), HSTS preload, `x-content-type-options: nosniff`, `referrer-policy: same-origin`, `cross-origin-opener-policy: same-origin`, `x-cloud-trace-context`. No `ETag`/`Cache-Control` on API responses (only `cache-control: private` on the CSRF view). No `Accept-Language` handling of substance (`LANGUAGE_CODE=en-us`, `USE_I18N=True` but no locale middleware).
- Error format: DRF default (`{"detail": "..."}`, or field → list-of-strings maps; custom `{"code": ..., "detail": ...}` on some billing/adapter errors). No custom `EXCEPTION_HANDLER` → an iOS client needs a tolerant error decoder (string, list, or object per key).
- Timestamps: ISO-8601 UTC (`TIME_ZONE='UTC'`); `reset_at` from paywall is `+00:00`-suffixed; model fields render `Z` (prod probe shows both `2026-07-05T17:18:29Z` and `...08.524179Z` — microseconds sometimes present, so use a lenient `ISO8601DateFormatter` with fractional seconds option).

---

## 10. Telemetry contract (creator_insights ingestion)

`POST /api/v1/telemetry/events` (`TelemetryIngestView`, `jokes/views.py:3287-3445`), `IsAuthenticated`, default user throttle (1000/hour — the `creator_insights` scope is only used by the insights GET). Body:
```json
{"events": [
  {"joke": 123, "type": "impression", "source": "feed"},
  {"joke": 123, "type": "reveal", "source": "feed"},
  {"joke": 123, "type": "dwell", "value": 4200, "scroll_pct": 80, "source": "feed"},
  {"joke": 123, "type": "watch", "watch_ms": 9000, "watch_pct": 60, "source": "feed"}
]}
```
Rules: batch truncated to 50 (`MAX_BATCH`); `source` any string, truncated to 16 chars, default `other` (the web uses `feed|explore|search|daily|pack|other`); unknown jokes/types skipped silently; `dwell.value` and `watch.watch_ms` must be JSON **integers** (bools and floats rejected), clamped to [0, 600000], dropped if < 500; `scroll_pct`/`watch_pct` optional ints clamped 0-100; impressions dedup to one per (user, joke, UTC day); `reveal` flips `JokeView.revealed_punchline` or creates a `JokeView(source, revealed_punchline=True)`. Always `202 {"accepted": N}`.

Separately, `GET /api/v1/jokes/{id}/?source=daily|search|explore|mystery|pack|saved|share|other` logs a `JokeView` (debounced 60 s) for authenticated users — the native client should pass `source` on detail fetches to keep insights/streak/recently-viewed correct (`jokes/views.py:175-208`, `JokeView.SOURCE_CHOICES` `models.py:1030-1039`). Anonymous reveal must go through `POST /jokes/{id}/reveal/` (which then depends on the cookie ledger; see 5).

What a native client must send: Bearer auth (the web's `sendBeacon` fallback relies on cookies; iOS should use a background `URLSession` with the header), batches ≤50, integer ms, and it must implement the consent/adult gate locally (backend does not check consent). The web flushes at 10 events and on page-hide; iOS analog: flush on `scenePhase == .background` with a background task.

---

## 11. Browser-only assumptions inventory

| Assumption | Where | Impact on iOS |
|---|---|---|
| Refresh token only in httpOnly cookie | `JWT_AUTH_HTTPONLY=True` (`settings.py:428`), `dj_rest_auth/views.py:92-95`, `jwt_auth.py:103-106` | Cannot renew sessions without cookie jar; logout impossible without cookie |
| verify-email returns cookies only | `notifications/views.py:72-80` | Post-verification bootstrap needs a second login |
| CSRF double-submit + Origin/Referer check on cookie path | `JWT_AUTH_COOKIE_USE_CSRF=True`, `CSRF_TRUSTED_ORIGINS` (`settings.py:369-371`) | If cookies leak into URLSession, mutations 403 |
| `SameSite=None; Secure` cookies | `JWT_COOKIE_SAMESITE=None` in prod | irrelevant to URLSession but shows cross-site web design |
| Anonymous paywall ledger is a cookie | `jokes/paywall.py:39-113` | Anonymous soft wall silently absent on iOS |
| CORS allow-list | `CORS_ALLOWED_ORIGINS` (`settings.py:340-352`) | Not enforced for non-browser clients (no `Origin` → no CORS processing); harmless |
| Google login = web auth-code flow with fixed `callback_url` | `jokes/views.py:918-920`, `GOOGLE_OAUTH_CALLBACK_URL` | iOS must use `access_token`(+`id_token`) mode; SocialApp client-id mismatch |
| Share URL on backend host, redirect to `jokesforfront.web.app` | `jokes/views.py:640`, share templates | Universal links need AASA on two hosts or a URL change |
| Password-reset link → SPA route | `jokes/password_reset.py:31-37` | Needs universal-link claim on `/reset-password` or an in-app code flow |
| Stripe Checkout/Portal URLs are web pages with web return URLs | `settings.py:512-514`, `billing/stripe_gateway.py` | Not usable for in-app purchase; IAP required |
| Unsubscribe pages are server-rendered HTML | `notifications/views.py:_html_page` | fine (email-only) |
| Consent stored in `localStorage` | frontend only | iOS re-implements; no server record |
| `X-CSRFToken` header in CORS allow-list | `settings.py:352` | n/a |
| No `Accept-Language`, no ETags, no cache headers | global | client-side caching only |
| `HEIC` not accepted for images | `media_processing.py:16` | client transcodes |
| Avatar upload has no endpoint | `UserProfile.avatar` unused by views | profile pictures impossible from iOS (and web) |

---

## 12. Prioritized backend changes for an iOS app

**Required (blocking a shippable App Store build)**
1. **Native token issuance**: add a way for non-browser clients to receive the refresh token in the body and get the rotated refresh token back from `/auth/token/refresh/`. Options: (a) a `X-Client: ios` / `?client=native` switch that makes login/social/verify-email/refresh views include `refresh` (bypassing the `JWT_AUTH_HTTPONLY` deletion) and skip cookies; or (b) set `JWT_AUTH_HTTPONLY=False` globally (weakens the web's XSS posture — not recommended); or (c) dedicated `/api/v1/auth/native/{login,refresh,logout}` views built on simplejwt's `TokenObtainPairView`/`TokenRefreshView` directly. Also make `verify-email` return tokens on the native path, and make logout accept `{"refresh": ...}` in the body on the native path. Enable `JWT_AUTH_RETURN_EXPIRATION=True` (harmless for web, gives iOS `access_expiration`).
2. **Sign in with Apple**: enable `allauth.socialaccount.providers.apple`, add `AppleLogin(SocialLoginView)` accepting `{id_token, access_token?/code, date_of_birth?}` from `ASAuthorizationAppleIDCredential`, configure Apple `SocialApp` (team id, key id, private key, bundle-id client ids for native), extend `SocialAccountAdapter.save_user` to persist the first-login name and handle private-relay emails. Reuse the DOB gate.
3. **Google Sign-In for iOS**: decide between (a) iOS uses the web client id as `serverClientID` and posts `{access_token, id_token}` to the existing `/auth/google/`, or (b) a second `SocialApp` + a view that resolves the app by `client_id` (today two google apps → `MultipleObjectsReturned`). Add a test for the `access_token`/`id_token` input mode (currently only `code` is tested).
4. **Apple IAP for premium**: server-side App Store receipt/JWS validation + App Store Server Notifications endpoint writing `Subscription` with an `apple` provider; `effective_plan()` must honor it; map `Plan` → IAP product ids. Decide the fate of tips on iOS (IAP consumable vs hidden).
5. **Typed OpenAPI responses** for the 49 untyped operations and correct `JWT`/`TokenRefresh`/`media/uploads` shapes, so Swift codegen is trustworthy. Consider `SCHEMA_PATH_PREFIX`, `COMPONENT_SPLIT_REQUEST`, and `SERVERS`.
6. **Universal links**: serve `/.well-known/apple-app-site-association` on the frontend host (and on the backend host or move `share_url` to `FRONTEND_URL`), claim `/jokes/*`, `/reset-password`, creator routes. Consider returning the frontend URL from `POST /jokes/{id}/share/`.

**Strongly recommended**
7. **Anonymous paywall for native**: replace/augment the `jf_anon_reads` cookie with a client-supplied opaque device id header (`X-Device-Id`) signed-ledger, or accept that anonymous iOS readers are unmetered.
8. **Push notifications**: `DeviceToken` model (`user, platform, token, created_at, last_seen`), `POST/DELETE /api/v1/users/me/devices/`, and request-triggered APNs sends (e.g. on inbox `Notification` creation) — must stay inside the single-service constraint (no workers), so keep it synchronous and best-effort.
9. **Server-side consent record** (`analytics_consent`, `consent_version`, timestamp) so telemetry ingestion can be gated by the server and the same consent is honored across web and iOS; expose on `/auth/user/` or `/users/me/preferences/`.
10. **HEIC/HEIF image ingestion** (Pillow with `pillow-heif`) or document that the client must transcode; document the 300 s upload timeout and the 429/`Retry-After` retry contract in the schema.
11. **Rate-limit visibility**: emit `X-RateLimit-Limit/Remaining/Reset` (custom throttle subclass) and raise the anon limit or exempt lookup endpoints; NAT'd mobile IPs share the 100/hour anon bucket.
12. **Password reset for native**: either rely on universal links for `/reset-password?uid&token` or add a 6-digit-code reset flow like verify-email.

**Optional / nice to have**
13. Avatar upload endpoint (`PATCH /users/me/profile/` multipart) — `UserProfile.avatar` exists but is unreachable.
14. `page_size` query param support and/or cursor pagination for the feed; `ETag`/`Cache-Control` on lookup tables (`formats`, `tones`, `vibes`, ...).
15. Consistent error envelope (custom `EXCEPTION_HANDLER`) so Swift can decode one error type.
16. Drop `application/x-www-form-urlencoded`/`multipart` from JSON-only operations in the schema (spectacular `PARSER_WHITELIST`) to simplify generated clients.
17. Fix the `GoogleLogin` docstring (claims `refresh` is returned in the body).

---

## Appendix A — endpoint groups an iOS client would consume (all under `/api/v1/`, from `jokes/urls.py`, `billing/urls.py`, `billing/tip_urls.py`, `creator_insights/urls.py`, `follows/urls.py`, `follows/user_urls.py`, `inbox/urls.py`, `notifications/urls.py`, `dj_rest_auth` urls)

Auth: `auth/login/`, `auth/logout/`, `auth/user/`, `auth/token/refresh/`, `auth/token/verify/`, `auth/registration/`, `auth/verify-email/`, `auth/resend-verification/`, `auth/password/change/`, `auth/password/reset/`, `auth/password/reset/confirm/`, `auth/google/`, `auth/csrf/` (web only).
Catalog: `jokes/` (+`random/`, `trending/`, `daily-reads/`, `{id}/`, `{id}/rate/`, `{id}/my-rating/`, `{id}/react/`, `{id}/reactions/`, `{id}/share/`, `{id}/reveal/`), `formats/`, `age-ratings/`, `tones/`, `context-tags/`, `culture-tags/`, `languages/`, `vibes/`, `packs/` (+`featured/`, `{slug}/`, `{slug}/progress/`), `daily-jokes/today|tomorrow|history/`, `tags/trending|rising/`, `themes/popular/`, `users/top-jokesters/`.
User: `users/me/profile|activity|achievements|preferences|vibes|recently-viewed|streak(+freeze, freeze/remove)|packs/in-progress|today-status|taste-profile|appeals|blocks|following|tips|data-export/`, `users/me/` (DELETE), `users/{id}/block/`, `preferences/me/`, `preferences/complete-onboarding/`, `mystery-box/status|roll/`, `collections/`, `saved-jokes/`, `favorites/`.
Creator: `media/uploads/`, `jokes/submit/`, `jokes/my-drafts/` (+`{id}/`, `{id}/submit/`), `creators/me/insights/`, `creators/{id}/profile/`, `creators/{id}/tips/summary/`, `follows/{id}/` (+`status/`, `followers/`), `reports/`, `appeals/`, `telemetry/events`.
Billing: `billing/plans|entitlements|my-subscription|checkout-session|portal-session`, `tips/checkout/`.
Inbox: `notifications/`, `notifications/unread-count/`, `notifications/mark-read/`.
Non-API: `/jokes/{id}/share/` (HTML), `/sitemap.xml`, `/healthz`, `/readyz`, `/api/schema/`.

## Appendix B — docs vs code disagreements found
- `jokes/views.py:893-918` `GoogleLogin` docstring says the response includes a real `refresh` token; code (`JWT_AUTH_HTTPONLY=True`) returns `""`.
- `frontend Docs/API_Specification_For_Frontend.md` / `.planning/*` were not relied on; the `.planning/phases/06-authentication/06-03-PLAN.md` note that the Google `SocialApp` lives in the DB is consistent with settings (no `APP` key).
- OpenAPI `TokenRefresh` component says the response returns `refresh`; code deletes it (`dj_rest_auth/jwt_auth.py:103-106`) and adds `access_expiration` which the schema omits.
- OpenAPI `media/uploads/` declares `200 No response body`; code returns `201` + `MediaAssetSerializer`.
