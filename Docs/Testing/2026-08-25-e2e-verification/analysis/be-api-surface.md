# JokesFor Backend — Complete HTTP API Surface (be-api-surface)

Analyzed 2026-08-25 from code in `/Users/narekmeloyan/PycharmProjects/JokesForProject` (Django 5.2 / DRF / dj-rest-auth 7.0.2). All facts below come from reading `JokesForProject/urls.py` and every included URLconf plus the view/serializer/permission/throttle code. Docs were used only as hints.

Backend prod host: `https://jokesforbackend-332865216810.us-east1.run.app`. Every path below is relative to that host.

---

## 0. Cross-cutting facts (apply to every DRF endpoint unless a row says otherwise)

Source: `JokesForProject/settings.py:297-321`, `:424-454`, `:460-469`, `:83-105`.

| Concern | Value |
|---|---|
| Authentication | Single class `dj_rest_auth.jwt_auth.JWTCookieAuthentication`. Reads `Authorization: Bearer <access>` header first; if absent, reads httpOnly cookie `jokes-access-token`. Refresh cookie `jokes-refresh-token`. Access TTL 15 min, refresh 1 day, rotation + blacklist on. |
| CSRF | `JWT_AUTH_COOKIE_USE_CSRF=True` → when the JWT cookie is present AND no `Authorization` header, `enforce_csrf` runs (`dj_rest_auth/jwt_auth.py:135-153`). Cookie-authenticated mutating requests therefore need `X-CSRFToken` header matching the `csrftoken` cookie (bootstrap via `GET /api/v1/auth/csrf/`). Bearer-header requests and requests with no JWT cookie are never CSRF-checked. `APIView` is csrf_exempt at the Django-middleware level, so DRF views only get CSRF through the authenticator. |
| Default permission | `DEFAULT_PERMISSION_CLASSES` is NOT set → DRF default `AllowAny`. Any view/action that does not declare `permission_classes` is public. |
| Pagination | `PageNumberPagination`, `PAGE_SIZE=10`, `?page=N`. **No `page_size_query_param` anywhere in the repo** (grep confirmed; only `VibeViewSet.pagination_class=None` at `jokes/views.py:2673`). Envelope: `{count,next,previous,results}`. |
| Throttling | Defaults `AnonRateThrottle` 100/hour (by IP) + `UserRateThrottle` 1000/hour (by user id) on every DRF view that does not override `throttle_classes`. Scoped rates defined: `verification_resend` 3/15min, `creator_insights` 120/hour, `media-upload` 30/hour, `appeals` 10/day, `tips-checkout` 30/hour. No `dj_rest_auth` rate is defined and `ScopedRateThrottle` is not a default class → the `throttle_scope='dj_rest_auth'` on login/logout/register/password views is inert; they get the default anon/user throttles. Throttle counters live in the DB cache table (`readyz` probes it). |
| Versioning | `URLPathVersioning`, allowed `['v1']`; the URLconf hardcodes `api/v1/` (no `<version>` kwarg), so `request.version` is always the default `v1`. |
| Schema | drf-spectacular; `/api/schema/` served with `SERVE_PERMISSIONS=AllowAny` (library default). `RunDigestsView.post` is `@extend_schema(exclude=True)`. |
| Content-tier gate ("age gating") | `jokes/serving.py:allowed_tiers(request)`: anon → `{tier_1}`; authenticated but no profile/pref → `{tier_1}`; `profile.is_adult` False → `{tier_1}`; adult AND `preference.show_mature` → `{tier_1,tier_2}`; `tier_3` never served. Applied per endpoint as noted below. |
| Paywall (`is_locked`) | `jokes/paywall.py:paywall_state(request)` computed once per request and injected as serializer context. Free authenticated users: limit = `free_joke_reads_per_day` entitlement (default 10), ledger = distinct `JokeView.joke_id` for (user, today UTC). Paid plans (limit `None`) → never locked. Anonymous: signed cookie `jf_anon_reads` (salt `jokes.paywall.anon`, max-age 48h, date-scoped) with the same 10/day cap (soft wall). `JokeSerializer` (`jokes/serializers.py:254-318`) sets `is_locked=True` iff `state.over` AND joke id not in `consumed_ids`; when locked: `punchline=None`, `lines=None`, `text=None` for text-only formats (`TEXT_ONLY_FORMATS` = formats whose required fields are exactly `['text']`), `media` reduced to `{kind,width,height}` (no URLs). `setup` is always kept. |
| Moderation | `Joke.objects` default manager excludes `is_removed=True`; `visible_jokes()/hidden_user_ids()` (`jokes/moderation.py`) hide jokes from users in a block relationship with the viewer. |
| Identity in responses | `public_display_name()/public_handle()` (`jokes/identity.py`) — email is never exposed on public surfaces. |
| Audit | Many mutations call `audit.services.record_audit(...)` (registration, media upload, report, appeal, block/unblock, account delete, data export, digest run). |

Auth levels used in the tables: **anon** (AllowAny), **auth** (IsAuthenticated), **creator** (IsAuthenticated + `IsCreator` = ≥1 `JokeSubmission` with status `published`, `creator_insights/permissions.py`), **staff** (Django admin `is_staff`), **token** (shared-secret header), **signature** (Stripe signature). There is **no per-endpoint "verified email" permission class**: verification is enforced only by `user.is_active` (unverified users are inactive and cannot log in / hold tokens).

---

## 1. Infrastructure, SEO, admin, docs (plain Django or non-API)

Source: `JokesForProject/urls.py:30-49,88-91`, `JokesForProject/health.py`, `jokes/sitemap.py`, `jokes/views.py:1352-1433`.

| # | Method | Path | View | Auth | Throttle | Notes |
|---|---|---|---|---|---|---|
| 1 | GET (any) | `/healthz` | `health.healthz` (plain Django, `@csrf_exempt`) | anon | none | Always `200 {"status":"ok"}`; touches no DB/cache. |
| 2 | GET (any) | `/readyz` | `health.readyz` | anon | none | `SELECT 1` + cache set/get/delete. `200 {status:"ready",checks:{db:{status,latency_ms},cache:{...}},version}` or `503 {status:"not_ready",...}`. `version` = `K_REVISION`/`GIT_SHA`/`unknown`. |
| 3 | GET | `/sitemap.xml` | `jokes.sitemap.sitemap_view` (`@require_GET`) | anon | none | `application/xml` urlset. Static frontend routes (`/`, `/daily`, `/trending`, `/privacy`, `/terms`, `/cookie-policy`, `/childrens-privacy`) + `/jokes/{id}` for `is_removed=False, content_tier in BASE_TIERS(tier_1)` (cap 20000, lastmod=updated_at) + `/creators/{id}` for distinct non-null `creator_id` of those jokes (cap 5000) + `/packs/{slug}` for published packs within publish/expiry window (cap 2000). All `<loc>` use `settings.FRONTEND_URL` (default `https://jokesforfront.web.app`). Non-GET → 405. |
| 4 | * | `/admin/...` | `django.contrib.admin` | staff (session login) | none | Standard admin subtree (no custom `get_urls` found). Counted as one route. |
| 5 | GET | `/jokes/<int:pk>/share/` | `jokes.views.joke_share_page` (`@require_GET`) | anon | none | HTML share shell. Joke fetched via default manager (removed → 404). If `joke.content_tier not in allowed_tiers(request)` → renders `jokes/share_redirect.html` (content-free redirect to `FRONTEND_URL/jokes/{id}`). Otherwise `jokes/share.html` with OG/Twitter meta, `title`=first 60 chars of `setup or text` (never punchline), `description`=160 chars, `badge_text`=first tone, JSON-LD `CreativeWork` (author = Organization "JokesFor"), `share_image_url` if `joke.share_image`. Humans are bounced to the SPA by meta-refresh/JS. |
| 6 | GET | `/api/schema/` | `SpectacularAPIView` | anon | default | OpenAPI 3 document. |
| 7 | GET | `/api/docs/` | `SpectacularSwaggerView` | anon | default | Swagger UI. |
| 8 | GET | `/api/redoc/` | `SpectacularRedocView` | anon | default | Redoc UI. |
| 9 | GET | `/api/v1/` | DRF `DefaultRouter` API root | anon | default | Lists the 14 registered router prefixes. DefaultRouter also registers `.json`-style format-suffix variants of every router route. |

---

## 2. Authentication & account credentials

Source: `JokesForProject/urls.py:63-79`, `.venv/.../dj_rest_auth/urls.py`, `.venv/.../dj_rest_auth/registration/urls.py`, `jokes/views.py:795-931`, `notifications/views.py:40-107`, `JokesForProject/serializers.py`, `jokes/password_reset.py`.

Path resolution order matters: `api/v1/auth/csrf/` → `dj_rest_auth.urls` → explicit `api/v1/auth/registration/` (CookieRegisterView) → `dj_rest_auth.registration.urls` → `api/v1/auth/google/` → `notifications.urls`. The explicit `registration/` path shadows dj-rest-auth's own `''` RegisterView; the include still owns `registration/verify-email/`, `registration/resend-email/`, `registration/account-confirm-email/<key>/`, `registration/account-email-verification-sent/`.

| # | Method | Path | View | Auth | Throttle | Request | Response / behavior |
|---|---|---|---|---|---|---|---|
| 10 | GET | `/api/v1/auth/csrf/` | `csrf_token_view` (`@api_view`, `authentication_classes=[]`, AllowAny) | anon | default | — | `200 {"csrfToken": "<token>"}`; sets `csrftoken` cookie (`CSRF_COOKIE_HTTPONLY=False`, SameSite from `JWT_COOKIE_SAMESITE`, Secure when not DEBUG). |
| 11 | POST | `/api/v1/auth/login/` (trailing slash optional: `re_path(r'login/?$')`) | `dj_rest_auth.views.LoginView` | anon | default (scope `dj_rest_auth` inert) | `{email, password}` (`username` optional) | `200 {access, refresh:"", user:{pk,username,email,first_name,last_name,date_of_birth}}` + sets both JWT cookies. Inactive (unverified) user → `400 {"non_field_errors":["Unable to log in..."|"User account is disabled."]}`. `SESSION_LOGIN=False` → no Django session. |
| 12 | POST | `/api/v1/auth/logout/` | `LogoutView` | anon-permitted (AllowAny) but needs refresh cookie | default | — (reads `jokes-refresh-token` cookie) | `200 {"detail":"Successfully logged out."}`; unsets both cookies; blacklists refresh token. Missing refresh cookie → `401 {"detail":"Refresh token was not included in cookie data."}` (cookies still cleared). GET → 405 (`ACCOUNT_LOGOUT_ON_GET` unset). |
| 13 | GET / PUT / PATCH | `/api/v1/auth/user/` | `UserDetailsView` (serializer `JokesForUserDetailsSerializer`) | auth | default | PUT/PATCH: `username, first_name, last_name` | `{pk, username, email, first_name, last_name, date_of_birth}` (`date_of_birth` read-only from `profile.date_of_birth`; `pk`,`email` read-only). |
| 14 | POST | `/api/v1/auth/password/change/` | `PasswordChangeView` | auth | default | `{old_password, new_password1, new_password2}` (`OLD_PASSWORD_FIELD_ENABLED=True`) | `200 {"detail":"New password has been saved."}` |
| 15 | POST | `/api/v1/auth/password/reset/` | `PasswordResetView` (serializer `jokes.password_reset.FrontendPasswordResetSerializer`) | anon | default | `{email}` | `200 {"detail":"Password reset e-mail has been sent."}` regardless of existence; email link = `FRONTEND_URL/reset-password?uid=<uidb64>&token=<key>`. |
| 16 | POST | `/api/v1/auth/password/reset/confirm/` | `PasswordResetConfirmView` | anon | default | `{uid, token, new_password1, new_password2}` | `200 {"detail":"Password has been reset with the new password."}` / 400 on bad uid/token. |
| 17 | POST | `/api/v1/auth/token/refresh/` | dj-rest-auth `RefreshViewWithCookieSupport` (`authentication_classes=()` → never CSRF-checked) | anon (needs refresh cookie or body) | default | `{refresh}` optional; falls back to `jokes-refresh-token` cookie | `200 {access, access_expiration}`; sets new access cookie; with `ROTATE_REFRESH_TOKENS` sets a new refresh cookie and deletes `refresh` from body (httpOnly). Missing → `401 {"detail":"No valid refresh token found."}`. |
| 18 | POST | `/api/v1/auth/token/verify/` | simplejwt `TokenVerifyView` | anon | default | `{token}` | `200 {}` or `401`. |
| 19 | POST | `/api/v1/auth/registration/` | `jokes.views.CookieRegisterView` (subclass of dj-rest-auth `RegisterView`; serializer `EmailOnlyRegisterSerializer`) | anon | default | `{email, password1, password2, date_of_birth (YYYY-MM-DD, required)}` | Validation: email unique (case-insensitive), passwords match, DOB in the past and age ≥ 13 (`400 {"date_of_birth":["You must be at least 13 years old to use Jokes For."]}`). `username` is set to the email; DOB stored on `profile.date_of_birth`. **Gated mode** (`EMAIL_VERIFICATION_REQUIRED=true`, prod): user created `is_active=False`, 6-digit code emailed, `201 {"detail":"Verification code sent to your email.","email":...}`, no cookies; email-provider failure → `502 {"detail":"We couldn't send your code right now...","email":...}` (row exists, recover via resend). **Legacy mode** (flag false): `201 {access, refresh, user}` + JWT cookies. Audit `registration` recorded. |
| 20 | POST | `/api/v1/auth/verify-email/` | `notifications.views.VerifyEmailView` | anon | default | `{email, code:/^\d{6}$/}` | Unknown email → `400 {"code":["Incorrect code."]}` (anti-enumeration). Already active → `400 {"detail":"This email is already verified. Please log in."}`. `verification.verify_code` errors: `no_active_code`/`expired`/`incorrect` → `400 {"code":[msg]}`; `too_many_attempts` (≥ `EMAIL_VERIFICATION_MAX_ATTEMPTS`) → `429 {"detail":"Too many attempts. Request a new code."}`. Success → activates user, `200 {"user":{"id","email"}}` + sets JWT cookies. |
| 21 | POST | `/api/v1/auth/resend-verification/` | `notifications.views.ResendVerificationView` | anon | `ResendThrottle` ONLY (3 per 15 min, keyed by normalized email; replaces defaults) | `{email}` | Always `200 {"detail":"If that email needs verification, a new code has been sent."}`; sends only if an inactive account with that email exists. |
| 22 | POST | `/api/v1/auth/google/` | `jokes.views.GoogleLogin` (`SocialLoginView`, `GoogleOAuth2Adapter`, PKCE, callback `GOOGLE_OAUTH_CALLBACK_URL`) | anon | default | `{code, date_of_birth?}` | Existing/linked user: logs in, DOB ignored. New user with no DOB → `400 {"code":"dob_required","detail":...}`; new user under 13 → `400 {"date_of_birth":[...]}` (no account created, `JokesForProject/adapters.py`). Success → `200 {access, refresh, user}` + JWT cookies. |
| 23 | POST | `/api/v1/auth/registration/verify-email/` | dj-rest-auth `VerifyEmailView` (allauth key-based) | anon | default | `{key}` | Legacy allauth link flow — **not used by this product** (`ACCOUNT_EMAIL_VERIFICATION='none'`; the 6-digit code flow is #20). GET → 405. |
| 24 | POST | `/api/v1/auth/registration/resend-email/` | dj-rest-auth `ResendEmailVerificationView` | anon | default | `{email}` | Always `200 {"detail":"ok"}`; sends allauth confirmation only if an unverified `EmailAddress` row exists. Legacy, unused by the SPA. |
| 25 | GET | `/api/v1/auth/registration/account-confirm-email/<key>/` | `TemplateView` (no `template_name`) | anon | none | — | Exists only so allauth `reverse()` works. A real GET raises `ImproperlyConfigured` → 500. Dead route. |
| 26 | GET | `/api/v1/auth/registration/account-email-verification-sent/` | `TemplateView` (no `template_name`) | anon | none | — | Same dead-route caveat as #25. |

---

## 3. Email unsubscribe & internal digest trigger

Source: `notifications/views.py:168-281`, `JokesForProject/urls.py:82-86`.

| # | Method | Path | View | Auth | Throttle | Behavior |
|---|---|---|---|---|---|---|
| 27 | GET | `/api/v1/email/unsubscribe/?token=<signed>` | `EmailUnsubscribeView` (`authentication_classes=[]`, AllowAny) | anon | default | Never mutates. Valid token → `200 text/html` confirm page containing a POST form (token in hidden field, HTML-escaped). Invalid/expired → `400 text/html` friendly error page. |
| 28 | POST | `/api/v1/email/unsubscribe/` | same | anon | default | Token from body `token` or query `?token=` (RFC 8058 List-Unsubscribe-Post). `apply_unsubscribe(token)` flips the preference; `200 text/html` "You're unsubscribed" page; bad token → `400` error page. Not CSRF-checked (no authenticator). |
| 29 | POST | `/api/v1/internal/run-digests/` | `RunDigestsView` (`authentication_classes=[]`, `throttle_classes=[]`, schema-excluded) | token | none | Requires header `X-Digest-Token` equal (constant-time) to `settings.DIGEST_CRON_TOKEN`. Missing header, wrong token, or empty server secret (dormant) → **404** (never 401/403). Success → runs `run_daily_digests()`, audit `digest_run`, `200 <summary dict>`. |

---

## 4. Jokes — reading, feed, engagement (`jokes/urls.py`, router prefix `jokes`)

Source: `jokes/views.py:142-688`. `JokeViewSet` is `ReadOnlyModelViewSet` with **no class-level `permission_classes`** (→ AllowAny) and per-action overrides. `get_queryset()` = `Joke.objects.filter(content_tier__in=allowed_tiers)` → `visible_jokes()`; `get_serializer_context()` injects `paywall_state`.

| # | Method | Path | Action / view | Auth | Throttle | Request | Response / behavior |
|---|---|---|---|---|---|---|---|
| 30 | GET | `/api/v1/jokes/` | `JokeViewSet.list` (`views.py:270`) | anon | default | query: `q`, `joke_format`, `age_rating`, `tones`(csv), `context_tags`(csv), `culture_tags`(csv), `language`, `vibe`, `ordering` (`-created_at`, `popularity`, `relevance`), `page` | Paginated `JokeSerializer` (10/page). Uses `Joke.objects.search(...)` with `allowed_tiers`; `vibe` unknown/inactive → `400 {"detail":"Unknown vibe 'x'."}`; excludes blocked users' jokes; eager loads to avoid N+1. Each item carries `is_locked` and stripped payoff when locked. Fields: `id,text,setup,punchline,lines,media[],format{},age_rating{},language{},source{},tones[],context_tags[],themes[](alias),categories[](alias),culture_tags[],share_image_url,is_locked,created_at,updated_at`. |
| 31 | GET | `/api/v1/jokes/{pk}/` | `JokeViewSet.retrieve` (`views.py:175`) | anon | default | query `source` (one of `daily,search,explore,mystery,pack,saved,share,other`; else `other`) | `JokeSerializer` or 404 (removed / wrong tier / blocked). If authenticated and the joke is delivered **unlocked**, creates a `JokeView` row (60-second debounce per user+joke) — this is the paywall ledger. Locked delivery logs nothing. Anonymous unlocked delivery appends the id to the `jf_anon_reads` cookie (`record_anon_read`). |
| 32 | GET | `/api/v1/jokes/random/` | `@action random` | anon | default | — | Random joke from allowed tiers minus blocked creators; `404 {"detail":"No jokes found."}` when empty. Paywall context applied. |
| 33 | GET | `/api/v1/jokes/daily-reads/` | `@action daily_reads` (`permission_classes=[AllowAny]`) | anon | default | — | `200 {limit (int|null), used, remaining (int|null), over, reset_at (ISO next midnight UTC)}`. Paid tiers → `limit=null, remaining=null, over=false`. Anonymous → cookie-ledger state. |
| 34 | GET | `/api/v1/jokes/trending/` | `@action trending` (AllowAny; also in `get_permissions`) | anon | default | `period` = `today`(1d) / `week`(7d, default) / `month`(30d) | Paginated list of `{rank, joke:{JokeSerializer}, likes, shares, comments:0, trending_since}` for jokes with ≥1 recent like/share/save, ordered by `likes + 2*shares + saves`. Note: `prefetch_related` here omits `media__asset` (minor N+1 on media jokes). |
| 35 | POST | `/api/v1/jokes/{pk}/rate/` | `@action rate` (IsAuthenticated) | auth | default | `{"rating": 1 | -1}` | `200 {rating, created, joke_score}`; other values → `400 {"error":"Rating must be 1 (like) or -1 (dislike)"}`. Upserts `JokeRating`. |
| 36 | GET | `/api/v1/jokes/{pk}/my-rating/` | `@action get_rating` (url_path `my-rating`, IsAuthenticated) | auth | default | — | `{id, rating, created_at, updated_at, joke_score}` or `{rating:null, joke_score}`. |
| 37 | POST | `/api/v1/jokes/{pk}/react/` | `@action react` (IsAuthenticated) | auth | default | `{"reaction": "lol"|"crying"|"hmm"|"eyeroll"}` (`JokeReaction.REACTION_CHOICES`) | Same reaction → toggle off (`my_reaction:null`); different → switch; none → create. `200 {my_reaction, counts:{lol,crying,hmm,eyeroll}}`. Invalid → `400 {"error":...}`. |
| 38 | GET | `/api/v1/jokes/{pk}/reactions/` | `@action reactions` | anon | default | — | `{my_reaction (null when anon), counts{}}`. |
| 39 | POST | `/api/v1/jokes/{pk}/share/` | `@action share` (AllowAny via `get_permissions`) | anon | default | `{"platform": "copy"|"twitter"|"facebook"|"whatsapp"|"other"}` (unknown → `other`) | Creates `ShareEvent` (user nullable). `201 {status:"recorded", share_url:"<backend>/jokes/{pk}/share/", joke_id}`. |
| 40 | POST | `/api/v1/jokes/{pk}/reveal/` | `JokeRevealView` (explicit path, `views.py:647`) | anon | default | — | Authenticated caller → `204` no-op (their ledger is `JokeView`). Anonymous: joke must be visible in allowed tiers (else 404); if not already consumed and not over cap, appends to the cookie ledger; returns `200 {limit, used, remaining, over, reset_at}`. |

---

## 5. Creator authoring — media upload, submissions, drafts

Source: `jokes/views.py:1436-1811`, `jokes/serializers.py:766-991`, `jokes/submission_rules.py`.

| # | Method | Path | View | Auth | Throttle | Request | Response / behavior |
|---|---|---|---|---|---|---|---|
| 41 | POST | `/api/v1/media/uploads/` | `MediaUploadView` (`MultiPartParser, FormParser`) | auth | `ScopedRateThrottle` `media-upload` 30/hour (replaces defaults) | multipart `file` (required), `kind` ∈ `image|video|audio` (default `image`) | `.gif` (by content-type or extension) always goes through the video pipeline regardless of `kind`. Image: Pillow normalize → webp, SafeSearch `screen_image` (blocked → `422 {"file":["This image was rejected by automated content screening."]}`), pHash matcher hit → `422 {"file":["This image cannot be uploaded."]}`. Video/GIF: ffmpeg → mp4 + poster.jpg, poster+sample frames screened (`422 ... "This clip was rejected..."`), hash hit `422`. Audio: → m4a, no screening. `MediaValidationError` → `400 {field:[...]}`; `MediaBusyError` → `429` + `Retry-After: 30`. Bad `kind` → `400 {"kind":["Unsupported kind."]}`; no file → `400 {"file":["This field is required."]}`. Success `201 MediaAssetSerializer` `{id(uuid), kind, url, poster_url, width, height, duration_ms, is_gif, created_at}`. Side effects: sweeps caller's orphan assets >24h old, `purge_lapsed_quarantine()`, audit `media_upload`. |
| 42 | POST | `/api/v1/jokes/submit/` | `JokeSubmitView` (`CreateAPIView`, `JokeSubmissionCreateSerializer`) | auth | default | `{format(slug, req), age_rating(slug, req), setup?, punchline?, text?, lines?(JSON), tones[]/categories[] (slugs), context_tags[]/themes[] (slugs), culture_tags[], source?, language?(code), media_asset_ids?[uuid]}` | Full per-format validation (`validate_per_format`) — 400 on rule failures; `media_asset_ids` must be caller-owned & unique (`400 {"media_asset_ids":...}`). Creates `JokeSubmission(status='pending')`. `201 {id, status:"pending", created_at}`. Backfills `text` from setup+punchline / lines. |
| 43 | GET | `/api/v1/jokes/my-drafts/` | `JokeDraftListView` (`ListCreateAPIView`) | auth | default | `page` | Paginated (10/page — `?page_size=100` sent by the frontend is **ignored**) `JokeSubmissionListSerializer`: `{id,text,setup,punchline,lines,format(slug),status,tones[names],age_rating(slug),context_tags[slugs],culture_tags[slugs],categories,themes,last_edited_at,created_at,likes (published only),rejection_reason,media[]}`; quarantined assets emit `url:null,poster_url:null`. All statuses (draft/pending/published/rejected) of the caller. |
| 44 | POST | `/api/v1/jokes/my-drafts/` | same | auth | default | `{format (slug, required), age_rating? (slug)}` | Creates a minimal `status='draft'` submission; no content validation. Defaults: `age_rating` = lowest `min_age`, `language` = `en` (or first). Unknown format/age rating → 400; missing lookup rows → `503`. `201` list-shape body. |
| 45 | GET | `/api/v1/jokes/my-drafts/{pk}/` | `JokeDraftDetailView` (`RetrieveUpdateDestroyAPIView`) | auth (owner-scoped queryset → 404 for others) | default | — | List-shape body. |
| 46 | PATCH | `/api/v1/jokes/my-drafts/{pk}/` | same | auth | default | Partial `JokeSubmissionCreateSerializer` fields | Only when `status in ('draft','rejected')` else `400 {"detail":"Can only edit drafts or rejected submissions."}`. Context `skip_format_validation=True` → incomplete autosaves persist (200). `media_asset_ids` omitted → attachments untouched; present → replaced. |
| 47 | PUT | `/api/v1/jokes/my-drafts/{pk}/` | same | auth | default | — | Routed by the generic view but `get_serializer_class` only switches on PATCH, so PUT uses the read serializer (no writable fields) → effectively a no-op 200 after the status check. Docstring says GET/PATCH/DELETE only. |
| 48 | DELETE | `/api/v1/jokes/my-drafts/{pk}/` | same | auth | default | — | `204`; deletes attached assets (files too) that are no longer linked anywhere. |
| 49 | POST | `/api/v1/jokes/my-drafts/{pk}/submit/` | `JokeDraftSubmitView` | auth | default | — | 404 if not owner; `400` if status not draft/rejected; runs `validate_per_format` (errors → `400 {field:[...]}`); sets `status='pending'`; `200 {id, status:"pending"}`. |

---

## 6. Lookup catalogs (router, `ReadOnlyModelViewSet`, all AllowAny by default)

Source: `jokes/views.py:691-726, 2664-2673`.

| # | Method | Path | ViewSet | Response |
|---|---|---|---|---|
| 50/51 | GET | `/api/v1/formats/`, `/api/v1/formats/{pk}/` | `FormatViewSet` | Paginated `{id,name,slug,description,...required_fields[],forbidden_fields[]}` ordered by name. |
| 52/53 | GET | `/api/v1/age-ratings/`, `/{pk}/` | `AgeRatingViewSet` | `{id,name,slug,description,min_age}` ordered by `min_age,name`. |
| 54/55 | GET | `/api/v1/tones/`, `/{pk}/` | `ToneViewSet` | `{id,name,slug,description}`. |
| 56/57 | GET | `/api/v1/context-tags/`, `/{pk}/` | `ContextTagViewSet` | `{id,name,slug,description}`. |
| 58/59 | GET | `/api/v1/culture-tags/`, `/{pk}/` | `CultureTagViewSet` | `{id,name,slug,description}`. |
| 60/61 | GET | `/api/v1/languages/`, `/{pk}/` | `LanguageViewSet` | `{id,code,name}`. |
| 62/63 | GET | `/api/v1/vibes/`, `/api/v1/vibes/{slug}/` | `VibeViewSet` (`lookup_field='slug'`, `pagination_class=None`) | Unpaginated JSON array of active vibes (`VibeSerializer`: slug,label,icon,...). |

All six lookup lists are paginated at 10 (default) — callers wanting the full catalog must page.

---

## 7. Preferences, vibes, onboarding

Source: `jokes/views.py:731-790, 2084-2150, 2676-2719`.

| # | Method | Path | View | Auth | Request | Response / behavior |
|---|---|---|---|---|---|---|
| 64 | GET | `/api/v1/preferences/me/` | `UserPreferenceViewSet.me` | auth | — | `UserPreferenceSerializer`: `{id, preferred_tones[], preferred_contexts[], preferred_categories[](alias), preferred_themes[](alias), preferred_age_rating{}, preferred_language{}, notification_enabled, notification_time, notification_days, streak_saver_enabled, onboarding_completed, created_at, updated_at}`. |
| 65 | PATCH | `/api/v1/preferences/me/` | same | auth | `UserPreferenceUpdateSerializer`: PK ids for `preferred_tones/preferred_contexts/preferred_categories/preferred_themes/preferred_age_rating/preferred_language`, `notification_enabled`, `notification_time`, `notification_days`, ... | Returns the read shape. Alias fields collapse to canonical. |
| 66 | POST | `/api/v1/preferences/complete-onboarding/` | `UserPreferenceViewSet.complete_onboarding` | auth | — | `200 {status:"onboarding_completed", onboarding_completed:true}`. |
| 67 | GET | `/api/v1/users/me/preferences/` | `UserPreferencesView` | auth | — | Composite: `{humor_types:[tone slugs], notifications:{daily_joke,trending_alerts,collection_updates,email_digest}, privacy:{public_profile,show_activity,share_analytics}, theme}`. |
| 68 | PUT / PATCH | `/api/v1/users/me/preferences/` | same | auth | any subset of `humor_types[]`, `notifications{}`, `privacy{}`, `theme` | Applies present keys (no validation of `theme` value), returns the GET shape. |
| 69 | GET | `/api/v1/users/me/vibes/` | `UserVibesView` | auth | — | Array of `{vibe{...}, weight, created_at}` newest first. |
| 70 | PUT | `/api/v1/users/me/vibes/` | same | auth | `{"slugs": [3..12 slugs]}` | Replaces selection atomically; unknown/inactive slugs → `400 {"slugs":["Unknown or inactive vibes: [...]"]}`; <3 or >12 → 400. Returns array as GET. |

---

## 8. Daily ritual — daily jokes, mystery box, streak, packs, status, taste profile

Source: `jokes/views.py:1142-1341, 2722-3284`.

| # | Method | Path | View | Auth | Request | Response / behavior |
|---|---|---|---|---|---|---|
| 71 | GET | `/api/v1/daily-jokes/today/` | `DailyJokeViewSet.today` (AllowAny via `get_permissions`) | anon | — | Anonymous: random tier_1 joke → `{joke:{JokeSerializer WITHOUT paywall context → never locked}, date}`; 404 if none. Authenticated: today's `DailyJoke` (regenerated if missing or joke removed) via `get_personalized_joke(..., allowed_tiers)`, `update_or_create`, marks `delivered_at` on first access; `{id, joke{}, date, delivered_at, created_at, issue_label:"Vol. I · No. 042"}`. Daily joke is exempt from the paywall by design (no paywall context). |
| 72 | GET | `/api/v1/daily-jokes/tomorrow/` | `.tomorrow` (IsAuthenticated) | auth | — | Lazily creates tomorrow's row; `{date, issue_label, preview (first 12 words + …), format (slug)}`; 404 if no joke. |
| 73 | GET | `/api/v1/daily-jokes/history/` | `.history` | auth | — | Unpaginated array of `DailyJokeSerializer` for the caller within a rolling window of `daily_joke_history_days` entitlement (free 30). Filters `joke__is_removed=False`; **no content-tier filter and no paywall context** (full punchlines). Docstring in the class header still says "last 30 days". |
| 74 | GET | `/api/v1/mystery-box/status/` | `MysteryBoxStatusView` | auth | — | `{rolls_used_today, rolls_remaining_today, max_per_day}` (`mystery_box_rolls_per_day` entitlement, default 3). |
| 75 | POST | `/api/v1/mystery-box/roll/` | `MysteryBoxRollView` | auth | — | Cap reached → `429 {detail, rolls_used_today, rolls_remaining_today:0, max_per_day}`. Pool = union of caller's vibes' recipes (fallback: all jokes) ∩ allowed tiers − blocked creators − rolled today − already saved. Empty → `404`. Success `200 {joke:{JokeSerializer with paywall ctx}, rolls_remaining_today, source_vibe{}|null}`; creates `MysteryBoxRoll`. |
| 76 | GET | `/api/v1/users/me/streak/` | `StreakView` | auth | — | Reconciles gaps/freeze refresh (`_reconcile_streak`) then `StreakSerializer`: `{current_count,longest_count,last_active_date,freeze_days_available,freezes_used_total,started_at,last_14_days:[{date,status}],streak_at_risk_today}` (`at_risk` = not read today AND hour ≥ 20 UTC). |
| 77 | POST | `/api/v1/users/me/streak/freeze/` | `StreakFreezeView` | auth | — | `400` if `freeze_days_available<=0` or today already `read`; else marks today `frozen`, decrements freezes (2/month), sets `last_active_date=today`; returns streak. |
| 78 | POST | `/api/v1/users/me/streak/freeze/remove/` | `StreakFreezeRemoveView` | auth | — | `400 {"detail":"No freeze to remove for today."}` if none; else deletes today's frozen day, refunds freeze. |
| 79 | GET | `/api/v1/packs/` | `JokePackViewSet.list` (AllowAny) | anon | `page` | Paginated `JokePackListSerializer` `{slug,title,subtitle,description,cover_color,is_featured,joke_count,publish_at,expires_at,user_progress{}|null}` for `is_published=True` within publish/expiry window. |
| 80 | GET | `/api/v1/packs/{slug}/` | `.retrieve` | anon | — | `JokePackDetailSerializer` = list fields + `jokes:[{order, joke:{JokeSerializer}}]` filtered by allowed tiers and `is_removed=False`; paywall context applied. |
| 81 | GET | `/api/v1/packs/featured/` | `@action featured` | anon | — | First `is_featured` pack (detail shape) or `404 {"detail":"No featured pack at the moment."}`. |
| 82 | POST | `/api/v1/packs/{slug}/progress/` | `JokePackProgressView` | auth | `{"entry_order": int ≥ 0}` | 404 if pack not published; `entry_order >= max order` (and max>0) → sets `completed_at`; lower → clears it. `200 {last_read_entry, completed_at, is_complete}`. |
| 83 | GET | `/api/v1/users/me/packs/in-progress/` | `JokePackInProgressView` | auth | — | Array of list-shape packs with `completed_at IS NULL AND last_read_entry > 0`, published only. |
| 84 | GET | `/api/v1/users/me/today-status/` | `DailyRitualStatusView` | auth | — | `{daily_joke_due, has_read_today, today_is_a_notification_day, now_past_notification_time}` from `UserPreference.notification_days/time/enabled` + `JokeView` today. |
| 85 | GET | `/api/v1/users/me/taste-profile/` | `TasteProfileView` | auth | `period` = `month`(default, 30d) / `week`(7d) / `all` | `{period, jokes_read, jokes_saved, peak_read_hour, top_vibe{}|null, top_themes[{label,count}], top_categories[], top_formats[], daily_reads_28d[28 ints]}`. |
| 86 | GET | `/api/v1/users/me/recently-viewed/` | `RecentlyViewedView` | auth | `limit` (default 20, max 100; non-int → 20) | Array of `{joke:{JokeSerializer w/ paywall ctx}, source, revealed_punchline, viewed_at}` newest first; tier + `is_removed` filtered. |

---

## 9. Library — collections, saved jokes, favorites

Source: `jokes/views.py:936-1139, 1814-1919`, `jokes/serializers.py:549-683, 736-763`.

| # | Method | Path | View | Auth | Request | Response / behavior |
|---|---|---|---|---|---|---|
| 87 | GET | `/api/v1/collections/` | `CollectionViewSet.list` (`ModelViewSet`, IsAuthenticated) | auth | `page` | Paginated `{id,name,description,is_default,joke_count,created_at,updated_at}` for the caller. |
| 88 | POST | `/api/v1/collections/` | `.create` | auth | `{name, description?}` | Name unique per user (`400 {"name":["You already have a collection with this name."]}`); `201` (create-serializer shape `{name, description}`). |
| 89 | GET | `/api/v1/collections/{pk}/` | `.retrieve` | auth | — | Read shape; 404 if not owner. |
| 90 | PUT / PATCH | `/api/v1/collections/{pk}/` | `.update/.partial_update` | auth | `{name?, description?}` | Same uniqueness rule. |
| 91 | DELETE | `/api/v1/collections/{pk}/` | `.destroy` | auth | — | `400 {"detail":"Cannot delete the default Favorites collection."}` when `is_default`; else `204`. |
| 92 | GET | `/api/v1/collections/{pk}/jokes/` | `@action jokes` | auth | `page` | Paginated `SavedJokeSerializer` (`{id, joke{JokeSerializer}, collection, note, created_at,...}`) filtered to allowed tiers & `is_removed=False`; paywall context applied. |
| 93 | GET | `/api/v1/collections/trending/` | `@action trending` (AllowAny) | anon | — | `{results:[{id,name,joke_count,saves_this_week,creator_name}]}` top 10 public collections with saves in last 7 days. |
| 94 | GET | `/api/v1/saved-jokes/` | `SavedJokeViewSet.list` | auth | `ordering` ∈ `-saved_at`(default)/`saved_at`/`-created_at`/`created_at`, `page` | Paginated `SavedJokeSerializer`; filters `joke__is_removed=False` only — **no content-tier filter on the plain list** (the `search` action and Favorites do filter by tier). Paywall context applied. |
| 95 | POST | `/api/v1/saved-jokes/` | `.create` (`SavedJokeCreateSerializer`) | auth | `{joke (pk), collection? (pk, must be caller's), note?}` | Duplicate (user,joke,collection) → `400 {"joke":"This joke is already saved in this collection."|"...without a collection."}`; foreign collection → `400 {"collection":[...]}`. `201 {joke, collection, note}`. |
| 96 | DELETE | `/api/v1/saved-jokes/{pk}/` | `.destroy` | auth | — | `204`; 404 if not caller's. |
| 97 | GET | `/api/v1/saved-jokes/search/` | `@action search` | auth | `q` (required → `400 {"detail":"Search query \"q\" is required."}`) | Paginated saved jokes whose joke matches `Joke.objects.search(q, allowed_tiers)`. |
| 98 | GET | `/api/v1/favorites/` | `FavoriteViewSet.list` | auth | `tones` (csv slugs), `ordering` ∈ `-favorited_at`(default)/`favorited_at`/`-popularity`, `page` | Paginated `{id, joke{JokeSerializer}, favorited_at}`; tier + `is_removed` filtered; paywall ctx. |
| 99 | POST | `/api/v1/favorites/` | `.create` | auth | `{joke (pk)}` | `201` full `FavoriteSerializer` shape (not just the id). Duplicate → 400 (model unique). |
| 100 | DELETE | `/api/v1/favorites/{pk}/` | `.destroy` | auth | — | `204`. |
| 101 | GET | `/api/v1/favorites/stats/` | `@action stats` | auth | — | `{total_count, top_tone (name|null), this_week_count}`. |

---

## 10. User self-service — profile, activity, achievements, account, GDPR, blocks, appeals

Source: `jokes/views.py:1922-2081, 2275-2661`.

| # | Method | Path | View | Auth | Throttle | Request | Response / behavior |
|---|---|---|---|---|---|---|---|
| 102 | GET | `/api/v1/users/me/profile/` | `UserProfileView` | auth | default | — | `{name, username, display_name, handle, email, bio, avatar_url, member_since, is_premium, stats:{jokes_saved,jokes_shared,collections,days_active}, humor_dna:[{type,percentage}] (top 4 tones)}`. This is the only self-surface exposing `email` besides `/auth/user/`. |
| 103 | PATCH | `/api/v1/users/me/profile/` | same | auth | default | `{first_name?, last_name?, bio?, display_name? (truncated to 50), handle?}` | `handle` normalized; must match 3-30 `[a-z0-9_]` (`400 {"handle":[...]}`), unique (`400 {"handle":["That handle is already taken."]}`), `""` clears it. Returns GET shape. No avatar upload endpoint exists. |
| 104 | GET | `/api/v1/users/me/activity/` | `UserActivityView` | auth | default | `limit` (default 10; non-int → 500 `ValueError` unhandled) | `{results:[{id:"rating_N"|"save_N"|"fav_N"|"share_N", type:"like"|"dislike"|"save"|"share", description, created_at}]}` merged & sorted desc. |
| 105 | GET | `/api/v1/users/me/achievements/` | `UserAchievementsView` | auth | default | — | `{results:[{id(slug),title,description,icon,unlocked,unlocked_at}]}` for every `Achievement`. |
| 106 | DELETE | `/api/v1/users/me/` | `UserAccountDeleteView` | auth | default | password accounts: `{password}`; OAuth/unusable-password accounts: `{confirm:"DELETE"}` | Missing/incorrect → `400 {"password":[...]}` / `400 {"confirm":["Type DELETE to confirm account deletion."]}`. Atomic: blacklist outstanding refresh tokens, delete owned `MediaAsset` files, delete avatar file, purge `EmailMessageLog`/`EmailVerification`, mark caller's media-format jokes `is_removed`, cascade-delete user. Audit `account_delete` with hashed email. `204`. |
| 107 | GET | `/api/v1/users/me/data-export/` | `DataExportView` | auth | default | — | `application/zip` attachment `jokes-for-data-export.zip` containing `jokes-for-data-export.json` (account, profile, preferences, collections, saved_jokes/favorites excluding removed jokes, ratings, reactions, daily_jokes, views[:5000], streak, streak_days, submissions, media_assets (quarantined → `url:null,status:"quarantined"`), reports_filed, blocks, achievements, vibes, pack_progress, mystery_rolls, share_events, email_logs). Audit `data_export`. |
| 108 | POST | `/api/v1/reports/` | `ContentReportView` (`CreateAPIView`) | auth | default | `{joke (pk), reason ∈ offensive|inappropriate|spam|copyright|harassment|other, description?}` | Existing **pending** report by same reporter for same joke → `200` (existing); else `201 {joke, reason, description}`. Audit `content_report`. |
| 109 | POST | `/api/v1/appeals/` | `AppealCreateView` | auth | `ScopedRateThrottle` `appeals` 10/day (replaces defaults) | `{joke_id | submission_id (exactly one), reason_text}` | Both/neither → 400. Target missing or not owned → **404** (indistinguishable). Joke not removed / `removed_at` null / >14-day window / duplicate pending → 400 with message. Submission not rejected / window lapsed / duplicate → 400. Race duplicate (DB partial unique index) → 400 same message. `201 AppealSerializer {id, action_type ("takedown"|"rejection"), status, reason_text, target_type, target_id, target_preview (60 chars), created_at, resolved_at, resolution_note}`. Side effects: audit `appeal_filed`, `purge_lapsed_quarantine()`. |
| 110 | GET | `/api/v1/users/me/appeals/` | `MyAppealsView` (`ListAPIView`) | auth | default | `page` | Paginated `AppealSerializer` for the caller. |
| 111 | POST | `/api/v1/users/{user_id}/block/` | `UserBlockView` | auth | default | — | Self → `400 {"detail":"Cannot block yourself."}`; unknown → 404. `get_or_create` block, deletes follows in both directions, audit `block`. `201 {"status":"blocked"}` (also 201 when already blocked). |
| 112 | DELETE | `/api/v1/users/{user_id}/block/` | same | auth | default | — | Idempotent delete, audit `unblock`, `204`. |
| 113 | GET | `/api/v1/users/me/blocks/` | `MyBlocksView` | auth | default | — | `{results:[PublicUserSerializer {id,name,username,avatar_url}]}` (unpaginated). |

---

## 11. Discovery / trending lookups (all AllowAny, default throttles)

Source: `jokes/views.py:2153-2272`.

| # | Method | Path | View | Request | Response |
|---|---|---|---|---|---|
| 114 | GET | `/api/v1/tags/trending/` | `TagsTrendingView` | — | `{results:[{name,slug,count,growth_percent:0}]}` top 10 tones by likes in last 7 days. No tier/moderation filter. |
| 115 | GET | `/api/v1/tags/rising/` | `TagsRisingView` | — | `{results:[{name,slug,growth_percent}]}` top 10 context tags by week-over-week like growth (N+1 loop over all tags). |
| 116 | GET | `/api/v1/users/top-jokesters/` | `TopJokestersView` | `period` ∈ `all_time`(default)/`week`/`month`/other(365d), `limit` (default 5; non-int → 500) | `{results:[{id,name,username,avatar_url:null,punchline_count,rank,top_vibes:[{slug,label,icon}]}]}` users ranked by published submissions. |
| 117 | GET | `/api/v1/themes/popular/` | `ThemesPopularView` | — | `{results:["Name", ...]}` top 10 context tag names by joke count. |

---

## 12. Telemetry

Source: `jokes/views.py:3287-3396`.

| # | Method | Path | View | Auth | Request | Response / behavior |
|---|---|---|---|---|---|---|
| 118 | POST | `/api/v1/telemetry/events` (**no trailing slash**) | `TelemetryIngestView` | auth | `{"events":[{joke:int, type:"impression"|"reveal"|"dwell"|"watch", source?:str(≤16), value?:ms (dwell), scroll_pct?:0-100, watch_ms?:ms (watch), watch_pct?:0-100}]}` | Batch capped at 50; non-list → `[]`. Unknown joke id / bad type / non-dict → skipped silently. `impression` → `get_or_create JokeImpression` per (user,joke,day). `reveal` → sets `revealed_punchline=True` on latest `JokeView` or creates one (this **also feeds the paywall ledger**). `dwell` → clamp `value` to [0, 600000] ms, drop < 500 ms, create `JokeDwell`. `watch` → same clamps on `watch_ms`, create `JokeWatch`. Any per-event exception swallowed. Always `202 {"accepted": N}`. |

---

## 13. Creators & follows

Source: `creator_insights/urls.py`, `creator_insights/views.py`, `follows/urls.py`, `follows/user_urls.py`, `follows/views.py`, `billing/views.py:191-221`.

| # | Method | Path | View | Auth | Throttle | Request | Response / behavior |
|---|---|---|---|---|---|---|---|
| 119 | GET | `/api/v1/creators/me/insights/` | `CreatorInsightsView` | creator (`IsAuthenticated, IsCreator, HasFeature('creator_analytics')` — feature defaults True for all plans) | `CreatorInsightsThrottle` (scope `creator_insights` 120/hour, user-keyed; replaces defaults) | `period` ∈ `month`(default)/`week`/`all` | `CreatorInsightsSerializer` shape: `{period, is_creator, overview:{published_jokes, reach, views, impressions, unique_reach, open_rate, payoff_rate, avg_read_seconds, read_rate, completion_rate, reactions, favorites, saves, shares, peak_read_hour, daily_reach_28d[], followers, follower_growth_28d[]}, reactions_breakdown[], shares_breakdown[], source_mix[], top_jokes[{id,text,views,impressions,reactions,saves,shares,payoff_rate,avg_read_seconds,read_rate,avg_watch_seconds,watch_completion_rate}], audience:{top_themes,top_categories,top_formats}, suggestions[{kind,title,detail,data}]}`. Non-creator → `403 {"detail":"You must have at least one published joke to view creator insights."}`. |
| 120 | GET | `/api/v1/creators/{creator_id}/profile/` | `CreatorProfileView` | anon | default | `page` | Unknown user → 404; blocked pair (auth viewer) → 404; zero jokes visible in the viewer's allowed tiers → `404 {"detail":"Creator not found or has no published jokes."}`. `200 {id, display_name, handle, published_jokes, follower_count, is_following (null when anon/self), jokes:[JokeListSerializer {id,text(≤100 chars + "..."),format(slug),age_rating(slug),tones[slugs],categories[slugs],share_image_url,media[{kind,width,height}] (dims only, always)}], jokes_pagination:{count,next,previous}}` (10 jokes/page). No `is_locked` field on this surface. |
| 121 | GET | `/api/v1/creators/{creator_id}/tips/summary/` | `billing.views.CreatorTipsSummaryView` | anon | default | — | `{count, total_cents}` of `status='succeeded'` tips. Unknown creator → `{0,0}` (no 404). |
| 122 | POST | `/api/v1/follows/{creator_id}/` | `FollowView.post` | auth | default | — | Unknown user → 404; self-follow → `400 {"detail":"You cannot follow yourself."}`; blocked pair → `400 {"detail":"You cannot follow this user."}`. `201` (new) or `200` (already) `{is_following:true, follower_count}`; new follow triggers an inbox notification to the creator. |
| 123 | DELETE | `/api/v1/follows/{creator_id}/` | `FollowView.delete` | auth | default | — | Idempotent, `204`. |
| 124 | GET | `/api/v1/follows/{creator_id}/status/` | `FollowStatusView` | auth | default | — | `{is_following, follower_count}`. |
| 125 | GET | `/api/v1/follows/{creator_id}/followers/` | `FollowersListView` | auth | default | `page` | Paginated `PublicUserSerializer` (10/page) excluding users hidden by block relations. |
| 126 | GET | `/api/v1/users/me/following/` | `MyFollowingView` | auth | default | `page` | Paginated `PublicUserSerializer` of creators the caller follows. |
| 127 | GET | `/api/v1/users/me/tips/` | `billing.views.MyTipsView` | auth | default | `page` | Paginated (10) `TipSerializer {id, creator, creator_name, joke, amount_cents, currency, status, created_at, completed_at}` newest first. |

---

## 14. Billing — subscriptions, entitlements, tips, Stripe webhook

Source: `billing/urls.py`, `billing/tip_urls.py`, `billing/views.py`, `billing/entitlements.py`. Note: billing paths have **no trailing slash** (`checkout-session`, `plans`, ...) while `tips/checkout/` has one.

| # | Method | Path | View | Auth | Throttle | Request | Response / behavior |
|---|---|---|---|---|---|---|---|
| 128 | GET | `/api/v1/billing/plans` | `PlansView` | anon | default | — | Array `PlanPublicSerializer {slug,name,description,interval,amount_cents,currency,amount_display,features{},limits{},sort_order}` for `is_active & is_public` plans. |
| 129 | POST | `/api/v1/billing/checkout-session` | `CheckoutSessionView` | auth | default | `{plan_slug}` | Stripe disabled → `503 {"detail":"Billing is not configured.","code":"billing_unavailable"}`. Unknown/inactive plan → 404. Plan without `stripe_price_id` → `422`. Already has a live paid subscription → `409 {"detail":..., "code":"active_subscription", "portal_url"?}`. Success `200 {"url": <checkout url>}`; Stripe error → `502 {"detail":"Checkout error."}`. |
| 130 | POST | `/api/v1/billing/portal-session` | `PortalSessionView` | auth | default | — | No subscription / no `stripe_customer_id` → `404 {"detail":"No billing account found."}`; disabled → 503; `200 {"url"}`; error → 502. |
| 131 | POST | `/api/v1/billing/webhook` | `StripeWebhookView` (`authentication_classes=[]`, `@csrf_exempt`) | signature | **default AnonRateThrottle 100/hour by IP still applies** (no `throttle_classes` override) | raw Stripe event body + `Stripe-Signature` header | Disabled → `200 {"detail":"billing_dormant"}`. Bad signature → `400 {"detail":"Invalid signature."}`; other construct error → 400; handler exception → `500 {"detail":"Handler error."}`; success `200 {"received": true}`. Idempotent on event id (`billing/webhooks.py`). |
| 132 | GET | `/api/v1/billing/my-subscription` | `MySubscriptionView` | auth | default | — | `MySubscriptionSerializer {plan_slug, plan_name, status, current_period_end, cancel_at_period_end, stripe_customer_id}`; no row → `{plan_slug:"free"|default plan, plan_name, status:"free", current_period_end:null, cancel_at_period_end:false, stripe_customer_id:""}`. |
| 133 | GET | `/api/v1/billing/entitlements` | `EntitlementsView` | auth | default | — | `{plan, features:{creator_analytics, daily_joke_preview, mature_content_addon}, limits:{mystery_box_rolls_per_day, submissions_per_day, daily_jokes_per_day, daily_joke_history_days, free_joke_reads_per_day, ...}}` resolved from effective plan (`null` limit = unlimited). |
| 134 | POST | `/api/v1/tips/checkout/` | `TipCheckoutView` | auth | `ScopedRateThrottle` `tips-checkout` 30/hour (replaces defaults) | `{amount_cents ∈ {100,300,500,1000}, creator_id, joke_id?}` | Disabled → 503. Non-int amount / not a tier → `400 code:"invalid_amount"`; missing creator → `400 code:"creator_required"`; unknown creator → 404; creator has no `Joke.creator` rows → `400 code:"not_a_creator"`; self → `400 code:"self_tip"`; bad joke → `400`; joke not by creator → `400 code:"joke_creator_mismatch"`. Success `200 {checkout_url, tip_id}` (a `Tip` row is created pending); error → 502. |

---

## 15. In-app inbox notifications

Source: `inbox/urls.py`, `inbox/views.py`, `inbox/serializers.py`. Mounted at `api/v1/notifications/`.

| # | Method | Path | View | Auth | Request | Response |
|---|---|---|---|---|---|---|
| 135 | GET | `/api/v1/notifications/` | `NotificationListView` | auth | `page` | Paginated **20/page** `{id, verb, read, created_at, data{}, actor{id,name,username}|null, joke{id,preview(60)}|null}` newest first. |
| 136 | GET | `/api/v1/notifications/unread-count/` | `UnreadCountView` | auth | — | `{count}`. |
| 137 | POST | `/api/v1/notifications/mark-read/` | `MarkAllReadView` | auth | — | Marks all unread as read; `{marked: N}`. |

---

## 16. Totals

- **Distinct URL routes: 121** (numbered #1–#137 above but several numbers cover paired list/detail lookup routes; the unique-route count = 9 infra/docs + 17 auth + 2 email/internal + 11 jokes + 6 authoring (my-drafts collapsed per path) + 14 lookups + 6 preferences/vibes + 16 daily-ritual + 12 library + 10 user self-service + 4 discovery + 1 telemetry + 8 creators/follows + 7 billing + 3 inbox = 126 rows; collapsing rows that share a path with different methods (#45-48 → 1, #64/65 → 1, #67/68 → 1, #89-91 → 1, #94/95 → 1, #98/99 → 1, #102/103 → 1, #111/112 → 1, #122/123 → 1, #27/28 → 1, #69/70 → 1) yields **121 distinct routes**, plus the `/admin/` subtree and DefaultRouter format-suffix duplicates.
- **Method × path operations: ~141** (routes with multiple methods: `/auth/user/` ×3, `/users/me/preferences/` ×3, `/jokes/my-drafts/{pk}/` ×4, `/collections/{pk}/` ×4, and 2-method routes: email/unsubscribe, jokes/my-drafts/, preferences/me/, users/me/vibes/, collections/, saved-jokes/, favorites/, users/me/profile/, users/{id}/block/, follows/{id}/).
- **Router ViewSets (14 registered):** jokes, formats, age-ratings, tones, context-tags, culture-tags, languages, preferences, vibes, packs, collections, saved-jokes, daily-jokes, favorites.
- **Router `@action`s (18):** `JokeViewSet` random, daily_reads(`daily-reads`), rate, get_rating(`my-rating`), react, reactions, trending, share; `UserPreferenceViewSet` me (GET/PATCH), complete_onboarding(`complete-onboarding`); `CollectionViewSet` jokes, trending; `SavedJokeViewSet` search; `DailyJokeViewSet` today, tomorrow, history; `FavoriteViewSet` stats; `JokePackViewSet` featured.

---

## 17. Endpoint-by-behavior matrix (paywall / tier / moderation / pagination)

| Behavior | Endpoints where applied | Endpoints where NOT applied (notable) |
|---|---|---|
| `paywall_state` context → `is_locked` stripping | jokes list/retrieve/random/trending; collections/{id}/jokes; saved-jokes list+search; favorites list+create response; packs list/retrieve/featured (embedded jokes); mystery-box/roll; users/me/recently-viewed | daily-jokes/today & tomorrow & history (by design — daily joke exempt); creators/{id}/profile (uses `JokeListSerializer`: truncated `text`, dims-only media, no `is_locked`) |
| `allowed_tiers` content-tier gate | jokes list/retrieve/random/trending/reveal; saved-jokes search; collections/{id}/jokes; favorites; recently-viewed; daily today/tomorrow (selection); mystery-box pool; packs detail/featured (embedded jokes); creators/{id}/profile; share page (redirect shell); sitemap (tier_1 only) | saved-jokes plain list (`is_removed` only); daily-jokes/history; tags/*, themes/popular, top-jokesters (aggregate only) |
| Block-based hiding | jokes list/retrieve/random/reveal; mystery pool; creator profile (404); followers/following lists; follow POST (400) | trending, packs, collections/trending |
| `is_removed` explicit gate on FK traversals | saved-jokes, favorites, collections/{id}/jokes, recently-viewed, daily today/history, pack detail, data-export | — |
| Pagination 10/page | jokes, lookups, my-drafts, collections, saved-jokes, favorites, appeals, packs, creator profile jokes, followers, following, tips | notifications (20/page); vibes, daily history, blocks, recently-viewed (`limit`), activity (`limit`), in-progress packs, top-jokesters (`limit`) are unpaginated |

---

## 18. Docs vs code disagreements & observations

1. **`page_size` query param is not supported.** Frontend `src/features/create/api.ts:25` requests `/jokes/my-drafts/?page_size=100` and `src/lib/api.ts:234` types a `page_size` param; the backend never defines `page_size_query_param`, so every paginated list is capped at 10/page (`settings.py:301-302`). A creator with >10 drafts sees only page 1 in the editor list unless the frontend pages.
2. **Stripe webhook is throttled.** `StripeWebhookView` clears auth but not throttles; DRF `AnonRateThrottle` 100/hour keyed by client IP applies (`billing/views.py:238-241` vs `settings.py:303-308`). Bursts >100 events/hour from a single Stripe egress IP would get 429 and be retried by Stripe.
3. **`throttle_scope='dj_rest_auth'` on login/register/password views is inert** (no `ScopedRateThrottle` in defaults, no rate defined) — login brute-force protection is only the 100/hour anon IP throttle.
4. `DailyJokeViewSet` class docstring (`views.py:1147-1149`) says history = "last 30 days (auth required)"; code uses the `daily_joke_history_days` entitlement (30/90/365) — the `@extend_schema` description is correct.
5. `JokeDraftDetailView` docstring says GET/PATCH/DELETE; PUT is also routed (generic `RetrieveUpdateDestroyAPIView`) and silently uses the read serializer.
6. Root `urls.py:57-59` comment says `creators/{id}/tips/summary` and `users/me/tips` "land ... in a later wave task" — they are already wired (`creator_insights/urls.py:9`, `follows/user_urls.py:9`).
7. dj-rest-auth registration sub-routes (#23–#26) exist but belong to allauth's link-based verification, which is disabled (`ACCOUNT_EMAIL_VERIFICATION='none'`); the two `TemplateView` routes 500 on GET. They are dead surface, harmless but present in the OpenAPI schema.
8. `.planning/codebase/*.md` contains no endpoint-level inventory (grep for `api/v1` in ARCHITECTURE.md returned nothing), so there is nothing there to contradict — treat it as non-authoritative for API surface.
9. `UserActivityView` and `TopJokestersView` do `int(request.query_params.get('limit', ...))` without try/except → a non-numeric `limit` yields a 500 rather than 400 (`views.py:2015, 2217`).
10. `JokeListSerializer.get_text` (creator profile) truncates `Joke.text` to 100 chars; for setup-punchline jokes `text` = "setup punchline", so short jokes' punchlines are visible on the public creator profile regardless of the paywall (profile is intentionally outside the paywall, but this is the one anonymous surface that shows payoff text).
11. `SavedJokeViewSet.get_queryset` (`views.py:1049-1066`) filters `is_removed` but not `content_tier`, unlike `FavoriteViewSet`; a user who disabled `show_mature` after saving a tier_2 joke still sees it in `/saved-jokes/` (but not in `/saved-jokes/search/`).
12. No avatar-upload endpoint exists even though `avatar_url` is returned in several places; `top-jokesters` hardcodes `avatar_url: null`.
13. `POST /api/v1/telemetry/events` has no trailing slash while every other jokes route does; `CommonMiddleware` `APPEND_SLASH` would redirect a POST to `.../events/` → 404, so callers must use the exact path (frontend `src/lib/telemetry.ts:60` does).
