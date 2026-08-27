# JokesFor Backend Architecture Map (key: be-architecture)

Repo: `/Users/narekmeloyan/PycharmProjects/JokesForProject` (Django 5.2.17 / DRF 3.16.1 / Postgres via psycopg2 / Cloud Run). All facts below are taken from code; docs are cited only where they agree or disagree with code. Line numbers refer to the current working tree (2026-08-25).

---

## 0. Runtime shape (one sentence)

A single synchronous Django/DRF monolith (gunicorn `--workers 2 --threads 4 --worker-class gthread --timeout 300`, `Dockerfile`), no Celery/cron/workers, Postgres for everything including the DRF throttle cache, Google Cloud Storage for media in prod (filesystem locally), Resend (via django-anymail) for email in prod (console backend locally), Stripe env-gated/dormant, Sentry opt-in by DSN, structured JSON logs to stdout for Cloud Logging.

---

## 1. `JokesForProject/settings.py` in full (664 lines)

### 1.1 Core / env keys
| Setting | Source & default | Notes |
|---|---|---|
| `DEBUG` | `os.getenv('DEBUG','False')` truthy in `('true','1','yes')` (L32) | drives many derived flags below |
| `SECRET_KEY` | `os.getenv('SECRET_KEY')`; if missing: `'django-insecure-dev-only-key'` when DEBUG else `ImproperlyConfigured` (L37-42) | production refuses to boot without it |
| `ALLOWED_HOSTS` | `os.getenv('ALLOWED_HOSTS','localhost,127.0.0.1')` comma-split (L44) | |
| `SITE_ID` | `1` (L83) | allauth |
| `ROOT_URLCONF` | `'JokesForProject.urls'` | |
| `WSGI_APPLICATION` | `'JokesForProject.wsgi.application'` | |
| `DEFAULT_AUTO_FIELD` | `BigAutoField` (L291) | |
| `LANGUAGE_CODE/TIME_ZONE/USE_I18N/USE_TZ` | `en-us` / **`UTC`** / True / True (L212-218) | `TIME_ZONE='UTC'` is load-bearing for paywall/streak day boundaries |
| `AUTH_PASSWORD_VALIDATORS` | 4 stock Django validators (L192-205) | |

`load_dotenv()` is called at import (L22) so a `.env` file is honoured.

### 1.2 `INSTALLED_APPS` (L49-81)
Django contrib: admin, auth, contenttypes, sessions, messages, staticfiles, **sites** (allauth).
Third-party: `rest_framework`, `rest_framework.authtoken` (dj-rest-auth dependency), `rest_framework_simplejwt.token_blacklist`, `dj_rest_auth`, `allauth`, `allauth.account`, `allauth.socialaccount`, `allauth.socialaccount.providers.google`, `dj_rest_auth.registration`, `drf_spectacular`, `corsheaders`, `pgtrigger`, `anymail`.
Local: `jokes`, `notifications`, `creator_insights`, `follows`, `audit`, `billing`, `inbox`.

### 1.3 `MIDDLEWARE` order and purpose (L85-107)
1. `django.middleware.security.SecurityMiddleware` — HSTS/SSL redirect/nosniff.
2. `whitenoise.middleware.WhiteNoiseMiddleware` — serves collected static (admin CSS/JS) from the process; must sit right after Security.
3. `JokesForProject.observability.middleware.RequestContextMiddleware` — binds `request_id` (from `X-Request-ID` or uuid4) + Cloud Trace (`X-Cloud-Trace-Context`) into contextvars, installs a per-request DB `execute_wrapper` counter, binds `user_id` lazily after the view, echoes `X-Request-ID` on the response, tags Sentry; resets all contextvars in `finally`.
4. `JokesForProject.observability.middleware.AccessLogMiddleware` — one structured `jokesfor.access` line per request (method, path, route template, status, latency_ms, masked client IP, user_id, request_id, db_query_count, db_time_ms). Severity: >=500 ERROR, >=400 WARNING, else INFO; `/healthz` and `/readyz` at DEBUG.
5. `SessionMiddleware`
6. `corsheaders.middleware.CorsMiddleware`
7. `CommonMiddleware`
8. `CsrfViewMiddleware`
9. `AuthenticationMiddleware`
10. `allauth.account.middleware.AccountMiddleware`
11. `MessageMiddleware`
12. `XFrameOptionsMiddleware`

`AUTHENTICATION_BACKENDS` = `ModelBackend` + `allauth.account.auth_backends.AuthenticationBackend` (L110-113).

`TEMPLATES`: DjangoTemplates, `DIRS=[BASE_DIR/'templates']` (that directory is **empty**), `APP_DIRS=True`, standard 3 context processors (L117-132).

### 1.4 Database (L142-173)
`_build_default_db()`:
- If `DATABASE_URL` set: parse it; `NAME`=path, `USER/PASSWORD` unquoted, `HOST/PORT`; every libpq query-string param (sslmode, channel_binding, ...) becomes `OPTIONS`. If hostname contains `-pooler` (Neon PgBouncer) sets `DISABLE_SERVER_SIDE_CURSORS=True`.
- Else individual vars: `DB_NAME` (`jokesfor`), `DB_USER` (`postgres`), `DB_PASSWORD` (`''`), `DB_HOST` (`localhost`), `DB_PORT` (`5432`).
Engine is always `django.db.backends.postgresql`.

### 1.5 Cache (L188-195)
`CACHES['default']` = **`django.core.cache.backends.db.DatabaseCache`**, `LOCATION='jokesfor_cache'`, `OPTIONS={'MAX_ENTRIES':10000,'CULL_FREQUENCY':3}`. Reason (comment): DRF throttling uses the default cache; LocMemCache would be per-worker/per-instance and bypassable. The table is created by `notifications/migrations/0002_create_cache_table.py` (`call_command('createcachetable', database=alias)`), so it exists after `migrate` in prod and in the test DB.

### 1.6 Static & media storage (L224-282)
- `STATIC_URL='static/'`, `STATIC_ROOT=BASE_DIR/'staticfiles'`; `STORAGES['staticfiles']` = `whitenoise.storage.CompressedManifestStaticFilesStorage`.
- `MEDIA_URL='/media/'`, `MEDIA_ROOT=BASE_DIR/'media'`.
- `build_default_storage(bucket_name)` (L235-273): empty `GS_BUCKET_NAME` -> `FileSystemStorage`; otherwise `storages.backends.gcloud.GoogleCloudStorage` with `bucket_name`, `default_acl=None`, `querystring_auth=False` (stable public non-expiring `https://storage.googleapis.com/<bucket>/<path>` URLs, uniform bucket-level public-read; signed URLs deliberately avoided because Cloud Run's default SA can't V4-sign and OG crawlers need non-expiring links), `file_overwrite=True`, optional `project_id` from `GS_PROJECT_ID`, optional `location` (path prefix) from `GS_LOCATION`. Credentials come from ADC.
- `SAFESEARCH_ENABLED` = `os.getenv('SAFESEARCH_ENABLED','')` truthy in `('1','true','yes')` (L287). Read in `jokes/media_screening.py:36`.

### 1.7 `REST_FRAMEWORK` (L297-322)
- `DEFAULT_AUTHENTICATION_CLASSES` = `['dj_rest_auth.jwt_auth.JWTCookieAuthentication']` only (cookie or Bearer JWT; no session auth).
- No `DEFAULT_PERMISSION_CLASSES` key -> DRF default `AllowAny`; every view sets its own `permission_classes` (mostly `IsAuthenticated`; public reads use `AllowAny`).
- Pagination: `PageNumberPagination`, `PAGE_SIZE=10`.
- Throttles: `AnonRateThrottle` + `UserRateThrottle` default; rates: `anon 100/hour`, `user 1000/hour`, `verification_resend 3/15min` (string exists only so `get_rate()` doesn't raise; the real (3, 900s) window is hardcoded in `notifications/throttles.py:ResendThrottle.parse_rate`), `creator_insights 120/hour` (`creator_insights/throttles.py`), `media-upload 30/hour`, `appeals 10/day`, `tips-checkout 30/hour` (`billing/views.py:112 throttle_scope`).
- Schema: `drf_spectacular.openapi.AutoSchema`; `SPECTACULAR_SETTINGS` title "Jokes For API" v1.0.0.
- Versioning: `URLPathVersioning`, `DEFAULT_VERSION='v1'`, `ALLOWED_VERSIONS=['v1']`. NOTE: the URLconf hardcodes `api/v1/` prefixes rather than a `<version>` path converter, so `request.version` will be the default `'v1'`.

### 1.8 CORS / CSRF / cookies / transport (L336-421)
- `CORS_ALLOWED_ORIGINS` = `['http://localhost:5173','http://127.0.0.1:5173']` + comma-split `CORS_ALLOWED_ORIGINS` env. `CORS_ALLOW_CREDENTIALS=True`. `CORS_ALLOW_HEADERS = (*default_headers,'x-csrftoken')`.
- `FRONTEND_URL` = `os.getenv('FRONTEND_URL','https://jokesforfront.web.app')` — used for password-reset links (`jokes/password_reset.py`), sitemap `<loc>`s, share-page redirects (`jokes/views.py:1377`), digest email links.
- `CSRF_TRUSTED_ORIGINS` = env comma list, plus `FRONTEND_URL` always appended if absent (L365-367).
- `SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')` (L373).
- `_COOKIE_SAMESITE = os.getenv('JWT_COOKIE_SAMESITE','Lax')`; if `'None'` then `CSRF_COOKIE_SAMESITE='None'` and `SESSION_COOKIE_SAMESITE='None'`. `CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE = not DEBUG`. `CSRF_COOKIE_HTTPONLY=False` (SPA obtains the token value from `GET /api/v1/auth/csrf/`).
- `if not DEBUG`: `SECURE_HSTS_SECONDS=int(os.getenv('SECURE_HSTS_SECONDS','31536000'))`, `SECURE_HSTS_INCLUDE_SUBDOMAINS=True`, `SECURE_HSTS_PRELOAD=True`, `SECURE_SSL_REDIRECT=True`, `SECURE_CONTENT_TYPE_NOSNIFF=True`; else all off. (CI runs with `DEBUG=True` precisely because `SECURE_SSL_REDIRECT` would 301 test-client requests — `.github/workflows/ci.yml`.)

### 1.9 dj-rest-auth (`REST_AUTH`, L431-460)
`USE_JWT=True`; cookies `jokes-access-token` / `jokes-refresh-token`; `JWT_AUTH_HTTPONLY=True`; **`JWT_AUTH_COOKIE_USE_CSRF=True`** (CSRF enforced only when the JWT cookie is present and no `Authorization` header; login/register/google/verify are unauthenticated so no CSRF on bootstrap; simplejwt `token/refresh` + `token/verify` have `authentication_classes=()` so are not CSRF-checked; rollback = set False); `JWT_AUTH_SECURE = not DEBUG`; `JWT_AUTH_SAMESITE = os.getenv('JWT_COOKIE_SAMESITE','Lax')`; `SESSION_LOGIN=False`; `REGISTER_SERIALIZER='JokesForProject.serializers.EmailOnlyRegisterSerializer'`; `USER_DETAILS_SERIALIZER='JokesForProject.serializers.JokesForUserDetailsSerializer'` (adds read-only `date_of_birth` from profile); `PASSWORD_RESET_SERIALIZER='jokes.password_reset.FrontendPasswordResetSerializer'` (emails `<FRONTEND_URL>/reset-password?uid=..&token=..`; without it dj-rest-auth's default `reverse('password_reset_confirm')` raises NoReverseMatch); `OLD_PASSWORD_FIELD_ENABLED=True`.

### 1.10 `SIMPLE_JWT` (L466-475)
Access 15 min, refresh 1 day, `ROTATE_REFRESH_TOKENS=True`, `BLACKLIST_AFTER_ROTATION=True`, `UPDATE_LAST_LOGIN=True`, HS256 signed with `SECRET_KEY`, header type `Bearer`.

### 1.11 Email / verification / digests (L478-505)
- `EMAIL_BACKEND = os.getenv('EMAIL_BACKEND','django.core.mail.backends.console.EmailBackend')` (prod: `anymail.backends.resend.EmailBackend`).
- `ANYMAIL={'RESEND_API_KEY': os.getenv('RESEND_API_KEY','')}`; `DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL','Jokes For <noreply@localhost>')`.
- `EMAIL_VERIFICATION_REQUIRED = os.getenv(...,'false')=='true'` — gate switching `CookieRegisterView` between legacy (active user + JWT cookies on 201) and gated (inactive user, 6-digit code emailed, 201 with no tokens; `jokes/views.py:821-890`).
- `EMAIL_VERIFICATION_CODE_TTL_MINUTES` (`10`), `EMAIL_VERIFICATION_MAX_ATTEMPTS` (`5`).
- `BACKEND_URL = os.getenv('BACKEND_URL','https://jokesforbackend-332865216810.us-east1.run.app')` — base for the unsubscribe link in digest emails.
- `DIGEST_SEND_CAP` (`500`), `DIGEST_MILESTONE_THRESHOLD` (`10`), `DIGEST_CRON_TOKEN` (`''` => `RunDigestsView` 404s for every caller = dormant).

### 1.12 Stripe / billing (L508-516)
`STRIPE_SECRET_KEY` (`''`), `STRIPE_PUBLISHABLE_KEY` (`''`), `STRIPE_WEBHOOK_SECRET` (`''`), `STRIPE_API_VERSION` (`'2026-05-27.dahlia'`), `BILLING_ENABLED` (`'false'`), `BILLING_SUCCESS_URL` (`http://localhost:5173/billing/success`), `BILLING_CANCEL_URL` (`http://localhost:5173/billing/cancel`), `BILLING_PORTAL_RETURN_URL` (`http://localhost:5173/account`).
**Code/docs discrepancy:** `BILLING_ENABLED` is defined in settings and `.env.example` but is never read anywhere else (`grep` finds only settings.py). The real dormant gate is `billing.stripe_gateway.is_enabled()` = `bool(STRIPE_SECRET_KEY)` (`billing/stripe_gateway.py:15`), checked in `CheckoutSessionView`, `TipCheckoutView`, `PortalSessionView`, `StripeWebhookView`, and `PlanAdmin.push_to_stripe`.

### 1.13 allauth / Google (L521-541)
`ACCOUNT_LOGIN_METHODS={'email'}`, `ACCOUNT_SIGNUP_FIELDS=['email*','password1*','password2*']`, `ACCOUNT_EMAIL_VERIFICATION='none'` (verification is the custom notifications flow, not allauth's), `ACCOUNT_UNIQUE_EMAIL=True`, `SOCIALACCOUNT_ADAPTER='JokesForProject.adapters.SocialAccountAdapter'` (COPPA DOB gate for new Google users: `pre_social_login` validates DOB stashed on the raw request by `GoogleLogin.post`; missing -> 400 `{"code":"dob_required"}`; under 13 -> 400 field error; `save_user` persists to `profile.date_of_birth`), `SOCIALACCOUNT_PROVIDERS['google']` scope profile+email, `access_type=offline`, PKCE on. `GOOGLE_OAUTH_CALLBACK_URL` (`http://localhost:5173/auth/google/callback`). `GOOGLE_CLIENT_ID/SECRET/SITE_DOMAIN/SITE_NAME` are read only by the `setup_social_app` management command.

### 1.14 Observability / logging (L546-627)
`GOOGLE_CLOUD_PROJECT` (`'332865216810'`), `LOG_LEVEL` (`DEBUG` if DEBUG else `INFO`), `LOG_FORMAT` (`plain`/`json`; NOTE: only informational — the handler formatter is actually chosen by `DEBUG`, L578), `LOG_SQL` (`false`).
`LOGGING`: formatters `gcp_json` (`observability.formatters.GoogleCloudJsonFormatter`) and `plain` (`PlainFormatter`); single `stdout` StreamHandler; root at `LOG_LEVEL`; loggers `django` INFO, `django.request` ERROR, `django.server` WARNING, `django.db.backends` DEBUG iff LOG_SQL else WARNING, app loggers `jokesfor` INFO, `jokesfor.access` DEBUG, `jokesfor.metrics` INFO, `jokesfor.audit` INFO, `jokesfor.health` INFO (all `propagate=False`).

### 1.15 Sentry (L632-664)
`SENTRY_DSN` (`''` => no-op). If set: `sentry_sdk.init(DjangoIntegration, traces_sample_rate=float(SENTRY_TRACES_SAMPLE_RATE or '0'), send_default_pii=False, environment=SENTRY_ENVIRONMENT or 'production'/'development' by DEBUG, release=K_REVISION, before_send=observability.sentry.scrub_event, ignore_errors=[Throttled, NotAuthenticated, PermissionDenied, AuthenticationFailed, Http404, ValidationError, notifications.service.EmailSendError])`.

### 1.16 Complete env-key inventory (with defaults)
`DEBUG`(False) · `SECRET_KEY`(dev key / required) · `ALLOWED_HOSTS`(localhost,127.0.0.1) · `DATABASE_URL`('') · `DB_NAME`(jokesfor) · `DB_USER`(postgres) · `DB_PASSWORD`('') · `DB_HOST`(localhost) · `DB_PORT`(5432) · `GS_BUCKET_NAME`('') · `GS_PROJECT_ID`('') · `GS_LOCATION`('') · `SAFESEARCH_ENABLED`('') · `CORS_ALLOWED_ORIGINS`('') · `FRONTEND_URL`(https://jokesforfront.web.app) · `CSRF_TRUSTED_ORIGINS`('') · `JWT_COOKIE_SAMESITE`(Lax) · `SECURE_HSTS_SECONDS`(31536000) · `EMAIL_BACKEND`(console) · `RESEND_API_KEY`('') · `DEFAULT_FROM_EMAIL`(Jokes For <noreply@localhost>) · `EMAIL_VERIFICATION_REQUIRED`(false) · `EMAIL_VERIFICATION_CODE_TTL_MINUTES`(10) · `EMAIL_VERIFICATION_MAX_ATTEMPTS`(5) · `BACKEND_URL`(prod run.app URL) · `DIGEST_SEND_CAP`(500) · `DIGEST_MILESTONE_THRESHOLD`(10) · `DIGEST_CRON_TOKEN`('') · `STRIPE_SECRET_KEY`('') · `STRIPE_PUBLISHABLE_KEY`('') · `STRIPE_WEBHOOK_SECRET`('') · `STRIPE_API_VERSION`(2026-05-27.dahlia) · `BILLING_ENABLED`(false, unused) · `BILLING_SUCCESS_URL` · `BILLING_CANCEL_URL` · `BILLING_PORTAL_RETURN_URL` · `GOOGLE_OAUTH_CALLBACK_URL`(http://localhost:5173/auth/google/callback) · `GOOGLE_CLOUD_PROJECT`(332865216810) · `LOG_LEVEL` · `LOG_FORMAT` · `LOG_SQL`(false) · `SENTRY_DSN`('') · `SENTRY_TRACES_SAMPLE_RATE`(0) · `SENTRY_ENVIRONMENT` · `K_REVISION` (Cloud Run injected; also `health.py`) · `GIT_SHA` (`health.py` fallback) · `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `SITE_DOMAIN`(localhost:8000) / `SITE_NAME` (`setup_social_app` only) · `PORT`(8080, Dockerfile) · `GOOGLE_APPLICATION_CREDENTIALS` (ADC only, not read by code).

---

## 2. Project package: `JokesForProject/`

- `urls.py` — root routes: `healthz`, `readyz` (plain Django views, `JokesForProject/health.py`), `sitemap.xml` (`jokes.sitemap.sitemap_view`), `admin/`, `jokes/<int:pk>/share/` (`joke_share_page`, OG/JSON-LD page that meta-refreshes humans to the SPA), `api/v1/` -> `jokes.urls`, `api/v1/creators/` -> `creator_insights.urls`, `api/v1/follows/` -> `follows.urls`, `api/v1/users/` -> `follows.user_urls` (`me/following/`, `me/tips/`), `api/v1/billing/` -> `billing.urls`, `api/v1/tips/` -> `billing.tip_urls`, `api/v1/auth/csrf/` (`csrf_token_view`), `api/v1/auth/` -> `dj_rest_auth.urls`, `api/v1/auth/registration/` -> `CookieRegisterView` (overrides root; sub-paths still from `dj_rest_auth.registration.urls`), `api/v1/auth/google/` (`GoogleLogin`), `api/v1/auth/` -> `notifications.urls` (`verify-email/`, `resend-verification/`), `api/v1/notifications/` -> `inbox.urls`, `api/v1/email/unsubscribe/` (`EmailUnsubscribeView`), `api/v1/internal/run-digests/` (`RunDigestsView`, schema-excluded), `api/schema/`, `api/docs/` (Swagger), `api/redoc/`.
- `health.py` — `healthz` (process-only 200 `{status:ok}`), `readyz` (SELECT 1 + cache set/get/delete round-trip on `jokesfor_cache`; 200 `{status:ready,checks,version}` or 503 `{status:not_ready,...}`; logs `jokesfor.health`). `_VERSION = K_REVISION or GIT_SHA or 'unknown'`.
- `serializers.py` — `JokesForUserDetailsSerializer` (+`date_of_birth` read-only from `profile`), `EmailOnlyRegisterSerializer` (email/password1/password2/`date_of_birth` required; rejects future DOB and age < 13; `username = email`; persists DOB onto the signal-created `UserProfile`).
- `adapters.py` — `SocialAccountAdapter` (see 1.13), `DateOfBirthRequired` APIException (400 `{code:'dob_required',detail}`), `MIN_AGE=13`.
- `observability/` — `context.py` (contextvars: request_id, trace, span, user_id, sampled, db_count, db_time; `bind_request_context`, `clear_request_context`, `get_log_fields`, `reset_db_stats`, `add_db_query`, `get_db_stats`); `formatters.py` (`GoogleCloudJsonFormatter`: `severity`, `message`, `timestamp`, `sourceLocation`, merges context fields, emits `logging.googleapis.com/trace = projects/<GOOGLE_CLOUD_PROJECT>/traces/<32hex>` only when trace validates against `^[0-9a-fA-F]{32}$`, `logging.googleapis.com/spanId`, copies `extra=` fields, `exception` text; `PlainFormatter` `%H:%M:%S LEVEL name  message`); `middleware.py` (see 1.3; explicit "WHY NO OPENTELEMETRY" regression-guard comment); `redaction.py` (`_DENYLIST` of secret keys incl. `password*`, `token`, `access`, `refresh`, `authorization`, `secret`, `api_key`, `resend_api_key`, `code`, `code_hash`, `cookie`, `set-cookie`, `jokes-access-token`, `jokes-refresh-token`, `x-digest-token`, `x_digest_token`; `mask_email` `a***@domain`, `hash_email` sha256[:12], `mask_ip` zero last IPv4 octet / IPv6 to first 3 hextets + `::`, `redact_mapping` recursive case-insensitive); `sentry.py` (`scrub_event` applies `redact_mapping` to request headers/cookies/data and `extra`).
- `tests/` — `test_healthz.py`, `test_observability.py`, `test_security_settings.py`.
- `ops/monitoring/` — `access_latency_metric.yaml` (log-based DISTRIBUTION metric `access_request_latency` from `jsonPayload.latency_ms` labelled by route/method/status_class), `dashboard-latency.json`, `README.md` (owner-applied gcloud commands; recommends `--min-instances=1`; notes max-instances currently 3).

Deploy: `cloudbuild.yaml` = Build -> Push -> **Migrate** (`python manage.py migrate --noinput` inside the built image with `DEBUG=True`, `DATABASE_URL` from Secret Manager `database-url`) -> `gcloud run services update` (env preserved). CI: `.github/workflows/ci.yml` (Postgres 15 service, `DEBUG=True`, `ruff check .` hard gate, bandit + pip-audit non-blocking, `manage.py check`, `manage.py test --noinput`). Dependabot weekly for pip + actions.

---

## 3. Apps, responsibilities, models

`AUTH_USER_MODEL` is Django's default `auth.User` (no custom user model). Email is used as `username` at registration.

### 3.1 `jokes` (core domain; `models.py` 1623 lines, 36 migrations, `views.py` 3447 lines)
Responsibility: taxonomy, joke catalog + FTS, user preferences/collections/saves/favorites/ratings/reactions, daily joke, share events, profiles, submissions/drafts + moderation + appeals, achievements, vibes, mystery box, views/impressions/dwell/watch telemetry, streaks, packs, media assets + screening/processing/quarantine, share cards, sitemap, paywall, content-tier serving, moderation visibility, identity helpers, password reset link, admin moderation actions.

Managers (`jokes/managers.py`): `JokeManager.get_queryset()` filters `is_removed=False` (global takedown enforcement); `Joke.all_objects` unfiltered (admin/moderation). `JokeManager.search(query_text, filters, ordering, allowed_tiers)` — optional `content_tier__in`, `SearchQuery(..., search_type='websearch', config='english')` + `SearchRank`, filters by format/age_rating/tones/context_tags/culture_tags/language slugs, ordering `popularity` (like_count via `ratings__rating=1`, save_count), `-created_at`, `relevance`; `.distinct()`.

Models (all `BigAutoField` unless noted):
- Lookups: `Format` (name/slug unique, description), `AgeRating` (+`min_age`), `Tone` (verbose "Category (Tone)"), `ContextTag` (verbose "Theme (ContextTag)"), `Language` (`code` unique ISO 639-1, name), `CultureTag`, `Source` (name, url, description).
- `Joke` (`@pgtrigger.register(UpdateSearchVector('joke_search_vector_update', vector_field='search_vector', document_fields=['text','setup','punchline']))`): `text`, `setup`, `punchline`, FK `format`/`age_rating`/`language` (PROTECT), `source` (SET_NULL), `creator` FK User (SET_NULL, `related_name='created_jokes'`, indexed; null = legacy/seed), M2M `tones`/`context_tags`/`culture_tags`, `content_tier` choices `tier_1|tier_2|tier_3` default `tier_1` indexed, `is_removed` (indexed) + `removed_at`, `lines` JSON (knock-knock), `search_vector` (GIN index `joke_search_vector_idx`), `share_image` ImageField `share-cards/`, timestamps; `ordering=['-created_at']`. `save()` regenerates the share card on create / text change / missing image, **never** for `is_removed=True`, blanks the card on a live->removed transition, persists the file name via queryset `update()` (default manager) to avoid recursion. `regenerate_share_image()` public wrapper (no-op if removed).
- `UserPreference` (1:1 User `preference`): M2M `preferred_tones`/`preferred_contexts`, FK `preferred_age_rating`/`preferred_language`, `notification_enabled`, `notification_time`, `notification_days` JSON list, `streak_saver_enabled`, `notification_daily_joke`, `notification_trending_alerts`, `notification_collection_updates`, `notification_email_digest`, `onboarding_completed`, `show_mature` (adult tier_2 opt-in).
- `Collection` (FK user `collections`, name, description, `is_default`, `is_public`; `unique_together (user,name)`; ordering `-is_default, name`).
- `SavedJoke` (user, joke `saved_by`, nullable collection, note; `unique_together (user, joke, collection)`).
- `DailyJoke` (user, joke `daily_deliveries`, `date`, `delivered_at`; `unique_together (user,date)`; index (user,date)).
- `JokeRating` (user, joke `ratings`, `rating` SmallInt `LIKE=1|DISLIKE=-1`; `unique_together (user,joke)`).
- `ShareEvent` (joke `share_events`, nullable user, `platform` in copy/twitter/facebook/whatsapp/other; indexes (joke,created_at),(platform,created_at)).
- `UserProfile` (1:1 User `profile`): `bio`(<=500), `avatar` ImageField `avatars/`, `is_premium` (denormalised, synced by Stripe webhooks), `display_name`(50), `handle` (30, unique, nullable, `^[a-z0-9_]{3,30}$` via `jokes/identity.py`), `public_profile`, `show_activity`, `share_analytics`, `date_of_birth` (null = minor, fail-safe), `theme` light/dark/system, `email_digest_opt_in` (default True), `creator_milestone_opt_in` (default True); properties `age`, `is_adult` (>=18 and known), `is_minor`.
- `Favorite` (user `favorites`, joke `favorited_by`; unique (user,joke)).
- `JokeSubmission` (user `joke_submissions`, mirrors Joke content fields + FK format/age_rating/language PROTECT, `source` CharField default `'original'`, M2M tones/context_tags/culture_tags, `lines` JSON, `status` draft/pending/published/rejected, `rejection_reason`, `published_joke` 1:1 Joke SET_NULL `related_name='submission'`; index (user,status); ordering `-updated_at`).
- `Achievement` (slug unique, title, description, icon, `criteria_type`, `criteria_value`), `UserAchievement` (unique (user,achievement)).
- `ContentReport` (reporter `content_reports`, joke `reports`, `reason` offensive/inappropriate/spam/copyright/harassment/other, description, `status` pending/reviewed/resolved/dismissed, `resolved_at`; index (status,created_at)).
- `UserBlock` (blocker `blocked_users`, blocked `blocked_by`; unique (blocker,blocked)).
- `Vibe` (slug unique, label, subtitle, icon emoji, `swatch_bg/fg`, order, M2M `formats`/`themes`(ContextTag)/`categories`(Tone), `is_active`; `filter_jokes(qs)` = AND across non-empty axes, any-match within). 12 vibes seeded in migration 0013 (office, dad, puns, dark, nerd, surreal, wholesome, observ, oneliner, date, kids, absurd); recipes populated in 0021.
- `UserVibe` (user `user_vibes`, vibe `picked_by`, `weight` float; unique (user,vibe)).
- `MysteryBoxRoll` (`MAX_DAILY_ROLLS=3`; user `mystery_rolls`, joke `mystery_pulls`, `source_vibe` SET_NULL, `rolled_at`, `rolled_date` auto-set in `save()`; index (user,rolled_date)).
- `JokeReaction` (user `joke_reactions`, joke **`reactions_v2`**, `reaction` lol/crying/hmm/eyeroll; unique (user,joke); index (joke,reaction)).
- `JokeView` (user `joke_views`, joke `views`, `source` daily/search/explore/mystery/pack/saved/share/other indexed, `revealed_punchline`, `viewed_at`, `viewed_date` auto-set; indexes (user,-viewed_at),(user,viewed_date),(joke,-viewed_at)). Doubles as the paywall ledger and the streak trigger.
- `JokeImpression` (user, joke `impressions`, source feed/explore/search/daily/pack/other, `created_date`; indexes (joke,created_date),(user,joke,created_date); deduped per (user,joke,day) at ingest).
- `JokeDwell` (user, joke `dwells`, `dwell_ms`, `scroll_pct` 0-100 nullable, source, `created_date`; append-only).
- `JokeWatch` (user, joke `watches`, `watch_ms`, `watch_pct`, source, `watched_at`; append-only).
- `Streak` (1:1 User `streak`; `FREEZES_PER_MONTH=2`; `current_count`, `longest_count`, `last_active_date`, `freeze_days_available`, `freezes_used_total`, `last_freeze_refresh_month` 'YYYY-MM', `started_at`).
- `StreakDay` (user `streak_days`, date, status read/frozen/missed; unique (user,date)).
- `JokePack` (slug unique, title, subtitle, description, `cover_color`, `is_published` indexed, `is_featured`, `publish_at`, `expires_at`, M2M `jokes` through `JokePackEntry`, `created_by` SET_NULL; ordering `-is_featured,-created_at`), `JokePackEntry` (pack `entries`, joke, `order`; unique (pack,joke)), `JokePackProgress` (user `pack_progress`, pack `progress_records`, `last_read_entry`, `completed_at`; unique (user,pack)).
- `MediaAsset` (**UUID pk**; owner `media_assets`, `kind` image/video/audio, `file` + `poster` at `media-assets/<uuid>/<name>`, width/height/`duration_ms`, `is_gif`, `safesearch` JSON verdict, `phash` (64-bit dHash hex, indexed), `quarantined_at`). Methods: `quarantine()` (moves file+poster to `quarantine/<uuid>/<token_urlsafe(16)>/<basename>`, crash-safe copy-then-save-then-delete), `release()` (back to `media-assets/<uuid>/<basename>`), `purge()`/`delete_with_files()` (only storage-deletion path).
- `JokeSubmissionMedia` (submission `media`, asset `submission_links`, position; UniqueConstraint `uniq_submission_media_position`), `JokeMedia` (joke `media`, asset `joke_links`, position; UniqueConstraint `uniq_joke_media_position`).
- `Appeal` (user `appeals`, nullable joke/submission, `action_type` takedown/rejection, `reason_text`, `status` pending/upheld/reversed, `resolved_at`, `resolver` SET_NULL, `resolution_note`; CheckConstraint `appeal_exactly_one_target`; partial UniqueConstraints `uniq_pending_appeal_per_user_joke` / `..._submission` on `status='pending'`).

Support modules: `serving.py` (`allowed_tiers(request)` -> `{tier_1}` for anon/minor/no-profile/adult-without-show_mature; `{tier_1,tier_2}` only for authenticated adult with `show_mature`; tier_3 never; logs `jokesfor.metrics` `content_tier_decision` / `age_gate_block`), `moderation.py` (`is_blocked_between`, `hidden_user_ids`, `visible_jokes(qs, request)` = not removed + exclude blocked creators both directions), `paywall.py` (`paywall_state(request)`: free limit `free_joke_reads_per_day` default 10 via `billing.entitlements.get_limit`; ledger = distinct `JokeView.joke_id` for (user, today UTC); paid => unlimited; anonymous => signed cookie `jf_anon_reads` salt `jokes.paywall.anon`, max_age 48h, date-checked, httponly, secure=not DEBUG; `record_anon_read`), `identity.py` (`public_display_name`, `public_handle` -> `@user<pk>` fallback, never email), `submission_rules.py` (`FORMAT_RULES` per slug oneliner/setup/knock/story/anti/observ/image/video/audio with required/forbidden/constraints, `validate_per_format`), `media_processing.py` (Pillow: JPEG/PNG/WEBP <=10MB, <=4096px, orient, downscale to 1600, WebP q82 = EXIF strip; dHash; `MediaBusyError` per-instance encode slot guard; ffmpeg video/audio normalisation), `media_probe.py` (ffprobe subprocess, 30s timeout), `media_screening.py` (Vision SafeSearch when `SAFESEARCH_ENABLED`; blocks on adult/violence >= LIKELY; fail-open `status:'error'` on client exceptions; `HashMatcher`/`NullMatcher` CSAM seam), `quarantine.py` (`purge_lapsed_quarantine()` lazy 14-day sweep, skips assets with open appeals or live-joke links, audits `media_purged`), `share_cards.py` (CairoSVG render of `jokes/share_cards/*.svg`; tone templates dad-jokes/dark/puns else base; media card embeds downscaled image or video poster, never the mp4; audio -> text card with 'Audio' badge), `sitemap.py` (static routes + tier_1 non-removed jokes (cap 20000) + creators with attributed jokes (cap 5000) + published packs in window (cap 2000); absolute `FRONTEND_URL` locs), `recommendations.py` (`get_personalized_joke`, `get_recently_shown_joke_ids` 30-day window, `get_daily_editorial_joke`), `password_reset.py`, `templatetags/mathfilters.py` (`multiply`).

Signals (`jokes/signals.py`, connected in `JokesConfig.ready`):
- `post_save(User)` x3: `create_user_preference`, `create_user_profile`, `create_default_collection` ('Favorites', `is_default=True`) — all `if created`.
- `post_save(jokes.JokeView)` `update_streak_on_view`: only when `created`; get-or-create `Streak`; refresh 2 freezes on new `YYYY-MM`; `_walk_gap` from `last_active_date+1` to today-1 creating `StreakDay` frozen (burning freezes) or missed (reset `current_count=0`); upsert today's `StreakDay(read)`; if today already counted -> save & exit; else `current_count+=1`, `longest_count=max`, `last_active_date=today`, `started_at` set once.
- `pre_save(jokes.JokeSubmission)` `stash_submission_status` + `post_save` `notify_submission_rejected`: on transition into `rejected` (not on create, not on re-save while rejected) -> `inbox.notify(user,'joke_rejected', submission_id, rejection_reason)`. Queryset `.update()` bypasses this.

Admin (`jokes/admin.py`, 905 lines): all models registered. `JokeAdmin` uses `Joke.all_objects`, action `restore_jokes` (release quarantined assets, un-remove, regenerate cards). `JokeSubmissionAdmin.approve_and_publish` (pending only; creates `Joke` with `creator=submission.user`, `content_tier='tier_2' if age_rating.min_age>=18 else 'tier_1'`, copies M2M + `JokeMedia`, `regenerate_share_image()` after media copy, sets `published_joke`/`status='published'`, `notify(...,'joke_published')`). `ContentReportAdmin.take_down_joke` (flip `is_removed`, blank share cards, notify `joke_removed` with top reason + 14-day `appeal_deadline`, resolve reports, `quarantine()` assets not shared with live jokes, audit `media_quarantined` + `content_takedown` per joke), `dismiss_reports`, `mark_resolved`. `AppealAdmin.uphold_appeals` (purge quarantined assets unless shared/sibling-appeal; audit `appeal_upheld`; notify `appeal_resolved` outcome upheld) and `reverse_appeals` (takedown: release assets, un-remove, regenerate card; rejection: submission back to `draft` with reason; audit `appeal_reversed`; notify). `UserBlockAdmin`, `VibeAdmin`, pack admin with entry inline, etc.

Templates: `jokes/templates/jokes/share.html` (OG/Twitter/JSON-LD + `meta refresh` to `frontend_joke_url`), `share_redirect.html` (content-free `noindex` bounce when tier not allowed), `share_cards/{base_card,dad_joke,dark_humor,pun,media_card}.svg`.

Fixtures: `lookup_data.json` (3 formats one-liner/setup-punchline/short-story, 4 age ratings, 5 tones, 8 context tags, 1 language, 3 culture tags, 3 sources — NOTE these legacy slugs differ from the design vocabulary seeded by migration 0021: formats `oneliner/setup/knock/story/anti/observ` + 0031 `image` + 0032 `video/audio`; both sets coexist in the DB), `jokes.json` (137 jokes).

Data migrations of note: 0002 `TrigramExtension`, 0003 search vector + GIN + pgtrigger, 0013 seed vibes, 0021 seed taxonomy + ~150 jokes + 4 packs (idempotent `update_or_create`), 0025 backfill `Joke.creator` from published submissions, 0031/0032 seed media formats.

### 3.2 `notifications` (transactional email engine + verification + digests)
Models: `EmailMessageLog` (to_email indexed, template_name, subject, `status` pending/sent/failed indexed, `provider_message_id`, error, nullable user `email_logs`, `sent_at`; index (to_email,-created_at)) — outbox/audit AND idempotency ledger for digests; `EmailVerification` (user `email_verifications`, `code_hash` sha256, `expires_at` indexed, `consumed_at`, `attempts`; index (user,-created_at)); `DigestRun` (`date` unique, started/finished, `digests_sent`, `milestones_sent`, `claimed_until` = pooling-safe conditional-UPDATE claim instead of advisory lock).
Modules: `service.send_email(to, template_name, context, user, headers)` (render via `templates_registry.TEMPLATES` = `verification_code`, `daily_digest`, `creator_milestone`; log row pending->sent/failed; raises `EmailSendError`), `verification.py` (`issue_code` invalidates prior codes, 6-digit `secrets.randbelow`, TTL; `verify_code` -> `no_active_code|expired|too_many_attempts|incorrect`, `hmac.compare_digest`, atomic conditional consume), `throttles.ResendThrottle` (per-email 3 per 15 min), `unsubscribe.py` (signed token `{uid,type}` salt `email.unsubscribe`, 90-day max age, kinds `digest`->`email_digest_opt_in`, `milestone`->`creator_milestone_opt_in`), `digests.run_daily_digests()` (daily digest of setup-only teaser to active + opted-in users not already logged today; creator milestone when >= threshold new reactions since last milestone email; shared `DIGEST_SEND_CAP`; `List-Unsubscribe`/`List-Unsubscribe-Post` headers; unsubscribe link at `BACKEND_URL`).
Views: `VerifyEmailView` (POST `{email,code}`; uniform 400 for unknown email; 429 on too many attempts; activates user and sets JWT cookies), `ResendVerificationView` (only for `is_active=False` users; uniform 200), `EmailUnsubscribeView` (GET confirm page / POST apply; no auth), `RunDigestsView` (no auth/throttle; `X-Digest-Token` constant-time compare vs `DIGEST_CRON_TOKEN`; any failure or empty token -> 404; audits `digest_run`). Templates: `notifications/templates/notifications/email/{base.html, verification_code.html/.txt, daily_digest.html/.txt, creator_milestone.html/.txt}`; `base.html` contains a `[COMPANY POSTAL ADDRESS]` placeholder (owner action). Admin: all three models read-only. Migrations: 0001, 0002 cache table, 0003 DigestRun, 0004 `claimed_until`.

### 3.3 `creator_insights` (no models, no migrations)
Read-only aggregation service `services.build_creator_insights(creator, period)` (overview/breakdowns/top_jokes/audience/suggestions; constants `READ_THRESHOLD_MS=4000`, `COMPLETION_SCROLL_PCT=90`, `WATCH_COMPLETION_PCT=90`), `resolve_creator_jokes(creator)` = `Joke.creator=creator OR (creator null AND submission.user=creator AND published)` (owner-scoped, bypasses tier lock), `build_creator_profile(creator, viewer, tiers)` for public profile. `permissions.IsCreator` = has >=1 published `JokeSubmission`. `throttles.CreatorInsightsThrottle` scope `creator_insights`. URLs: `me/insights/`, `<creator_id>/profile/`, `<creator_id>/tips/summary/` (view lives in billing).

### 3.4 `follows`
Model `Follow` (follower `following`, creator `followers`; unique (follower,creator); indexes (creator,created_at),(follower,created_at)). `services.follow()` rejects self-follow and blocked pairs (`jokes.moderation.is_blocked_between`), notifies `followed_you` on create; `unfollow` idempotent; counts/`is_following`. URLs: `follows/<creator_id>/` (follow/unfollow), `.../status/`, `.../followers/`, `users/me/following/`.

### 3.5 `audit`
Model `AuditLog` (actor SET_NULL `audit_events` indexed, `actor_email_hash` sha256 64-hex indexed, `action` indexed, `target_type`, `target_id`, `ip` (masked), `request_id` indexed, `user_agent`(256), `outcome` success/failure/denied indexed, `metadata` JSON, `created_at` indexed; indexes (action,outcome),(created_at); **`pgtrigger.Protect('append_only', Update|Delete)`** — rows are immutable at the DB level). `services.record_audit(request, action, outcome, actor, target_type, target_id, metadata)` writes the row in try/except AND always logs a `jokesfor.audit` line. Signals (`AuditConfig.ready` -> `register_receivers`): `user_logged_in` -> `login/success`, `user_logged_out` -> `logout/success`, `user_login_failed` -> `login/failure` with only `attempted_identifier_hash` (never queries User). Actions seen in code: `login`, `logout`, `registration`, `content_takedown`, `media_quarantined`, `media_purged`, `appeal_upheld`, `appeal_reversed`, `block`, `unblock`, `data_export`, `digest_run` (plus account deletion path in `UserAccountDeleteView`). Admin read-only.

### 3.6 `billing`
Models: `Plan` (slug unique, name, description, `is_active`, `is_public`, `is_default`, `sort_order`, `interval` month/year/blank, `amount_cents` nullable, currency, `stripe_product_id`, `stripe_price_id`, `features` JSON, `limits` JSON); `Subscription` (1:1 User `subscription`, plan PROTECT, `stripe_customer_id`/`stripe_subscription_id` indexed, `stripe_price_id`, `status` default `'free'`, `ACTIVE_STATUSES={'active','trialing'}`, `LIVE_PAID_STATUSES={'active','trialing','past_due'}`, period start/end, `cancel_at_period_end`; `is_entitled()`); `UsageCounter` (user, key, period_key, count; unique (user,key,period_key)); `ProcessedStripeEvent` (event_id unique, event_type) — webhook idempotency; `Tip` (sender `tips_sent`, creator `tips_received`, joke SET_NULL `tips`, `amount_cents`, currency, `status` pending/succeeded/failed/refunded indexed, `stripe_payment_intent_id`/`stripe_checkout_session_id` indexed, `completed_at`).
`entitlements.py`: `KNOWN_FEATURES={'creator_analytics':True,'daily_joke_preview':False,'mature_content_addon':False}`, `KNOWN_LIMITS={'mystery_box_rolls_per_day':3,'submissions_per_day':5,'daily_jokes_per_day':1,'daily_joke_history_days':30,'free_joke_reads_per_day':10}`; `effective_plan(user)` = entitled subscription plan else `is_default` plan else None (fail open to FREE); `has_feature`, `get_limit` (None = unlimited), `check_and_consume_quota` (atomic `select_for_update` on `UsageCounter`, lazy period reset via period_key), `check_quota_by_count`. `permissions.HasFeature(key)` factory. `stripe_gateway.py` (`is_enabled`, `get_or_create_customer` creates a `Subscription(status='free')` lazily, `create_checkout_session` mode=subscription, `create_tip_checkout_session` mode=payment, portal, `construct_event`). `webhooks.handle_event`: dedupe on `ProcessedStripeEvent`, handles `checkout.session.completed` (subscription or tip via metadata), `customer.subscription.created/updated/deleted`, `invoice.paid`, `invoice.payment_failed`; `_upsert_subscription` under `select_for_update`; `_sync_is_premium` mirrors entitlement to `UserProfile.is_premium`. Migrations: 0002 seeds plans `free` (default), `supporter` ($5 PLACEHOLDER), `creator_pro` ($15 PLACEHOLDER) with features/limits; 0003 adds `free_joke_reads_per_day` = 10 / None / None; 0004 Tip. Views: `PlansView` (AllowAny), `CheckoutSessionView`, `PortalSessionView`, `MySubscriptionView`, `EntitlementsView` (IsAuthenticated), `StripeWebhookView` (AllowAny, no auth, raw body, 200 `billing_dormant` when disabled, 400 bad signature, 500 handler error), `TipCheckoutView` (scope `tips-checkout`), `CreatorTipsSummaryView` (AllowAny), `MyTipsView`. Admin: `PlanAdmin.push_to_stripe` action.

### 3.7 `inbox` (in-app notifications)
Model `Notification` (recipient `notifications`, actor SET_NULL, `verb` in `followed_you|joke_published|joke_removed|joke_rejected|appeal_resolved`, joke SET_NULL, `data` JSON (`DjangoJSONEncoder`), `read`, `created_at`; index (recipient,read,created_at)). `services.notify(recipient, verb, actor=None, joke=None, **extra)` — synchronous create, no-op when recipient is None or recipient == actor. URLs `api/v1/notifications/` list, `unread-count/`, `mark-read/`. Migrations 0001-0004 (verb choices, `data`, encoder + `appeal_resolved`).

---

## 4. Management commands (`jokes/management/commands/`)
- `seed_jokes` — loads `jokes/fixtures/jokes.json` (`--count` default 150, `--clear`); requires all 7 lookup tables non-empty (`loaddata lookup_data` first); atomic; sets M2M by pk.
- `seed_achievements` — `update_or_create` 12 achievements (first_save, collector_10/50, first_favorite, first_share, sharer_10, first_rating, rater_50, streak_7/30, first_submission, published_joke).
- `seed_demo_creator` — idempotent fake creator `demo.creator@jokesfor.dev` / `DemoCreator!2026` (display "Dara Punwell", handle `darapun`), `--jokes 14 --viewers 140 --days 30 --fresh`; generates JokeView/Impression/Dwell/Reaction/Save/Favorite/Share/Follow graph with `RANDOM_SEED=2026`; real (non-`@jokesfor.dev`) accounts are only attributed, never re-credentialed; `--fresh` wipes only `@jokesfor.dev` users.
- `setup_social_app` — `update_or_create` `Site(id=1)` from `SITE_DOMAIN`/`SITE_NAME` and `SocialApp(provider='google')` from `GOOGLE_CLIENT_ID/SECRET`; errors if missing.
- `backfill_share_cards` — dry-run by default; `--apply`, `--only-media`, `--limit`; regenerates cards for live jokes with blank `share_image`; per-joke fail-open.
No other app defines commands.

---

## 5. Entity-relationship overview (prose)

`auth.User` is the hub. Each User has exactly one `UserProfile` (identity, DOB/age gate, premium flag, email opt-ins), one `UserPreference` (taste + notification settings, `show_mature`), one `Streak`, at most one `Subscription` (-> `Plan`), and one default `Collection` — the first three and the collection are created by `post_save` signals. Users own many `Collection`s, `SavedJoke`s (optionally inside a Collection), `Favorite`s, `JokeRating`s (legacy like/dislike) and `JokeReaction`s (4-emoji, one per joke), `DailyJoke` deliveries (one per date), `JokeView`s (detail opens; the paywall ledger and streak trigger), `JokeImpression`s (card seen, deduped per day), `JokeDwell`/`JokeWatch` samples, `StreakDay`s (one per date), `UserVibe` picks (-> `Vibe`), `MysteryBoxRoll`s, `JokePackProgress` rows, `UserAchievement`s (-> `Achievement`), `ContentReport`s, `UserBlock`s (blocker/blocked), `Follow`s (follower/creator), `Appeal`s, `Tip`s sent/received, `Notification`s received, `EmailMessageLog`s, `EmailVerification`s, `AuditLog` events (actor SET_NULL, email hash survives deletion), `MediaAsset`s (UUID, owner-scoped uploads), and `JokeSubmission`s (drafts/pending/published/rejected).

`Joke` is the content hub: FK to `Format`, `AgeRating`, `Language` (PROTECT), optional `Source` and `creator` User (SET_NULL); M2M to `Tone` ("Category"), `ContextTag` ("Theme"), `CultureTag`. A published `JokeSubmission` points 1:1 at its `Joke` (`published_joke`/`submission`); at publish time the admin copies content, tags, `JokeSubmissionMedia` -> `JokeMedia` (ordered links to shared `MediaAsset`s), and stamps `creator`. `Vibe` is a saved filter recipe over Format/Theme/Category and has no direct FK to Joke. `JokePack` groups Jokes through ordered `JokePackEntry`. `Appeal` targets exactly one of Joke (takedown) or JokeSubmission (rejection). Content visibility is layered: `Joke.objects` hides `is_removed`; `serving.allowed_tiers` filters `content_tier`; `moderation.visible_jokes` hides blocked creators; `paywall.paywall_state` strips punchlines past the daily cap (serializer-side). Billing gates resolve via `Subscription -> Plan.features/limits` with `UsageCounter` per (user, key, period). Stripe webhook idempotency is `ProcessedStripeEvent`. Email idempotency for digests is `EmailMessageLog`, with `DigestRun` as the per-date claim/observability row.

---

## 6. Docs vs code discrepancies noticed
- `.planning/codebase/ARCHITECTURE.md` (dated 2026-01-11) describes a scaffold with SQLite, "no custom apps", "no in-memory caching" — entirely stale; code has 7 apps, Postgres, DatabaseCache, GCS, etc. Treat `.planning/codebase/*` as historical only.
- `LOG_FORMAT` env var is defined but the JSON/plain formatter is chosen by `DEBUG`, not by `LOG_FORMAT` (settings L578).
- `BILLING_ENABLED` is defined but unused; Stripe dormancy is `STRIPE_SECRET_KEY`-driven.
- `creator_insights/models.py` docstring says `CreatorFollow` is "deferred to slice 2" — in code that edge exists as `follows.Follow`.
- `REST_FRAMEWORK` versioning is `URLPathVersioning` but no URL pattern carries a `<version>` kwarg, so it is effectively decorative.
- `templates/` root directory is empty; all templates live in app dirs.
