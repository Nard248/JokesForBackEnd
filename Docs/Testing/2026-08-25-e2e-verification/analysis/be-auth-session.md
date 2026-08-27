# JokesFor — Backend Authentication & Session Model (be-auth-session)

Analyzed 2026-08-25, read-only, from code. Backend repo: `/Users/narekmeloyan/PycharmProjects/JokesForProject` (BE). Frontend repo: `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend` (FE). Library sources verified in `BE/.venv/lib/python3.11/site-packages` (dj-rest-auth 7.0.2, django-allauth 65.14.3, djangorestframework-simplejwt 5.5.1, DRF 3.16.1, Django 5.2.17 — `BE/requirements.txt`).

---

## 0. Executive summary

* **Single authenticator**: `REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] = ['dj_rest_auth.jwt_auth.JWTCookieAuthentication']` (`BE/JokesForProject/settings.py:281-283`). No `DEFAULT_PERMISSION_CLASSES` → DRF default `AllowAny` per view unless the view sets `permission_classes`.
* **Two transport modes for the access token, header wins**: `JWTCookieAuthentication.authenticate()` (`dj_rest_auth/jwt_auth.py:134-153`) reads `Authorization: Bearer <access>` first; only if the header is absent does it fall back to the `jokes-access-token` cookie. **Bearer requests are never CSRF-checked.** Cookie-authenticated requests ARE CSRF-checked (`REST_AUTH['JWT_AUTH_COOKIE_USE_CSRF'] = True`, `settings.py:433`).
* **Refresh token is cookie-only**: `JWT_AUTH_HTTPONLY = True` → login/google return `"refresh": ""` in the body; `/auth/token/refresh/` strips `refresh` from its JSON. The only place the refresh token is delivered is the `Set-Cookie: jokes-refresh-token=…` header. (Exception: legacy-mode registration leaks it in the body — see §3.)
* **Lifetimes**: access 15 min, refresh 1 day, rotation + blacklist on every refresh (`SIMPLE_JWT`, `settings.py:459-468`).
* **Email verification gate** is env-driven (`EMAIL_VERIFICATION_REQUIRED`, `settings.py:487`); when on, registration creates an **inactive** user and returns no tokens until `POST /auth/verify-email/` succeeds. Memory notes say the gate is LIVE in prod since 2026-06-13; the doc `Docs/API/Frontend_Email_Verification_Integration.md` still says OFF (stale doc).
* **COPPA**: DOB required (>=13) on email registration (`JokesForProject/serializers.py:59-70`) and on *new* Google signups (`JokesForProject/adapters.py`). No "consent" field exists on the backend at all; consent (cookie/analytics) is purely client-side (`FE/src/features/consent/*`).
* **A non-browser (iOS) client** must: send `Authorization: Bearer`, capture the `jokes-refresh-token` Set-Cookie, and replay it (as a Cookie header or as `{"refresh": …}` body) on `/auth/token/refresh/`; on `/auth/logout/` the refresh token is ONLY read from the cookie. No CSRF needed on the Bearer path. Details in §12.

---

## 1. Settings that define the model (`BE/JokesForProject/settings.py`)

| Setting | Value | Line |
|---|---|---|
| `DEFAULT_AUTHENTICATION_CLASSES` | `['dj_rest_auth.jwt_auth.JWTCookieAuthentication']` | 281-283 |
| `DEFAULT_THROTTLE_CLASSES` | `AnonRateThrottle`, `UserRateThrottle` | 286-289 |
| `DEFAULT_THROTTLE_RATES` | `anon 100/hour`, `user 1000/hour`, `verification_resend 3/15min` (window hard-coded, see §7), `creator_insights 120/hour`, `media-upload 30/hour`, `appeals 10/day`, `tips-checkout 30/hour` | 290-300 |
| `CACHES['default']` | `DatabaseCache` table `jokesfor_cache` (throttle counters are shared across Cloud Run instances) | 178-185 |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173`, `http://127.0.0.1:5173` + env `CORS_ALLOWED_ORIGINS` | 322-325 |
| `CORS_ALLOW_CREDENTIALS` | `True` | 326 |
| `CORS_ALLOW_HEADERS` | defaults + `x-csrftoken` | 334 |
| `FRONTEND_URL` | env, default `https://jokesforfront.web.app` | 339 |
| `CSRF_TRUSTED_ORIGINS` | env list + `FRONTEND_URL` always appended | 352-354 |
| `SECURE_PROXY_SSL_HEADER` | `('HTTP_X_FORWARDED_PROTO','https')` | 359 |
| `_COOKIE_SAMESITE` = env `JWT_COOKIE_SAMESITE` (default `Lax`); if `None` → `CSRF_COOKIE_SAMESITE='None'`, `SESSION_COOKIE_SAMESITE='None'` | 369-372 |
| `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_SECURE` | `not DEBUG` | 373-374 |
| `CSRF_COOKIE_HTTPONLY` | `False` | 381 |
| HSTS/SSL redirect | on when `not DEBUG` | 386-397 |
| `REST_AUTH` | see §2 | 409-447 |
| `SIMPLE_JWT` | `ACCESS_TOKEN_LIFETIME=15min`, `REFRESH_TOKEN_LIFETIME=1day`, `ROTATE_REFRESH_TOKENS=True`, `BLACKLIST_AFTER_ROTATION=True`, `UPDATE_LAST_LOGIN=True`, `HS256`, `SIGNING_KEY=SECRET_KEY`, `AUTH_HEADER_TYPES=('Bearer',)` | 459-468 |
| `EMAIL_VERIFICATION_REQUIRED` | env, default false | 487 |
| `EMAIL_VERIFICATION_CODE_TTL_MINUTES` | env, default 10 | 488 |
| `EMAIL_VERIFICATION_MAX_ATTEMPTS` | env, default 5 | 489 |
| allauth: `ACCOUNT_LOGIN_METHODS={'email'}`, `ACCOUNT_SIGNUP_FIELDS=['email*','password1*','password2*']`, `ACCOUNT_EMAIL_VERIFICATION='none'`, `ACCOUNT_UNIQUE_EMAIL=True` | 529-532 |
| `SOCIALACCOUNT_ADAPTER` | `JokesForProject.adapters.SocialAccountAdapter` | 539 |
| `SOCIALACCOUNT_PROVIDERS['google']` | `SCOPE ['profile','email']`, `AUTH_PARAMS access_type=offline`, `OAUTH_PKCE_ENABLED True` | 542-548 |
| `GOOGLE_OAUTH_CALLBACK_URL` | env, default `http://localhost:5173/auth/google/callback` | 551 |
| `AUTHENTICATION_BACKENDS` | `ModelBackend`, `allauth.account.auth_backends.AuthenticationBackend` | 114-117 |
| `INSTALLED_APPS` includes `rest_framework_simplejwt.token_blacklist`, `dj_rest_auth`, `dj_rest_auth.registration`, `allauth.socialaccount.providers.google` | 49-72 |

Note: `rest_framework_simplejwt` blacklist app is installed → `OutstandingToken` rows are created for every refresh token minted (`RefreshToken.for_user` / `outstand()`), and `BlacklistedToken` rows on rotation/logout/deletion.

Note: `django.middleware.csrf.CsrfViewMiddleware` is in `MIDDLEWARE` (`settings.py:107`) but DRF views are `csrf_exempt` at the Django level; for API views CSRF is enforced **only** via `JWTCookieAuthentication.enforce_csrf` (below). Non-DRF views (Django admin, `/jokes/<pk>/share/`) get the normal middleware check.

## 2. `REST_AUTH` (dj-rest-auth) — exact values (`settings.py:409-447`)

```
USE_JWT=True
JWT_AUTH_COOKIE='jokes-access-token'
JWT_AUTH_REFRESH_COOKIE='jokes-refresh-token'
JWT_AUTH_HTTPONLY=True
JWT_AUTH_COOKIE_USE_CSRF=True
JWT_AUTH_SECURE = not DEBUG
JWT_AUTH_SAMESITE = env JWT_COOKIE_SAMESITE (default 'Lax'; prod is documented as 'None')
SESSION_LOGIN=False
REGISTER_SERIALIZER='JokesForProject.serializers.EmailOnlyRegisterSerializer'
USER_DETAILS_SERIALIZER='JokesForProject.serializers.JokesForUserDetailsSerializer'
PASSWORD_RESET_SERIALIZER='jokes.password_reset.FrontendPasswordResetSerializer'
OLD_PASSWORD_FIELD_ENABLED=True
```
Library defaults that apply (`dj_rest_auth/app_settings.py`): `JWT_AUTH_REFRESH_COOKIE_PATH='/'`, `JWT_AUTH_COOKIE_DOMAIN=None`, `JWT_AUTH_RETURN_EXPIRATION=False`, `LOGOUT_ON_PASSWORD_CHANGE=False`, `JWT_AUTH_COOKIE_ENFORCE_CSRF_ON_UNAUTHENTICATED=False`, `LOGIN_SERIALIZER=dj_rest_auth.serializers.LoginSerializer`, `JWT_SERIALIZER=JWTSerializer`, `JWT_TOKEN_CLAIMS_SERIALIZER=simplejwt TokenObtainPairSerializer`.

### 2.1 Cookie attributes actually emitted (`dj_rest_auth/jwt_auth.py:12-53`)
* `jokes-access-token`: value=access JWT, `expires=now+15min`, `Secure=not DEBUG`, `HttpOnly=True`, `SameSite=<JWT_AUTH_SAMESITE>`, no `Domain`, path `/` (Django default).
* `jokes-refresh-token`: value=refresh JWT, `expires=now+1day`, same flags, `Path=/` (`JWT_AUTH_REFRESH_COOKIE_PATH`).
* `csrftoken`: Django default (1 year), `Secure=not DEBUG`, `HttpOnly=False`, `SameSite=None` in prod.
* Logout: `delete_cookie` for both JWT cookies (Max-Age=0) with matching samesite (`jwt_auth.py:59-67`).
* Anonymous paywall ledger cookie `jf_anon_reads` (`BE/jokes/paywall.py:40-42,106-113`): signed (`django.core.signing`, salt `jokes.paywall.anon`), `max_age=48h`, `Secure=not DEBUG`, `HttpOnly=True`, `SameSite=CSRF_COOKIE_SAMESITE or 'Lax'`. This is session-adjacent: an anonymous client's 10/day reveal cap lives in this cookie (soft wall).

### 2.2 JWT claims
`jwt_encode(user)` (`dj_rest_auth/utils.py:9-14`) calls `TokenObtainPairSerializer.get_token(user)` → standard simplejwt claims only: `token_type`, `exp`, `iat`, `jti`, `user_id` (default `USER_ID_CLAIM`). No custom claims. HS256 signed with Django `SECRET_KEY` (required in prod, `settings.py:36-41`).

`UPDATE_LAST_LOGIN=True` has **no effect** on this app's login path: simplejwt only calls `update_last_login` inside `TokenObtainSerializer.validate` (`rest_framework_simplejwt/serializers.py:80,96`), which dj-rest-auth's `jwt_encode` bypasses. So `User.last_login` is not updated by `/auth/login/` (data export therefore shows `last_login: null` for API-only users; medium confidence — verified by reading both code paths, not by running).

## 3. Registration — `POST /api/v1/auth/registration/`

URL: `BE/JokesForProject/urls.py:65` maps to `jokes.views.CookieRegisterView` (declared BEFORE the `dj_rest_auth.registration.urls` include on line 66, so it overrides the library `RegisterView` at the root path; sub-paths `verify-email/`, `resend-email/`, `account-confirm-email/<key>/`, `account-email-verification-sent/` from the library remain mounted — see §13 risk).

View: `BE/jokes/views.py:821-890` (`CookieRegisterView(RegisterView)`). `permission_classes` = `REGISTER_PERMISSION_CLASSES` default `AllowAny`. `throttle_scope='dj_rest_auth'` is **inert** (no `ScopedRateThrottle` in defaults and no such rate) → only `anon 100/hour` per IP applies.

Serializer: `BE/JokesForProject/serializers.py:40-105` `EmailOnlyRegisterSerializer`:
* Fields: `email` (required), `password1`, `password2` (write-only), `date_of_birth` (required, `DateField`, ISO `YYYY-MM-DD`). **No username field; username := email** (line 96).
* `validate_email`: allauth `clean_email` then `User.objects.filter(email__iexact=...)` → `"A user is already registered with this e-mail address."` (returned as `{"email":[...]}`, 400). Note: enumerating, by design.
* `validate_password1`: allauth `clean_password` → Django validators (`AUTH_PASSWORD_VALIDATORS` `settings.py:189-202`: similarity, min length 8, common, numeric) → `{"password1":[...]}`.
* `validate_date_of_birth`: `>= today` → `"Enter a valid date of birth."`; age < 13 → `"You must be at least 13 years old to use Jokes For."` (age computed with month/day adjust, lines 59-70) → `{"date_of_birth":[...]}`.
* `validate`: mismatch → `{"password2":["The two password fields didn't match."]}`.
* `save`: creates user, `set_password`, persists DOB to `user.profile.date_of_birth` (profile auto-created by signal; `BE/jokes/models.py:541-546`), `setup_user_email` creates an allauth `EmailAddress` row (unverified — irrelevant because `ACCOUNT_EMAIL_VERIFICATION='none'`).

Modes (`views.py:836-889`):
* **Legacy** (`EMAIL_VERIFICATION_REQUIRED=False`): `super().create()` → `RegisterView.perform_create` mints tokens via `jwt_encode`, calls allauth `complete_signup` (no-op email-wise), response **201 `{access, refresh, user}`** via `JWTSerializer` — note: **the refresh token IS in the body here** (unlike login), then `set_jwt_cookies` sets both cookies. Audit `registration success`, metric `mode=legacy`. Verified by `notifications/tests/test_registration_flow.py:66-77`.
* **Gated** (`True`): serializer save → `user.is_active=False` → `verification.issue_and_send(user)` → **201 `{"detail":"Verification code sent to your email.","email":<email>}`, no tokens, no cookies**. If email send raises `EmailSendError` → **502 `{"detail":"We couldn't send your code right now. Please use \"Resend code\" in a moment.","email":…}`**; the inactive user + unconsumed code remain (recoverable via resend). Audit `registration` success/failure, metric `mode=gated`. Tests: `test_registration_flow.py:17-57`.

No consent capture in the payload. Terms/Privacy acceptance is implied by copy only (`FE/src/pages/RegisterPage.tsx:474`).

## 4. Login / logout / refresh / verify (dj-rest-auth + simplejwt)

Routes (`dj_rest_auth/urls.py`, mounted at `/api/v1/auth/`; regex allows optional trailing slash): `login/`, `logout/`, `user/`, `password/change/`, `password/reset/`, `password/reset/confirm/`, `token/verify/`, `token/refresh/`.

### 4.1 `POST /auth/login/` (`dj_rest_auth/views.py:29-124`, `serializers.py:21-131`)
* Body: `{"email","password"}` (`username` accepted but ignored: `ACCOUNT_LOGIN_METHODS={'email'}` → `_validate_email`). Missing → 400 `{"non_field_errors":["Must include \"email\" and \"password\"."]}`.
* `authenticate()` via allauth backend (`allauth/account/auth_backends.py:74-99`): password OK but `user_can_authenticate` fails on `is_active=False` → returns `None` → **400 `{"non_field_errors":["Unable to log in with provided credentials."]}`**. This is what an **unverified (inactive) user** gets; the `"User account is disabled."` branch (`validate_auth_user_status`) is unreachable here. Wrong password → same message. `user_login_failed` signal fires → audit row `login failure` with hashed identifier (`BE/audit/signals.py:26-49`).
* `validate_email_verification_status`: only enforces when allauth `EMAIL_VERIFICATION == 'mandatory'` — it's `'none'` → no-op.
* Success **200 `{"access":"<jwt>","refresh":"","user":{pk,username,email,first_name,last_name,date_of_birth}}`** + `Set-Cookie` for both tokens. `SESSION_LOGIN=False` → no Django session, no `sessionid`, and **`user_logged_in` signal does not fire → no audit 'login success' row for API logins** (only failures are audited). `throttle_scope='dj_rest_auth'` inert → anon 100/hour per IP.
* CSRF: not enforced (no JWT cookie yet) — `jokes/tests_csrf.py:106-121`. If a *stale* `jokes-access-token` cookie is present and no Bearer header, `enforce_csrf` DOES run on login (cookie present). The SPA always attaches `X-CSRFToken`, so fine; a test that logs in twice with a cookie jar and no CSRF header would 403.

### 4.2 `POST /auth/token/refresh/` (`dj_rest_auth/jwt_auth.py:70-119`)
* View = simplejwt `TokenRefreshView` subclass: `authentication_classes=()`, `permission_classes=()` (`rest_framework_simplejwt/views.py:14-16`) → **never auth'd, never CSRF-checked**.
* Refresh source: body `refresh` (non-empty) overrides; else cookie `jokes-refresh-token`; else 401 `{"detail":"No valid refresh token found.","code":"token_not_valid"}`.
* Validation (`simplejwt/serializers.py:111-145`): invalid/expired → 401 `{"detail":"Token is invalid or expired","code":"token_not_valid"}`; blacklisted (reused after rotation) → 401 `"Token is blacklisted"`; user inactive → 401 `no_active_account`. Rotation: old refresh blacklisted, new `jti/exp/iat`, `outstand()`.
* Response **200 `{"access":"<jwt>","access_expiration":"<iso>"}`** (`refresh` key deleted because HTTPONLY) + `Set-Cookie` for new access AND new refresh cookie.
* Consequence: **each refresh extends the session by another 24h**; two concurrent refreshes with the same cookie → the second 401s (blacklisted).

### 4.3 `POST /auth/token/verify/` — simplejwt `TokenVerifyView` (`authentication_classes=()`), body `{"token"}` → 200 `{}` or 401; checks blacklist by `jti` (`simplejwt/serializers.py:166-180`). FE defines `authApi.verifyToken` but nothing calls it.

### 4.4 `POST /auth/logout/` (`dj_rest_auth/views.py:127-203`)
* `permission_classes=(AllowAny,)`. If the request carries the JWT cookie and no Bearer header → CSRF enforced (403 `CSRF Failed` without token). With Bearer → no CSRF.
* Always: `unset_jwt_cookies` (both Max-Age=0). Then, because blacklist app installed and `JWT_AUTH_HTTPONLY=True`, it reads the refresh **from the cookie only** (`request.COOKIES['jokes-refresh-token']`; body `refresh` is ignored on this path). Missing cookie → **401 `{"detail":"Refresh token was not included in cookie data."}`** (cookies still cleared). Already blacklisted/invalid → 401 with that message. Success → **200 `{"detail":"Successfully logged out."}`** and the refresh is blacklisted. The access token remains cryptographically valid until expiry (≤15 min) — no access blacklist.
* No `user_logged_out` signal (no Django session) → no logout audit row.

### 4.5 `GET|PUT|PATCH /auth/user/` (`dj_rest_auth/views.py:206-224`, `IsAuthenticated`)
Serializer `JokesForUserDetailsSerializer` (`BE/JokesForProject/serializers.py:13-30`): fields **`pk, username, email, first_name, last_name, date_of_birth`**; `email` read-only, `date_of_birth` read-only (sourced from `profile.date_of_birth`, null allowed). `username` writable, validated by allauth `clean_username` (uniqueness/blacklist). 401 body when anonymous: DRF `{"detail":"Authentication credentials were not provided."}`; invalid/expired Bearer → 401 `{"detail":"Given token not valid for any token type","code":"token_not_valid","messages":[...]}`; inactive user with valid token → 401 `{"detail":"User is inactive","code":"user_inactive"}` (`simplejwt/authentication.py:138-139`); deleted user → 401 `User not found`. Tests: `jokes/tests_compliance.py:791-810` (DOB present/null).

## 5. CSRF bootstrap

* `GET /api/v1/auth/csrf/` → `csrf_token_view` (`BE/jokes/views.py:794-817`): `@api_view(['GET'])`, `authentication_classes([])`, `AllowAny`; calls `django.middleware.csrf.get_token(request)` → response **`{"csrfToken":"<64-char token>"}`** and `Set-Cookie: csrftoken=…` (the middleware sets it in `process_response`). Idempotent; usable before or after login.
* Enforcement path (`dj_rest_auth/jwt_auth.py:127-153`): when `Authorization` header is absent AND `jokes-access-token` cookie present → `enforce_csrf` runs Django's `CSRFCheck` (`process_request` + `process_view`) → failure raises `PermissionDenied` → **403 `{"detail":"CSRF Failed: <reason>"}`** (e.g. `CSRF token missing`, `CSRF token from the 'X-Csrftoken' HTTP header incorrect`, `Origin checking failed - https://evil.example does not match any trusted origins.`). Checks: `X-CSRFToken` header must match the `csrftoken` cookie (double submit), and for HTTPS requests the `Origin`/`Referer` must be in `CSRF_TRUSTED_ORIGINS` (which always includes `FRONTEND_URL`).
* Safe methods (GET/HEAD/OPTIONS) pass `CSRFCheck` without a token.
* Tests pin the contract: `BE/jokes/tests_csrf.py` (token endpoint, 403 without header, 200 with header, garbage header rejected, login works without token, Stripe webhook exempt).
* Endpoints explicitly outside CSRF: `/auth/csrf/`, `/auth/token/refresh/`, `/auth/token/verify/` (`authentication_classes=()`), `/api/v1/email/unsubscribe/`, `/api/v1/internal/run-digests/` (`authentication_classes=[]`, `notifications/views.py`), billing webhook.

## 6. Google OAuth — `POST /api/v1/auth/google/`

View `GoogleLogin(SocialLoginView)` (`BE/jokes/views.py:893-938`): `adapter_class=GoogleOAuth2Adapter`, `client_class=OAuth2Client`, `callback_url=settings.GOOGLE_OAUTH_CALLBACK_URL`. `post()` stashes `request.data.get('date_of_birth')` on the raw Django request (`adapters.DOB_REQUEST_ATTR='jokesfor_dob_raw'`) then defers to `SocialLoginView.post` = `LoginView.post`.

Serializer `SocialLoginSerializer` (`dj_rest_auth/registration/serializers.py:39-185`) — accepted inputs: **`code`** (authorization code) **or `access_token`** (+ optional **`id_token`**). Nothing else is read — **the `redirect_uri` the SPA sends is silently ignored** (FE `lib/api.ts:47-57` comment claiming the backend accepts it is wrong). Behaviour:
* `code` path: `OAuth2Client(app.client_id, app.secret, adapter.access_token_url, callback_url=GOOGLE_OAUTH_CALLBACK_URL).get_access_token(code)`. Redirect URI sent to Google's token endpoint is therefore always `GOOGLE_OAUTH_CALLBACK_URL` — it must equal the `redirect_uri` the client used at the consent screen (prod: `https://jokesforfront.web.app/auth/google/callback` per FE workflows). Exchange failure → 400 `{"non_field_errors":["Failed to exchange code for access token"]}`. Google's response `id_token` is passed to `complete_login` → allauth decodes it (signature verification skipped when the token was obtained server-side; audience checked = `SocialApp.client_id`) (`allauth/socialaccount/providers/google/views.py:79-107`).
* `access_token` path: `complete_login(response={'id_token': id_token})`; if `id_token` present it is verified (signature + issuer + audience == SocialApp client_id); if absent, allauth GETs `https://www.googleapis.com/oauth2/v2/userinfo` with the access token. **Relevant for iOS**: an `id_token` minted for an iOS OAuth client id will fail the audience check unless the same client id is in `SocialApp.client_id`; sending only `access_token` avoids the audience check.
* Neither → 400 `"Incorrect input. access_token or code is required."`.
* `OAUTH_PKCE_ENABLED=True` in settings has no effect on this flow (dj-rest-auth's `get_access_token(code)` passes no verifier; the SPA sends none).
* Google client credentials come from the DB `SocialApp` row (provider `google`, bound to `Site id=1`), provisioned by `python manage.py setup_social_app` from env `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`SITE_DOMAIN` (`BE/jokes/management/commands/setup_social_app.py`). `settings.py` does not read `GOOGLE_CLIENT_ID` directly.

Age gate adapter `BE/JokesForProject/adapters.py` (`SocialAccountAdapter.pre_social_login`, `save_user`):
* `sociallogin.is_existing` (SocialAccount already linked) → normal login, DOB ignored.
* Local user with same email (iexact) exists but not linked → adapter does nothing; then `SocialLoginSerializer` (`registration/serializers.py:163-172`) with `ACCOUNT_UNIQUE_EMAIL=True` → **400 `{"non_field_errors":["User is already registered with this e-mail address."]}`** — email-registered users cannot "Continue with Google" (no auto-link; allauth `SOCIALACCOUNT_EMAIL_AUTHENTICATION` not enabled).
* New user: `date_of_birth` missing/blank → **400 `{"code":"dob_required","detail":"Date of birth is required to continue."}`** (`DateOfBirthRequired` APIException, flat body); unparsable or `>= today` → 400 `{"date_of_birth":["Enter a valid date of birth."]}`; age < 13 → 400 `{"date_of_birth":["You must be at least 13 years old to use Jokes For."]}`; else account created (**active immediately, no verification code, no usable password**), DOB persisted to profile, username generated by allauth from email local part.
* Success response is identical to login: 200 `{access, refresh:"", user}` + cookies. Tests: `BE/jokes/tests_google_age_gate.py` (5 cases, Google mocked).

Frontend side (`FE/src/features/auth/google-oauth.ts`, `FE/src/pages/GoogleCallbackPage.tsx`, `RegisterPage.tsx:111-122`): browser redirect to `https://accounts.google.com/o/oauth2/v2/auth?client_id=VITE_GOOGLE_CLIENT_ID&redirect_uri=<VITE_GOOGLE_OAUTH_REDIRECT_URI or origin+/auth/google/callback>&response_type=code&scope=openid email profile&access_type=offline&prompt=consent`; signup path validates DOB ≥13 client-side and stashes it in `sessionStorage['auth.signupDob']`; callback page POSTs `{code, redirect_uri, date_of_birth?}` exactly once; `dob_required` → navigates to `/register` with notice (code is spent, never reused).

## 7. Email verification gate (notifications app)

Routes (`BE/notifications/urls.py`, mounted under `/api/v1/auth/` by `JokesForProject/urls.py:68`): `verify-email/` → `VerifyEmailView`, `resend-verification/` → `ResendVerificationView` (`BE/notifications/views.py:38-113`). Both `AllowAny`.

Code lifecycle (`BE/notifications/verification.py`): 6-digit zero-padded `secrets.randbelow`, stored as SHA-256 hex in `EmailVerification(code_hash, expires_at=now+TTL(10m), attempts, consumed_at)` (`notifications/models.py:39-62`); issuing a code first marks all unconsumed codes consumed; verification order: no active code → `no_active_code`; expired → `expired`; `attempts >= MAX(5)` → `too_many_attempts`; mismatch → `attempts += 1`, `incorrect`; match → conditional UPDATE consume (race-safe). Email sent through `notifications.service.send_email` (template `verification_code`, `EmailMessageLog` row, `EMAIL_BACKEND` env: console locally / anymail Resend in prod).

`POST /auth/verify-email/` body `{"email","code"}` (`code` must match `^\d{6}$` else 400 `{"code":["This value does not match the required pattern."]}`):
* unknown email → 400 `{"code":["Incorrect code."]}` (anti-enumeration, same shape as wrong code)
* `user.is_active` already → 400 `{"detail":"This email is already verified. Please log in."}`
* `too_many_attempts` → **429 `{"detail":"Too many attempts. Request a new code."}`**
* `no_active_code` → 400 `{"code":["No active code. Request a new one."]}`; `expired` → `{"code":["This code has expired. Request a new one."]}`; `incorrect` → `{"code":["Incorrect code."]}`
* success → `is_active=True`, `RefreshToken.for_user(user)` → **200 `{"user":{"id":<int>,"email":…}}`** + both JWT cookies. **No `access` in the body** (client must call refresh; FE does exactly this in `useVerifyEmail`, `FE/src/features/auth/api.ts:80-109`). Note `user.id` here vs `user.pk` in the login shape.
No dedicated throttle on verify beyond anon 100/hour/IP; brute force bounded by 5 attempts per code.

`POST /auth/resend-verification/` body `{"email"}` → always **200 `{"detail":"If that email needs verification, a new code has been sent."}`**; only sends when an inactive user with that email exists. Throttle `ResendThrottle` (`notifications/throttles.py`): `SimpleRateThrottle` keyed by normalized email, hard-coded **3 per 900s** (the `'3/15min'` rate string is only there so `get_rate()` doesn't raise) → 429 `{"detail":"Request was throttled. Expected available in N seconds."}`. **Gap**: `verification.issue_and_send` can raise `EmailSendError`, which this view does not catch → 500 when the provider is down (registration handles the same error with 502).

Effect on protected endpoints: an unverified user has **no tokens** at all, so every `IsAuthenticated` endpoint returns 401 `Authentication credentials were not provided.`; login returns 400 `Unable to log in with provided credentials.`; password reset ignores inactive users (§8). If a user is deactivated after obtaining tokens, Bearer/cookie auth → 401 `User is inactive`, refresh → 401 `no_active_account`.

Google signups bypass the gate entirely (`notifications/tests/test_google_exemption.py`).

## 8. Password reset & change

* `POST /auth/password/reset/` `{"email"}` (`dj_rest_auth/views.py:227-246`, `FrontendPasswordResetSerializer` in `BE/jokes/password_reset.py`): allauth form `AllAuthPasswordResetForm.clean_email` filters `is_active=True` users and does **not** error for unknown/inactive emails (`dj_rest_auth/forms.py:39-47`, allauth `PREVENT_ENUMERATION` default True) → always **200 `{"detail":"Password reset e-mail has been sent."}`**. Email rendered from allauth template `account/email/password_reset_key_message.txt` (project override in `BE/templates/`, per `test_reset_roundtrip`), link = **`<FRONTEND_URL>/reset-password?uid=<base36 pk>&token=<allauth token>`** (`password_reset.py:22-31`). Sent via plain Django mail, **not** the notifications engine (no `EmailMessageLog`). Token = allauth `default_token_generator` (Django `PASSWORD_RESET_TIMEOUT` default 3 days).
* `POST /auth/password/reset/confirm/` `{"uid","token","new_password1","new_password2"}` → 200 `{"detail":"Password has been reset with the new password."}`; bad uid → 400 `{"uid":["Invalid value"]}`; bad/expired token → `{"token":["Invalid value"]}`; validator failures → `{"new_password2":[...]}`. **Does not blacklist existing refresh tokens** — other sessions survive a reset. Round-trip test: `BE/jokes/test_reset_roundtrip.py`; link format test `jokes/tests_launch_blockers.py:99-123`.
* `POST /auth/password/change/` (IsAuthenticated) `{"old_password","new_password1","new_password2"}` → 200 `{"detail":"New password has been saved."}`; wrong old → 400 `{"old_password":["Your old password was entered incorrectly. Please enter it again."]}`; missing old → 400 `{"old_password":["This field is required."]}` (`tests_launch_blockers.py:126-159`). `LOGOUT_ON_PASSWORD_CHANGE=False` → tokens untouched. Cookie-auth callers need CSRF header.

## 9. Account deletion (GDPR) — `DELETE /api/v1/users/me/`

`UserAccountDeleteView` (`BE/jokes/views.py:2399-2496`, `IsAuthenticated`). Body (JSON) branch by `user.has_usable_password()`:
* password users: `password` required → 400 `{"password":["This field is required."]}` / `{"password":["Incorrect password."]}`.
* OAuth/unusable-password users: `confirm` must equal `"DELETE"` → 400 `{"confirm":["Type DELETE to confirm account deletion."]}`.
Then in one transaction: blacklist all `OutstandingToken` for the user; `MediaAsset.delete_with_files()` for owned uploads; delete avatar file; purge `EmailMessageLog` (by FK or `to_email`) and `EmailVerification`; media-format jokes by the user are soft-removed (`is_removed=True`); `user.delete()` cascades. Audit `account_delete` with hashed email. Response **204**. Cookies are NOT cleared by the server (client must drop them; an access token then yields 401 `User not found`). Tests `BE/jokes/tests.py:654-758`. The SPA sends `{confirm:"DELETE", password?}` (`FE/src/pages/SettingsPage.tsx:105`) because the User payload has no `has_usable_password` flag.

## 10. Data export — `GET /api/v1/users/me/data-export/`

`DataExportView` (`views.py:2499-2657`, `IsAuthenticated`): synchronous; returns **`application/zip`**, `Content-Disposition: attachment; filename="jokes-for-data-export.zip"` containing `jokes-for-data-export.json` with sections: `export_meta, account{id,email,username,date_joined,last_login,is_active}, profile[], preferences[], collections, saved_jokes, favorites, ratings, reactions, daily_jokes, views(≤5000), streak, streak_days, submissions, media_assets (quarantined → status only, no URL), reports_filed, blocks, achievements, vibes, pack_progress, mystery_rolls, share_events, email_logs`. Removed jokes excluded from saved/favorites. Audit `data_export`. Tests `jokes/tests.py:547-652`. Only the global `user 1000/hour` throttle applies. Does **not** include `date_of_birth` in `profile[]` (only bio/avatar/premium/flags/theme/created_at) — a GDPR-completeness gap since DOB is personal data (it IS exposed via `/auth/user/`).

## 11. Throttling summary for auth endpoints

| Endpoint | Throttle actually applied |
|---|---|
| login, registration, password reset/confirm, google, verify-email, csrf | `AnonRateThrottle` 100/hour per IP (`get_ident`: full `X-Forwarded-For` string when `NUM_PROXIES` unset, else `REMOTE_ADDR`; `rest_framework/throttling.py:23-40`). `throttle_scope='dj_rest_auth'` on the library views is inert. |
| resend-verification | `ResendThrottle` 3/15 min per email (plus anon 100/hour) |
| token/refresh, token/verify | anon 100/hour (unauthenticated views still run default throttles) |
| user/, password/change/, users/me, data-export | `UserRateThrottle` 1000/hour per user id |
Counters live in the `jokesfor_cache` DB table (`notifications/tests/test_throttle_cache.py`). Throttled response: 429 `{"detail":"Request was throttled. Expected available in N seconds."}` + `Retry-After` header. E2E suites hammering `/auth/login/` from one IP can trip the 100/hour limit.

## 12. What the SPA does (`FE/src/lib/axios.ts`, `FE/src/features/auth/*`, `FE/src/app/providers/*`)

* `axios.create({baseURL: VITE_API_URL, withCredentials: true})`; prod `VITE_API_URL=https://jokesforbackend-332865216810.us-east1.run.app/api/v1` (`.github/workflows/firebase-hosting-merge.yml:16`).
* Request interceptor: `Authorization: Bearer <in-memory access>` when present; `X-CSRFToken` on POST/PUT/PATCH/DELETE when a token is cached (`sessionStorage['jokesfor-csrf']`).
* Response interceptor: 403 whose `detail` contains `CSRF` → refetch `/auth/csrf/` and retry once; 401 (not on refresh URL) → single de-duplicated `POST /auth/token/refresh/` (raw axios, cookie-based) → replace Bearer → retry; refresh failure clears the token (store handles redirect).
* Store `zustand/persist` → **`sessionStorage['jokesfor-auth']` = `{user, accessToken, isAuthenticated}`** (access token is JS-readable; HttpOnly cookies are the defence for the refresh token only).
* Bootstrap (`AuthProvider.tsx`): `ensureCsrfToken()`; `POST /auth/token/refresh/` (cookie) → `GET /auth/user/` with Bearer → `setAuth`; any failure → anonymous.
* `useLogin/useGoogleAuth`: `setAuth(data.user, data.access)` then refetch CSRF. `useRegister`: if body has `access` → logged in (legacy) else RegisterPage navigates to `/verify-email?email=…` (`RegisterPage.tsx:147`); 502 → `/verify-email?…&sendFailed=1`. `useVerifyEmail`: after 200 calls `/auth/user/` then `/auth/token/refresh/` for an access token; VerifyEmailPage treats 429 as locked-until-resend and `already verified` → `/login`. `useLogout`: `POST /auth/logout/` (Bearer + CSRF header + cookies) then clears store regardless of outcome.
* Route guards: `ProtectedRoute` → `/login?returnTo=…`; `GuestOnlyRoute` on `/login`, `/register`, `/verify-email`. `/auth/google/callback`, `/forgot-password`, `/reset-password` (uid+token from query, `ForgotPasswordPage.tsx:27-31,253-283`).
* Consent is client-only (`features/consent/storage.ts`, `useConsent.ts`): Firebase analytics initialised only when consent accepted AND `isAdult(user.date_of_birth)`; nothing is sent to the backend.
* Telemetry (`FE/src/lib/telemetry.ts:95-125`) prefers `navigator.sendBeacon` (no Authorization header, cookies only). Because the `jokes-access-token` cookie is present and there is no Bearer header, the server takes the cookie path and **enforces CSRF; sendBeacon cannot set `X-CSRFToken`, so those posts should 403** (the in-code comment says the backend "accepts the httpOnly refresh/session cookie" — inaccurate). `sendBeacon` returns true when queued, so the `fetch` fallback (which does carry Bearer) does not run. Medium confidence (reasoned from code, not observed).

## 13. Docs vs code discrepancies

* `Docs/API/Frontend_Integration_Handout.md:92` says "the API doesn't enforce CSRF" and lists `sessionid`/`messages` cookies as set — stale: CSRF is enforced on the cookie path since `JWT_AUTH_COOKIE_USE_CSRF=True`; `SESSION_LOGIN=False` means API login never creates a Django session.
* `Docs/API/Frontend_Email_Verification_Integration.md` says `EMAIL_VERIFICATION_REQUIRED` is OFF in prod (2026-06-12); memory notes say it was turned on 2026-06-13. Cannot be verified from code (env var).
* FE `lib/api.ts` `GoogleAuthRequest.redirect_uri` doc says the backend accepts it — it does not.
* FE `lib/telemetry.ts` comment about cookie auth for beacons ignores the CSRF check.
* Library registration sub-routes remain mounted (`/api/v1/auth/registration/verify-email/` expects allauth `{key}`, `/resend-email/` would send allauth's own confirmation email for an unverified `EmailAddress` row, `/account-confirm-email/<key>/` is a `TemplateView` with no `template_name` → 500 if hit). Unused by the app; noise/attack surface.

## 14. Non-browser (iOS) client contract — precise

1. **Transport**: always send `Authorization: Bearer <access>`. Then no CSRF token, no Origin header, no CORS concerns. Access tokens expire 15 min after issue; pre-emptively refresh or react to 401 `token_not_valid`.
2. **Obtaining a session**: `POST /api/v1/auth/login/` `{"email","password"}` → body `access`; `POST /api/v1/auth/google/` `{"code"}` (web redirect flow with `redirect_uri` == server `GOOGLE_OAUTH_CALLBACK_URL`) or `{"access_token"}` (native Google Sign-In; omit `id_token` unless its audience equals the server's SocialApp client id) → body `access`; `POST /auth/verify-email/` → **no** `access` in body, must refresh.
3. **Refresh token**: read the `Set-Cookie: jokes-refresh-token=<jwt>; Path=/; HttpOnly; Secure; SameSite=…` header from login/google/verify-email/refresh responses (URLSession's default `HTTPCookieStorage` will store it automatically; Secure cookies require HTTPS). Keep it in Keychain if managing manually. Refresh with either `Cookie: jokes-refresh-token=<jwt>` or JSON `{"refresh":"<jwt>"}` to `POST /api/v1/auth/token/refresh/`; read the **new** refresh from the response `Set-Cookie` every time (rotation + blacklist; the old one is dead). Response JSON gives the new `access` and `access_expiration`.
4. **Logout**: `POST /api/v1/auth/logout/` must carry the refresh as a **Cookie** (body is ignored); response 200 blacklists it. Without the cookie: 401 but cookies cleared anyway. Send Bearer too, to skip CSRF.
5. **Register**: `POST /api/v1/auth/registration/` `{"email","password1","password2","date_of_birth":"YYYY-MM-DD"}`; 201 with `access`+`refresh` in body (legacy) or 201 `{detail,email}` (gated) → then verify-email loop; 502 → offer resend.
6. **Identity**: `GET /api/v1/auth/user/` → `{pk, username, email, first_name, last_name, date_of_birth|null}`.
7. **Deletion**: `DELETE /api/v1/users/me/` with JSON body `{"password"}` or `{"confirm":"DELETE"}` (safe to send both) → 204; discard local tokens.
8. **Anonymous reading**: the 10/day anonymous reveal ledger is the signed HttpOnly cookie `jf_anon_reads` returned by `POST /jokes/<id>/reveal/` — a cookie jar is required for the soft wall to work; without it every request looks fresh.
9. **Throttles**: anon 100/hour per IP for all unauthenticated auth calls; resend 3/15min per email; verify-code 5 wrong guesses per code.

## 15. Test inventory that already pins these behaviours (backend)

`jokes/tests_csrf.py` (CSRF contract), `jokes/tests_google_age_gate.py` (Google DOB gate), `jokes/tests_compliance.py:116-175` (registration DOB), `:791-810` (`/auth/user/` DOB), `jokes/tests.py:547-758` (export + delete), `jokes/test_reset_roundtrip.py`, `jokes/tests_launch_blockers.py:99-159` (reset link, old password), `notifications/tests/test_registration_flow.py`, `test_verify_resend.py`, `test_verification.py`, `test_throttling.py`, `test_throttle_cache.py`, `test_google_exemption.py`. Frontend: `FE/src/features/auth/api.verify.test.tsx`, `parseAuthError.test.ts`, `pages/LoginPage.test.tsx`, `RegisterPage.{agegate,googledob,verify}.test.tsx`, `VerifyEmailPage.test.tsx`.

## 16. Risks / gaps found

1. Resend-verification does not catch `EmailSendError` → 500 (registration returns 502 for the same failure).
2. Password reset/change and new logins never revoke other sessions (no blacklist of other outstanding refresh tokens); only account deletion does.
3. API login success is not audited (`user_logged_in` never fires because `SESSION_LOGIN=False`); `last_login` is never updated on API login.
4. Legacy-mode registration returns the refresh token in the JSON body (contradicts the "refresh is cookie-only" posture); only matters if the gate is ever turned off.
5. Beacon telemetry from cookie-authenticated browsers likely 403s on CSRF (§12).
6. Access token persisted in `sessionStorage` (XSS-readable) on the SPA.
7. Email-registered users cannot sign in with Google for the same address (400 "already registered") — product decision, but worth a test/UX check.
8. Data export omits `date_of_birth`.
9. `/api/v1/auth/registration/{verify-email,resend-email,account-confirm-email}` library routes are exposed but unused (§13).
10. `ACCOUNT_EMAIL_VERIFICATION='none'` plus `EmailAddress.verified=False` rows for all email signups — harmless today, but any future allauth `mandatory` switch would lock everyone out.
