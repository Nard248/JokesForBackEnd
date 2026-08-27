# JokesFor — Infrastructure, Deployment & Operations Map (key: infra-ops)

Date of analysis: 2026-08-25. Read-only. All facts verified against code, live `gcloud`
(project `jokesfor`, account narek.h.meloyan@gmail.com), live `curl`, Cloud Logging reads,
GitHub Actions run history (`gh run list`) and the Neon API (read-only). Where docs and code
disagree this is called out explicitly (section 12).

Backend repo: `/Users/narekmeloyan/PycharmProjects/JokesForProject` (HEAD `56e4945` = the image
running in prod).  Frontend repo: `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend`.

---

## 1. Topology at a glance

```
Browser
  │  https://jokesforfront.web.app  (also https://jokesfor.net, https://jokesforfront.firebaseapp.com)
  ▼
Firebase Hosting CDN  (GCP project jokesforfront, #77998926066)   ← static SPA (Vite dist/)
  │
  │  cross-origin XHR, withCredentials=true, CORS allow-list on Django
  ▼
Cloud Run service `jokesforbackend`  (GCP project jokesfor, #332865216810, us-east1)
  https://jokesforbackend-332865216810.us-east1.run.app  (alt: https://jokesforbackend-q6w4ck2t2q-ue.a.run.app)
  gunicorn 2 workers × 4 gthread threads, Django 5.2, WhiteNoise for /static/
  │
  ├─ Neon Postgres 17 (AWS us-east-1, project blue-salad-57632192, pooled host `…-pooler`)  — DB + DatabaseCache (throttles)
  ├─ GCS bucket `jokesfor-media-prod` (US multi-region, uniform access, public-read URLs)   — media uploads + share cards
  ├─ Google Cloud Vision SafeSearch (ADC via runtime SA)                                     — upload pre-screen
  ├─ Resend (via django-anymail)                                                             — transactional email
  ├─ Stripe (TEST-mode keys in prod env)                                                     — tips / subscriptions (webhook synchronous)
  ├─ Google OAuth (allauth; client id 332865216810-7kou…)                                    — social login
  ├─ Sentry (sentry-sdk wired, but SENTRY_DSN NOT set in prod → no-op)                       — error tracking
  └─ Cloud Logging / Cloud Trace (structured JSON stdout + X-Cloud-Trace-Context)            — observability
```

Two separate GCP projects: the frontend lives in `jokesforfront` (Firebase), the backend in
`jokesfor`. A Firebase→Cloud Run same-origin proxy was attempted and abandoned because Firebase
Hosting cannot rewrite to a Cloud Run service in another project
(`jokes-for-frontend/Docs/Hosting_Setup.md` §4). Hence the cross-site cookie posture
(`JWT_COOKIE_SAMESITE=None`, CSRF double-submit via `X-CSRFToken`).

---

## 2. Backend container image — `Dockerfile`

File: `/Users/narekmeloyan/PycharmProjects/JokesForProject/Dockerfile`

| Aspect | Value |
|---|---|
| Base | `python:3.11-slim`, two-stage (builder installs wheels with `pip install --prefix=/install/deps`, runtime copies to `/usr/local`) |
| Runtime apt libs | `libcairo2 libpango-1.0-0 libpangocairo-1.0-0` (cairosvg share cards), `libpq5` (psycopg2), `ffmpeg` (media normalisation, `jokes/media_processing.py`, `jokes/media_probe.py`) |
| User | non-root `app` (system user, home `/app`, nologin) |
| Static | `collectstatic --noinput --clear` at **build time** with throwaway `SECRET_KEY=build-only-key DEBUG=False ALLOWED_HOSTS=*`; `GS_BUCKET_NAME` deliberately unset so only WhiteNoise staticfiles storage is touched |
| Env baked | `PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 DJANGO_SETTINGS_MODULE=JokesForProject.settings` |
| CMD | `gunicorn JokesForProject.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --worker-class gthread --timeout 300 --error-logfile -` (gunicorn access log intentionally disabled; `AccessLogMiddleware` emits the JSON access line instead) |
| `.dockerignore` | excludes `.git .venv .env* .planning .remember .claude staticfiles media Docs *.md tests **/test_*.py` — note `**/test_*.py` but NOT `tests.py`/`tests_*.py`, so flat test modules (e.g. `jokes/tests_media.py`) ship in the image |

Consequences worth knowing:
* `--timeout 300` deliberately equals Cloud Run's `timeoutSeconds: 300` so in-request video
  encoding (minutes) is not killed by the gunicorn arbiter.
* 2×4 = **8 concurrent request slots per instance**, but the Cloud Run service is configured
  with `containerConcurrency: 80` (section 5). Cloud Run may route up to 80 in-flight requests
  to one instance; 72 of them queue in gunicorn's socket backlog. A single long video encode
  occupies 1/8 of an instance's capacity.

---

## 3. Backend deploy pipeline — Cloud Build (`cloudbuild.yaml`)

File: `/Users/narekmeloyan/PycharmProjects/JokesForProject/cloudbuild.yaml`
Trigger (live, verified via `gcloud builds triggers describe`):

| Field | Value |
|---|---|
| Name / id | `rmgpgab-jokesforbackend-us-east1-Nard248-JokesForBackEnd--maqgc` / `1127aeb4-8ff4-42a3-b0ba-bf8a9b0d80b7` (region `global`) |
| Source | GitHub `Nard248/JokesForBackEnd`, push to `^main$` |
| Config | `cloudbuild.yaml` (repo root) |
| Build service account | `332865216810-compute@developer.gserviceaccount.com` (the **default compute SA**, not the legacy `@cloudbuild` SA the doc names) |
| Substitutions | `_AR_HOSTNAME=us-east1-docker.pkg.dev _AR_PROJECT_ID=jokesfor _AR_REPOSITORY=cloud-run-source-deploy REPO_NAME=jokesforbackend _SERVICE_NAME=jokesforbackend _DEPLOY_REGION=us-east1 _PLATFORM=managed` |
| Last 5 builds | all SUCCESS; latest `ad467d78…` 2026-08-04T18:10Z for commit `56e4945` (= current `main` HEAD) |

### Deployment flow (prose diagram)

1. **Developer pushes/merges to `main`** on GitHub (`Nard248/JokesForBackEnd`).
   - In parallel and independently, GitHub Actions `CI` (section 4) runs lint + tests on the
     push. **It is NOT a gate** — Cloud Build fires on the same push regardless of CI outcome.
2. **Cloud Build trigger fires** (global region), runs as the compute SA, with
   `options.logging: CLOUD_LOGGING_ONLY`.
3. **Step `Build`** — `docker build --no-cache -t us-east1-docker.pkg.dev/jokesfor/cloud-run-source-deploy/jokesforbackend/jokesforbackend:$COMMIT_SHA -f Dockerfile .`
   (`--no-cache` ⇒ every build recompiles wheels; AR repo is already 3.27 GB).
4. **Step `Push`** — pushes that tag to Artifact Registry.
5. **Step `Migrate`** — runs **inside the freshly built image**: `python manage.py migrate --noinput`
   with env `DEBUG=True ALLOWED_HOSTS=localhost` and `DATABASE_URL` injected from Secret Manager
   secret `database-url` (`availableSecrets.secretManager[0].versionName: projects/$PROJECT_ID/secrets/database-url/versions/latest`).
   `DEBUG=True` is used so settings.py does not demand `SECRET_KEY`. **If migrate fails the build
   stops and Deploy never runs** (schema is always ahead of the code).
6. **Step `Deploy`** — `gcloud run services update jokesforbackend --platform=managed --image=<tag> --labels=managed-by=…,commit-sha=…,gcb-build-id=…,gcb-trigger-id=… --region=us-east1 --quiet`.
   No `--set-env-vars`, so the service's existing env/secret bindings are preserved.
   Creates a new revision (`jokesforbackend-000NN-xxx`) and routes 100 % traffic to it
   (`traffic: latestRevision: true`).
7. Cloud Run starts the new revision; the **default TCP startup probe** on 8080 must succeed
   (`failureThreshold 1, periodSeconds 240, timeoutSeconds 240`); old revision is retired.
8. Rollback = `gcloud run services update-traffic jokesforbackend --to-revisions=<prev>=100 --region us-east1`
   (`Docs/CICD_SETUP.md` §Rollback). Migrations are **not** rolled back.

Frontend ordering caveat (doc): backend must deploy before the frontend when the API contract
changes (`Docs/CICD_SETUP.md` §Frontend deploy ordering).

---

## 4. Backend CI — `.github/workflows/ci.yml`

File: `/Users/narekmeloyan/PycharmProjects/JokesForProject/.github/workflows/ci.yml`

* Triggers: `pull_request` (any), `push` to `main` only.
* Service container `postgres:15` (user/pass `postgres`, db `jokesfor`, `pg_isready` health).
* Env: `DATABASE_URL=''` (forces the `DB_*` fallback path in `settings._build_default_db`),
  `DB_HOST=localhost`, **`DEBUG='True'`** (documented reason: `DEBUG=False` flips
  `SECURE_SSL_REDIRECT` on and every test-client request 301s; also `SECRET_KEY` is only
  required when `DEBUG=False`).
* Steps: checkout@v4 → setup-python@v5 (3.11, pip cache) → apt `ffmpeg libcairo2 libpango-1.0-0 libpangocairo-1.0-0`
  (mirrors Dockerfile) → `pip install -r requirements.txt` + pinned `ruff==0.16.1 bandit==1.9.4 pip-audit==2.10.1`
  → **`ruff check .` (hard gate)** → `bandit … || true` (non-blocking) → `pip-audit … || true`
  (non-blocking) → `python manage.py check` → `python manage.py test --noinput`.
* Ruff config in `pyproject.toml` (`[tool.ruff]`, line-length 100, select `F E W I B UP C4 DJ`,
  ignores `E501 E402`, several per-file ignores); bandit config `[tool.bandit]`.
* Dependabot (`.github/dependabot.yml`): weekly `pip` + `github-actions`.
* Live evidence: `gh run list` shows `CI` runs succeeding on Dependabot PRs (≈6 min each,
  2026-08-04) — so the trailing NOTE in the file ("has not been run on actual GitHub Actions
  infrastructure yet") is **stale**; CI has run and passes.
* Gap: CI is advisory only — nothing prevents a red `main` from deploying (Cloud Build triggers
  on the push, not on CI success).

---

## 5. Cloud Run service — live configuration (`gcloud run services describe`, 2026-08-25)

| Setting | Live value |
|---|---|
| Service / region / project | `jokesforbackend` / `us-east1` / `jokesfor` (#332865216810) |
| Created / generation | 2026-05-09T15:17Z / 46 revisions; current `jokesforbackend-00046-bqv` (2026-08-04T18:13Z) |
| Image | `us-east1-docker.pkg.dev/jokesfor/cloud-run-source-deploy/jokesforbackend/jokesforbackend:56e4945666d40bd0d7a4cbbe10546503a7ca969d` |
| CPU / memory | `1000m` / `1Gi`; `run.googleapis.com/startup-cpu-boost: 'true'` |
| Concurrency | `containerConcurrency: 80` |
| Scaling | `autoscaling.knative.dev/maxScale: '3'` on the template; **no `minScale` ⇒ min-instances = 0 (scale-to-zero)**. (Service-level metadata also carries a stale `run.googleapis.com/maxScale: '2'` annotation; the template value 3 is effective, matching `ops/monitoring/README.md` "currently 3".) |
| Request timeout | `timeoutSeconds: 300` |
| Ingress / auth | `ingress: all`; `run.googleapis.com/invoker-iam-disabled: 'true'` (public, unauthenticated). `get-iam-policy` returns no bindings (`etag: ACAB`) — public access is via the invoker-IAM-disabled flag, not `allUsers` binding. |
| Runtime service account | `332865216810-compute@developer.gserviceaccount.com` (default compute SA) |
| Probes | **Startup probe only**: `tcpSocket :8080, failureThreshold 1, periodSeconds 240, timeoutSeconds 240` (`startupProbeType: Default`). **No liveness probe is configured** — `/healthz` is not used by the platform at all. |
| Port | `8080` (`http1`) |
| Deployer | Cloud Build (`managed-by=gcp-cloud-build-deploy-cloud-run`) |

### Environment on the service (names + where the value comes from)

Plain env vars (values visible in the service spec):
`DEBUG=False`, `ALLOWED_HOSTS=.run.app,jokesfor.net,www.jokesfor.net`, `GOOGLE_CLIENT_ID=332865216810-7kou…apps.googleusercontent.com`,
`GOOGLE_OAUTH_CALLBACK_URL=https://jokesforfront.web.app/auth/google/callback`, `SITE_DOMAIN=jokesforfront.web.app`,
`SITE_NAME=JokesFor`, `CORS_ALLOWED_ORIGINS=https://jokesfor.net,https://jokesforfront.web.app,https://jokesforfront.firebaseapp.com`,
`CSRF_TRUSTED_ORIGINS=<same three>`, `JWT_COOKIE_SAMESITE=None`, `EMAIL_BACKEND=anymail.backends.resend.EmailBackend`,
`DEFAULT_FROM_EMAIL=Jokes For <noreply@jokesfor.net>`, `EMAIL_VERIFICATION_REQUIRED=true`, `GS_BUCKET_NAME=jokesfor-media-prod`,
`STRIPE_SECRET_KEY=sk_test_…` (**test-mode**, plain env), `STRIPE_PUBLISHABLE_KEY=pk_test_…`, `STRIPE_WEBHOOK_SECRET=whsec_…` (plain env),
`BILLING_SUCCESS_URL=https://jokesforfront.web.app/settings/billing?checkout=success`, `BILLING_CANCEL_URL=…?checkout=cancel`,
`BILLING_PORTAL_RETURN_URL=https://jokesforfront.web.app/settings/billing`, `SAFESEARCH_ENABLED=true`.

Secret Manager bindings (`valueFrom.secretKeyRef`, all `key: latest`):
`SECRET_KEY ← django-secret-key`, `DATABASE_URL ← database-url`, `GOOGLE_CLIENT_SECRET ← google-client-secret`, `RESEND_API_KEY ← resend-api-key`.

**NOT set in prod (falls to settings.py defaults):** `SENTRY_DSN` (⇒ Sentry disabled),
`SENTRY_*`, `LOG_LEVEL` (⇒ INFO), `LOG_FORMAT` (⇒ json), `FRONTEND_URL` (⇒ `https://jokesforfront.web.app`),
`BACKEND_URL` (⇒ the run.app URL), `DIGEST_CRON_TOKEN` (⇒ digest endpoint 404s / dormant),
`DIGEST_SEND_CAP`, `DIGEST_MILESTONE_THRESHOLD`, `BILLING_ENABLED` (⇒ False), `STRIPE_API_VERSION`,
`SECURE_HSTS_SECONDS` (⇒ 31536000), `GS_PROJECT_ID`, `GS_LOCATION`, `EMAIL_VERIFICATION_CODE_TTL_MINUTES`,
`EMAIL_VERIFICATION_MAX_ATTEMPTS`, `GOOGLE_CLOUD_PROJECT` (Cloud Run injects it), `GIT_SHA`.
Cloud Run auto-injects `K_SERVICE`, `K_REVISION`, `K_CONFIGURATION`, `PORT`.

### Secret Manager (project jokesfor) — `gcloud secrets list`

| Secret | Created | Versions | Consumers |
|---|---|---|---|
| `database-url` | 2026-05-09 | 1 (enabled) | Cloud Run env `DATABASE_URL`; Cloud Build `Migrate` step |
| `django-secret-key` | 2026-05-09 | 1 | Cloud Run env `SECRET_KEY` (also JWT signing key) |
| `google-client-secret` | 2026-05-09 | 1 | Cloud Run env `GOOGLE_CLIENT_SECRET` |
| `resend-api-key` | 2026-06-12 | 1 | Cloud Run env `RESEND_API_KEY` (memory note: "needs rotation" — still version 1) |

Stripe keys and the webhook secret are **not** in Secret Manager (plain env). 

### IAM (project `jokesfor`, `gcloud projects get-iam-policy`)
* `user:narek.h.meloyan@gmail.com` — `roles/owner`.
* `332865216810-compute@developer.gserviceaccount.com` (runtime **and** build SA) —
  `roles/editor`, `roles/run.admin`, `roles/iam.serviceAccountUser`, `roles/artifactregistry.writer`,
  `roles/cloudbuild.builds.builder`, `roles/logging.logWriter`, `roles/secretmanager.secretAccessor`.
  `roles/editor` on the runtime SA is broad (covers GCS + Vision, but far more).
* `332865216810@cloudbuild.gserviceaccount.com` — `roles/cloudbuild.serviceAgent` only (the doc's
  IAM steps target this SA, but the trigger does not run as it).

### Enabled APIs (relevant subset)
`run`, `cloudbuild`, `artifactregistry`, `secretmanager`, `storage`, `vision`, `logging`,
`monitoring`, `cloudtrace`, `iamcredentials`. **Not enabled:** `cloudscheduler` (digest
activation prerequisite), `clouderrorreporting` (not listed).

### Other GCP resources
* Artifact Registry `cloud-run-source-deploy` (DOCKER, us-east1, 3268 MB).
* GCS bucket `jokesfor-media-prod` (location `US`, uniform bucket-level access = True).
* **No** log-based metrics, **no** Monitoring dashboards, **no** uptime checks
  (`gcloud logging metrics list` / `monitoring dashboards list` / `uptime list-configs` all empty).
  The versioned configs in `ops/monitoring/` have **not been applied**.
* **No** Cloud Scheduler jobs (API not even enabled).

---

## 6. Django settings — runtime/env contract (`JokesForProject/settings.py`)

Key infra-relevant behaviours (line refs approximate):
* `load_dotenv()` at import — local `.env` honoured; in the container there is no `.env`
  (dockerignored), so only real env applies.
* `DEBUG` parsed from env; **`SECRET_KEY` required when `DEBUG=False`** (raises
  `ImproperlyConfigured`) — test `test_missing_secret_key_in_prod_raises`.
* `ALLOWED_HOSTS` comma list, default `localhost,127.0.0.1`.
* DB: `_build_default_db()` — if `DATABASE_URL` set: parse URL, pass query params
  (`sslmode`, `channel_binding`, …) into `OPTIONS`, and **if hostname contains `-pooler`
  set `DISABLE_SERVER_SIDE_CURSORS=True`** (Neon PgBouncer transaction mode). Otherwise `DB_*`.
  **No `CONN_MAX_AGE` / `CONN_HEALTH_CHECKS`** ⇒ Django default 0 ⇒ a new TLS connection to
  Neon per request (see §10 latency evidence).
* Cache: `django.core.cache.backends.db.DatabaseCache` table `jokesfor_cache`
  (`MAX_ENTRIES 10000, CULL_FREQUENCY 3`), created by migration
  `notifications/migrations/0002_create_cache_table.py`. Used by DRF throttling so limits are
  shared across workers/instances (no Redis).
* Static: `STATIC_ROOT=staticfiles`, `whitenoise.storage.CompressedManifestStaticFilesStorage`,
  `WhiteNoiseMiddleware` right after `SecurityMiddleware`.
* Media: `build_default_storage(GS_BUCKET_NAME)` → `storages.backends.gcloud.GoogleCloudStorage`
  with `default_acl=None, querystring_auth=False, file_overwrite=True` (public, non-expiring
  `https://storage.googleapis.com/<bucket>/<path>` URLs; signed URLs deliberately avoided because
  the default SA cannot V4-sign without IAM Credentials API). Empty bucket ⇒ `FileSystemStorage`.
* `SAFESEARCH_ENABLED` truthy-string flag; Vision client via ADC (`jokes/media_screening.py`
  `_client()` → `vision.ImageAnnotatorClient()`), fail-open on client errors.
* Security when `DEBUG=False`: `SECURE_SSL_REDIRECT=True`, HSTS 1y + subdomains + preload,
  `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')`
  (Cloud Run TLS termination), `CSRF_COOKIE_SECURE`/`SESSION_COOKIE_SECURE = not DEBUG`.
* Cross-site cookies: `JWT_COOKIE_SAMESITE=None` also flips `CSRF_COOKIE_SAMESITE` and
  `SESSION_COOKIE_SAMESITE` to `None`. `REST_AUTH.JWT_AUTH_COOKIE_USE_CSRF=True`.
* CORS: localhost:5173 defaults + `CORS_ALLOWED_ORIGINS` env; `CORS_ALLOW_CREDENTIALS=True`;
  `CORS_ALLOW_HEADERS` adds `x-csrftoken`. `CSRF_TRUSTED_ORIGINS` env + `FRONTEND_URL` auto-appended.
* Email: `EMAIL_BACKEND` env (console default), `ANYMAIL.RESEND_API_KEY`, `DEFAULT_FROM_EMAIL`.
* Stripe/billing: all dormant when `STRIPE_SECRET_KEY` empty; `BILLING_ENABLED` separate flag.
* `DIGEST_CRON_TOKEN` empty ⇒ `RunDigestsView` raises 404 for every caller
  (`notifications/views.py:232-280`, constant-time compare). Verified live: `POST /api/v1/internal/run-digests/` → 404.
* Logging: `LOGGING` dict with `gcp_json` (`GoogleCloudJsonFormatter`) when `DEBUG=False`,
  `plain` otherwise; root at `LOG_LEVEL`; app loggers `jokesfor`, `jokesfor.access` (DEBUG),
  `jokesfor.metrics`, `jokesfor.audit`, `jokesfor.health`; `django.request` at ERROR.
* Sentry: only if `SENTRY_DSN` set — `DjangoIntegration`, `traces_sample_rate` from env (0),
  `send_default_pii=False`, `environment` from env or `production`/`development`,
  `release=K_REVISION`, `before_send=scrub_event`, `ignore_errors` for Throttled/NotAuthenticated/
  PermissionDenied/AuthenticationFailed/Http404/ValidationError/EmailSendError.

---

## 7. Environment-variable matrix

Legend for "Where set": **CR** = Cloud Run service env (plain), **SM** = Secret Manager via Cloud
Run `secretKeyRef`, **CB** = Cloud Build `Migrate` step, **auto** = injected by Cloud Run,
**default** = not set in prod, settings.py default applies, **local** = `.env` only, **GHA** =
GitHub Actions workflow env, **GH-secret/var** = GitHub repo secret / variable.

### Backend

| Variable | Where set (prod) | Purpose / consumer |
|---|---|---|
| `DEBUG` | CR=`False`; CB=`True` (migrate only); GHA CI=`True` | Master switch: SECRET_KEY requirement, HSTS/SSL redirect, log format, cookie Secure flags |
| `SECRET_KEY` | SM `django-secret-key` | Django signing + `SIMPLE_JWT.SIGNING_KEY` (HS256) |
| `ALLOWED_HOSTS` | CR=`.run.app,jokesfor.net,www.jokesfor.net`; CB=`localhost` | Host header validation (note: `www.jokesfor.net` does not resolve to a working site) |
| `DATABASE_URL` | SM `database-url` (CR + CB) | Neon connection string; `-pooler` host ⇒ no server-side cursors |
| `DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT` | local / GHA CI | Fallback when `DATABASE_URL` empty |
| `GOOGLE_CLIENT_ID` | CR | allauth Google provider (also read by `setup_social_app` mgmt cmd) |
| `GOOGLE_CLIENT_SECRET` | SM `google-client-secret` | same |
| `GOOGLE_OAUTH_CALLBACK_URL` | CR=`https://jokesforfront.web.app/auth/google/callback` | `GoogleLogin` view callback |
| `SITE_DOMAIN`, `SITE_NAME` | CR | `setup_social_app` command (Site row + SocialApp) |
| `CORS_ALLOWED_ORIGINS` | CR (3 origins) | django-cors-headers allow-list (verified live: both web.app and jokesfor.net get ACAO + credentials) |
| `CSRF_TRUSTED_ORIGINS` | CR (3 origins) | Django CSRF origin check |
| `FRONTEND_URL` | default `https://jokesforfront.web.app` | Password-reset links, sitemap `<loc>`, share-page redirect, digest links; auto-added to CSRF trusted |
| `BACKEND_URL` | default (run.app URL) | Digest unsubscribe link base (`notifications/digests.py:45`) |
| `JWT_COOKIE_SAMESITE` | CR=`None` | JWT/CSRF/session cookie SameSite for cross-site SPA |
| `SECURE_HSTS_SECONDS` | default 31536000 | HSTS (verified live header `max-age=31536000; includeSubDomains; preload`) |
| `EMAIL_BACKEND` | CR=`anymail.backends.resend.EmailBackend` | Email transport |
| `RESEND_API_KEY` | SM `resend-api-key` | anymail Resend |
| `DEFAULT_FROM_EMAIL` | CR=`Jokes For <noreply@jokesfor.net>` | From header |
| `EMAIL_VERIFICATION_REQUIRED` | CR=`true` | Registration verification gate |
| `EMAIL_VERIFICATION_CODE_TTL_MINUTES`, `EMAIL_VERIFICATION_MAX_ATTEMPTS` | default 10 / 5 | Verification codes |
| `GS_BUCKET_NAME` | CR=`jokesfor-media-prod` | Switches default storage to GCS |
| `GS_PROJECT_ID`, `GS_LOCATION` | default (unset) | Optional GCS project / key prefix |
| `GOOGLE_APPLICATION_CREDENTIALS` | local only | Local key file for prod-like tests; prod uses ADC of runtime SA |
| `SAFESEARCH_ENABLED` | CR=`true` | Vision SafeSearch at upload |
| `STRIPE_SECRET_KEY` | CR (plain, `sk_test_…`) | Un-dorms billing (`billing.stripe_gateway.is_enabled()`) |
| `STRIPE_PUBLISHABLE_KEY` | CR (plain, `pk_test_…`) | Exposed to frontend if needed |
| `STRIPE_WEBHOOK_SECRET` | CR (plain, `whsec_…`) | Webhook signature verification `POST /api/v1/billing/webhook` |
| `STRIPE_API_VERSION` | default `2026-05-27.dahlia` | Stripe SDK pin |
| `BILLING_ENABLED` | default `false` | Secondary billing flag |
| `BILLING_SUCCESS_URL`, `BILLING_CANCEL_URL`, `BILLING_PORTAL_RETURN_URL` | CR (frontend `/settings/billing…`) | Checkout/portal redirects |
| `DIGEST_CRON_TOKEN` | **unset** (dormant) | Shared secret for `/api/v1/internal/run-digests/` (`X-Digest-Token`) |
| `DIGEST_SEND_CAP`, `DIGEST_MILESTONE_THRESHOLD` | default 500 / 10 | Digest engine tunables |
| `SENTRY_DSN` | **unset** ⇒ Sentry no-op | Error tracking |
| `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_ENVIRONMENT` | default 0 / `production` | Sentry |
| `LOG_LEVEL`, `LOG_FORMAT`, `LOG_SQL` | default INFO / json / false | Logging |
| `GOOGLE_CLOUD_PROJECT` | auto (Cloud Run) ; default `332865216810` | Trace resource name `projects/<id>/traces/<trace>` |
| `K_REVISION` | auto | `readyz.version`, Sentry `release` |
| `GIT_SHA` | never set | fallback version for readyz (unused) |
| `PORT` | Dockerfile `8080` / auto | gunicorn bind |
| `DJANGO_SETTINGS_MODULE` | Dockerfile | settings module |

### Frontend (build-time, baked into the bundle by Vite)

| Variable | Where set | Purpose |
|---|---|---|
| `VITE_API_URL` | GH var `VITE_API_URL` or workflow fallback `https://jokesforbackend-332865216810.us-east1.run.app/api/v1`; local `.env` = `http://localhost:8000/api/v1` | axios `baseURL` (`src/lib/axios.ts:8`), `AuthProvider.tsx:7`; also read by `scripts/gen-sitemap.mjs` (prebuild) |
| `VITE_USE_MOCKS` | GH var or fallback `false`; local `true` | Mock adapters (`daily-reads/api.ts`) |
| `VITE_USE_REAL_PREFERENCES`, `VITE_USE_REAL_CREATE` | fallback `true` | Feature cut-over flags (`api-adapter.ts:677`, `create/adapter.ts:22`) |
| `VITE_FIREBASE_API_KEY, _AUTH_DOMAIN, _PROJECT_ID, _STORAGE_BUCKET, _MESSAGING_SENDER_ID, _APP_ID, _MEASUREMENT_ID` | GH secrets (7, created 2026-05-09) | `src/lib/firebase.ts` — app init + Analytics (consent-gated `initAnalytics()`, `isSupported()`); no measurementId ⇒ analytics null |
| `VITE_GOOGLE_CLIENT_ID` | GH var or fallback `332865216810-7kou…` | `features/auth/google-oauth.ts:44` |
| `VITE_GOOGLE_OAUTH_REDIRECT_URI` | GH var or fallback `https://jokesforfront.web.app/auth/google/callback` | `google-oauth.ts:27` |
| `FIREBASE_SERVICE_ACCOUNT_JOKESFORFRONT` | GH secret | `FirebaseExtended/action-hosting-deploy@v0` |
| `GITHUB_TOKEN` | auto | PR preview comments |

CI (`ci.yml`) builds with `ci-placeholder` values for all Firebase keys. `gh variable list` shows
no repository variables defined, so all `vars.*` fallbacks are in effect.

---

## 8. Frontend hosting & pipeline

Files: `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/{firebase.json,.firebaserc,.github/workflows/*.yml,scripts/gen-sitemap.mjs,Docs/Hosting_Setup.md}`

* `.firebaserc` default project `jokesforfront`. Hosting sites: `jokesforfront.web.app`,
  `jokesforfront.firebaseapp.com`, custom domain `jokesfor.net` (DNS A → `199.36.158.100`,
  served, HSTS `max-age=31556926`). **`www.jokesfor.net` CNAMEs to `jokesfor.net` but the TLS
  handshake fails (`curl` exit, http=000)** — the www host is not added to Firebase Hosting even
  though the backend's `ALLOWED_HOSTS` lists it.
* `firebase.json`: `public: dist`; SPA rewrite `** → /index.html`; headers:
  `**/*.@(js|css|woff|woff2|ttf|otf|svg|png|jpg|jpeg|webp|avif|ico)` ⇒ `public, max-age=31536000, immutable`;
  `**/index.html` ⇒ `no-cache, no-store, must-revalidate`.
  **Live gotcha:** the `**/index.html` header glob matches only the literal `/index.html` URL.
  `/`, `/search`, `/daily` (SPA-rewritten) are served with Firebase's default
  `cache-control: max-age=3600` (verified). Hashed assets do get `immutable`. So a browser/CDN may
  hold a stale shell for up to 1 h after a deploy, and its referenced hashed bundle names still
  exist (old assets are not purged immediately), so this is a freshness lag not a break.
* Workflows:
  - `ci.yml` — `pull_request` + `push` to non-main branches: `npm ci`, `npm run lint`,
    `npm test -- --run` (vitest), `npm run build` (Node 24; `checkout@v6`, `setup-node@v6`).
  - `firebase-hosting-merge.yml` — push to `main`: `npm ci && npm run build` (env above) →
    `FirebaseExtended/action-hosting-deploy@v0` `channelId: live`, `projectId: jokesforfront`.
    **No lint/test step before deploy on main.**
  - `firebase-hosting-pull-request.yml` — `pull_request` (same-repo only): build + preview channel.
  - `npm run build` = `prebuild` (`scripts/gen-sitemap.mjs`, fail-soft fetch of
    `<backend>/sitemap.xml` into `public/sitemap.xml`, gitignored) → `tsc -b && vite build`.
  - Dependabot weekly npm + github-actions. Recent Dependabot PR runs on 2026-08-04 **failed**
    (eslint 10, jest-dom 7, react-hooks 7.1.1 bumps) — unmerged, so `main` unaffected.
* Live: `/` and deep routes 200 with `index.html`; `robots.txt` disallows private routes and
  points to `https://jokesforfront.web.app/sitemap.xml`; `sitemap.xml` present (backend-generated
  snapshot from the 2026-08-04 build). No Sentry in the frontend (grep: none). Google Fonts
  loaded from `fonts.googleapis.com` in `index.html`.

---

## 9. Observability

Package: `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/observability/`

* `context.py` — `ContextVar`s `request_id, trace, span, user_id, sampled, db_count, db_time`;
  `bind_request_context/clear_request_context` with reset tokens (gthread thread reuse safety).
* `middleware.py`
  - `RequestContextMiddleware` (after WhiteNoise): request id from `X-Request-ID` or uuid4 hex;
    parses `X-Cloud-Trace-Context` (`TRACE/SPAN;o=1`, 32-hex validated); binds contextvars;
    installs `connection.execute_wrapper` to count queries + time; lazily binds `user_id` after
    the view; echoes `X-Request-ID` (verified live on every Django response); tags Sentry
    `request_id`/`cloud_trace_id` if active. Explicit comment: **no OpenTelemetry** (background
    exporter would starve under Cloud Run CPU throttling).
  - `AccessLogMiddleware`: one `jsonfor.access` line `message="request"` with `method, path, route
    (resolver template), status, latency_ms, client_ip (masked), user_id, request_id,
    db_query_count, db_time_ms`; severity INFO/WARNING(4xx)/ERROR(5xx); `/healthz` and `/readyz`
    logged at DEBUG (`_QUIET_PATHS`).
* `formatters.py` — `GoogleCloudJsonFormatter`: `severity, message, timestamp, sourceLocation`,
  merges context fields, emits `logging.googleapis.com/trace = projects/<GOOGLE_CLOUD_PROJECT>/traces/<id>`
  and `/spanId`, `exception` text. Verified live sample (Cloud Logging, 2026-08-25): jsonPayload
  carries all fields and `trace: projects/332865216810/traces/…`, `spanId` populated.
* `redaction.py` — `mask_email`, `hash_email` (sha256[:12]), `mask_ip` (/24, /48),
  `redact_mapping` with denylist (password*, token, access, refresh, authorization, secret,
  api_key, code, cookie, set-cookie, JWT cookie names, `x-digest-token`).
* `sentry.py` — `scrub_event` applies `redact_mapping` to request headers/cookies/data/extra.
* Tests: `JokesForProject/tests/test_observability.py` (28 tests), `test_healthz.py` (8),
  `test_security_settings.py` (5, incl. `test_sentry_not_initialized_without_dsn`).
* Monitoring assets (versioned, **not applied**): `ops/monitoring/access_latency_metric.yaml`
  (log-based DISTRIBUTION metric `access_request_latency` over `jsonPayload.latency_ms`, labels
  route/method/status_class, exponential buckets ×2 from 1 ms) and `ops/monitoring/dashboard-latency.json`
  (p50/p95/p99 by route, request rate by response-code class, instance count). README recommends
  `--min-instances=1` ($15–40/mo) and a load test.
* Design/plan docs (`Docs/superpowers/2026-06-17-observability-design.md`,
  `plans/2026-06-17-observability-plan.md`) list DEFERRED console/IaC work: point Cloud Run
  liveness probe at `/healthz`, uptime check on `/readyz`, alert policies (readiness, 5xx>2 %,
  p95>1500 ms / p99>3000 ms, 429 spikes, content-report spikes, Error Reporting/Sentry spike,
  cert/quota/OOM). **None of these exist in the project today** (verified empty lists).
  The design doc's recommendation to use `/healthz` as the Cloud Run liveness probe is
  **unaffected by the GFE anomaly** (probes are executed by the Cloud Run agent inside the
  instance, not via the public GFE path) — but it has not been configured anyway.

---

## 10. Health probes and the `/healthz` anomaly

Code: `JokesForProject/health.py` (`healthz` → `{"status":"ok"}` 200, no DB; `readyz` → `SELECT 1`
+ cache set/get/delete on `jokesfor_cache`, 200 `ready` / 503 `not_ready`, `version=K_REVISION`,
logs `jokesfor.health` INFO "readyz ok" / WARNING "readyz failed"). Routes in
`JokesForProject/urls.py`: `path('healthz', …)`, `path('readyz', …)` (no trailing slash; plain
Django views, `csrf_exempt`).

### Live probe matrix (2026-08-25, `curl`)

| Request | Status | Served by | Evidence |
|---|---|---|---|
| `GET /healthz` | 404 | **Google edge (GFE), never reached container** | HTML "Error 404 (Not Found)!!1", `content-type: text/html; charset=UTF-8`, `referrer-policy: no-referrer`; **no** `server: Google Frontend`, no `x-request-id`, no HSTS, no `x-cloud-trace-context` |
| `GET /healthz?x=1` | 404 | GFE | identical page |
| `HEAD /healthz`, `POST /healthz`, `GET //healthz` | 404 | GFE | no app headers |
| `GET /healthz%3Fx` (encoded `?`) | 404 | **Django** | `server: Google Frontend`, `x-request-id`, HSTS present, Django "Not Found" HTML (path literally `/healthz?x` ≠ route) |
| `GET /healthzz`, `/Healthz`, `/HEALTHZ`, `/healthz/`, `/healthz/x`, `/healthz.txt`, `/api/v1/healthz`, `/_ah/health`, `/health`, `/health-check`, `/livez`, `/ping` | 404 | Django | app headers present |
| `GET /readyz`, `/readyz?x=1` | 200 JSON | Django | `{"status":"ready","checks":{"db":{"status":"ok","latency_ms":~230-300},"cache":{"status":"ok","latency_ms":~190}},"version":"jokesforbackend-00046-bqv"}` |
| `GET /readyz/` | 404 | Django | trailing slash not routed (`APPEND_SLASH` irrelevant — reverse direction) |
| Alt URL `https://jokesforbackend-q6w4ck2t2q-ue.a.run.app/healthz` | 404 | GFE | same edge page |
| Alt URL `/readyz` | 200 | Django | |
| **Unrelated Cloud Run service** `https://epigraphyatlasback-986826173967.europe-southwest1.run.app/healthz` (different project + region) | 404 | GFE | no app headers; `/healthzz` on the same host reaches its container (`server: Google Frontend`) |
| **Firebase Hosting** `https://jokesforfront.web.app/healthz` | 404 | edge | Every other path (e.g. `/search`, `/daily`) SPA-rewrites to `index.html` with 200; `/healthz` is the one path that does not |
| Cloud Logging request log (`logName:requests`, last 24 h) | — | — | Entries exist for `/healthz/x`, `/healthz.txt`, `/Healthz`, `/HEALTHZ`, `/healthzz`, `/api/v1/healthz`, `/readyz`; **zero entries for exactly `/healthz`** although it was requested ~6 times |

### Diagnosis

The exact path `/healthz` (case-sensitive, any method, with or without a query string) is
intercepted by Google's shared front end (GFE) **before** the request is routed to the Cloud Run
revision, on every Google-fronted hostname tested (`*.run.app` in two projects/regions,
`*.a.run.app`, Firebase Hosting `*.web.app`). The Cloud Run request log never sees it, so no
container-side cause (Django routing, WhiteNoise, `APPEND_SLASH`, `ALLOWED_HOSTS`, CSRF) is
possible — those would all produce a Django-shaped 404 with `server: Google Frontend` and an
`x-request-id`. This is consistent with `/healthz` being a reserved GFE-internal health-check
path (Google's own HTTP servers answer `/healthz`; the edge answers the platform 404 for
externally originated requests to it). It is **not** caused by a custom domain or load balancer
(none are in front of the run.app URL) nor by WhiteNoise (no static file named `healthz`).

Practical consequences:
1. **External** uptime checks / synthetic monitors **must not** target `/healthz`; use `/readyz`
   (which is what `urls.py` comments and the design doc already prescribe for uptime checks).
2. Cloud Run's own HTTP liveness/startup probes are executed from inside the serving
   infrastructure against the container port and would still reach `healthz` if configured — but
   today **no HTTP probe is configured** (default TCP startup probe only), so `/healthz` is
   currently an unused endpoint; the `AccessLogMiddleware` DEBUG-suppression for `/healthz` is
   moot in prod.
3. Renaming the liveness route (e.g. `/livez`, which reaches Django today) would make it
   externally testable; the frontend cannot be affected (it never calls it).

### Cold-start latency (measured + logged)

* **Warm** (instance up, Neon compute active): `/readyz` 0.94–1.17 s end-to-end from Bulgaria
  (`connect ≈0.1 s`, TTFB ≈1.0 s; Cloud Run request log reports server-side latency ≈0.42 s);
  `/api/v1/jokes/` 1.3–1.5 s; `/sitemap.xml` 1.6 s; static admin CSS 0.63 s.
  Inside `/readyz` the app itself reports `db ≈ 226–300 ms` for `SELECT 1` and `cache ≈ 190 ms` for
  three cache queries (≈ 64 ms per round trip GCP us-east1 ↔ AWS us-east-1) — i.e. **~230 ms per
  request is spent establishing a fresh TLS connection to Neon** because `CONN_MAX_AGE` is 0.
* **Cold** (Cloud Logging, last 7 days — every "Default STARTUP TCP probe succeeded" line is
  followed within ~15 s by first requests with app-measured `latency_ms` of **5.5–11.2 s**):
  `2026-08-25T08:25:50 STARTUP` → `08:26:07 readyz 9877 ms (6 queries)`;
  `08-21 20:58:44 STARTUP` → `csrf 10425 ms`, `token/refresh 11179 ms`;
  `08-20 21:43:52 STARTUP` → `/robots.txt 6726 ms (0 queries)`;
  `08-19 07:42:57 STARTUP` → `csrf 6441 ms`, `refresh 5570 ms`.
  The Neon API shows the compute endpoint `ep-round-brook-aq0p3j8j` `started_at: 2026-08-25T08:26:06Z`
  (`suspend_timeout_seconds: 0` = provider default auto-suspend after inactivity, 0.25–2 CU
  autoscaling, `pooler_mode: transaction`) — i.e. the **DB compute resumed 16 s after the container
  started and 1 s before the 9.9 s readyz completed**. The cold path is therefore compound:
  Cloud Run container boot (Django import, ≈ a few seconds, on startup-cpu-boost) **plus Neon
  compute resume (several seconds)**, matching `ops/monitoring/README.md` "~10–14 s" and
  `min-instances=0`. Note that even a `/robots.txt` 404 with 0 queries took 6.7 s on a cold
  instance, so a meaningful share is container/Python start, not only Neon.
* An additional idle-latency probe (240 s and 660 s idle) was run in the background during
  this analysis; see the addendum at the end of this file if present. Cloud Run keeps idle
  instances ~15 min, so short idles typically stay warm while Neon (5 min default) may already
  have suspended — producing the "warm container, cold DB" middle case (~2–5 s).
* Traffic level (request log, last 24 h): a few dozen requests, most of them this analysis's
  probes; consistent with the README's "≈233 req/week ≈ health checks" — every real visitor is
  likely to hit a cold start today.

---

## 11. External services — activation state

| Service | Wired in code | Prod state (verified) |
|---|---|---|
| Neon Postgres | `settings._build_default_db` | Project `blue-salad-57632192` "JokesFor", PG17, aws-us-east-1, pooled host `ep-round-brook-aq0p3j8j-pooler.c-8.us-east-1.aws.neon.tech`, db `neondb`, `sslmode=require&channel_binding=require` (local `.env`; prod secret presumably same), autosuspend default, 512 MB logical size limit |
| GCS | `django-storages` GoogleCloudStorage | bucket `jokesfor-media-prod` (US, UBLA), ADC via compute SA (`roles/editor`) |
| Vision SafeSearch | `jokes/media_screening.py` | `SAFESEARCH_ENABLED=true`, `vision.googleapis.com` enabled; fail-open on errors |
| Resend | anymail backend | `EMAIL_BACKEND` set, key in SM `resend-api-key` (v1, created 2026-06-12); `EMAIL_VERIFICATION_REQUIRED=true` |
| Stripe | `billing/` (checkout, portal, webhook `POST /api/v1/billing/webhook`, tips) | **Test-mode keys** in plain env; `BILLING_ENABLED` unset (False). Go-live runbook `Docs/STRIPE_GOLIVE.md` |
| Google OAuth | allauth + `GoogleLogin`, PKCE | client id/secret set; callback `https://jokesforfront.web.app/auth/google/callback`; `setup_social_app` command provisions Site/SocialApp |
| Sentry | `settings.py` + `observability/sentry.py` | **Disabled** (no `SENTRY_DSN` in prod env); frontend has no Sentry |
| Firebase Hosting / Analytics | frontend | Hosting live (3 hostnames); Analytics consent-gated, keys from GH secrets |
| Cloud Scheduler (digests) | `RunDigestsView` + `notifications/digests.py` | **Dormant**: API not enabled, no jobs, `DIGEST_CRON_TOKEN` unset ⇒ endpoint 404s (verified) |
| Cloud Logging / Trace | observability package | Active (structured JSON verified in Cloud Logging with trace linkage) |
| Cloud Monitoring | `ops/monitoring/*` | **Nothing applied** (no metrics, dashboards, uptime checks, alerts) |

---

## 12. Docs vs. code/reality discrepancies

1. `Docs/CICD_SETUP.md` says the pipeline order is **Migrate → Build → Push → Deploy** with
   migrate running in a `python:3.11-slim` container after `pip install`. `cloudbuild.yaml`
   actually does **Build → Push → Migrate (inside the built image) → Deploy**.
2. `CICD_SETUP.md` names the secret **`DATABASE_URL`**; `cloudbuild.yaml` and the Cloud Run
   binding use **`database-url`** (the real Secret Manager name).
3. `CICD_SETUP.md` says the image tag is `<SHORT_SHA>`; the pipeline tags `$COMMIT_SHA` (full).
4. `CICD_SETUP.md` grants IAM to `332865216810@cloudbuild.gserviceaccount.com`; the trigger runs
   as `332865216810-compute@developer.gserviceaccount.com` (which holds the roles).
5. `ci.yml` trailing NOTE claims CI has never run on GitHub; `gh run list` shows successful runs.
6. `Hosting_Setup.md` §5 says `https://jokesfor.net` is **not** in the CORS allow-list; live
   preflight from `https://jokesfor.net` now returns `access-control-allow-origin` + credentials
   (env updated since 2026-05-09). The doc is stale on that point.
7. `Hosting_Setup.md` mentions "Cloud SQL / other backend services"; the DB is Neon, not Cloud SQL.
8. `health.py` docstring: "Cloud Run's constant liveness checks" — no liveness probe is configured.
9. Observability design/plan docs mark uptime checks/alerts/log metrics/`SENTRY_DSN` as
   deferred owner actions — still not done (verified).
10. `ops/monitoring/README.md` says max-instances "currently 3" — matches the template; the
    service-level `run.googleapis.com/maxScale: '2'` annotation is stale metadata.
11. `.planning/codebase/*.md` only mention gunicorn generically; no infra content to contradict.
12. `firebase.json` intends `no-cache` for the SPA shell, but live `/` and deep routes get
    `max-age=3600` (glob only matches `/index.html`).

---

## 13. Risks / gaps (infra-ops perspective)

* Scale-to-zero + Neon auto-suspend ⇒ 6–11 s first-request latency for essentially every
  visitor at current traffic; `--min-instances=1` and/or Neon suspend timeout increase are the
  documented fixes, neither applied.
* No `CONN_MAX_AGE` ⇒ ~230 ms per request of Neon TLS handshake overhead on warm instances.
* `containerConcurrency 80` vs 8 gunicorn slots — under load requests queue inside the
  instance instead of triggering scale-out; combined with `maxScale 3` and 300 s video encodes.
* No liveness probe, no uptime check, no alerts, no dashboards, no log-based metrics,
  Sentry off ⇒ outages are only visible by manual observation.
* `/healthz` is unreachable from the public internet (GFE reserved path) — any external monitor
  pointed at it will be permanently red; use `/readyz`.
* Secrets hygiene: Stripe secret key + webhook secret are plain env vars (visible to anyone with
  `run.services.get`); all four Secret Manager secrets still at version 1 (Resend key flagged
  for rotation in memory notes).
* Runtime SA has `roles/editor` (broad blast radius if the container is compromised).
* CI (both repos) does not gate deployment: backend Cloud Build fires on push to `main`
  regardless of GitHub CI; frontend merge workflow has no lint/test step.
* `docker build --no-cache` on every deploy — slower/more expensive builds than necessary.
* `.dockerignore` misses `tests.py` / `tests_*.py` modules (image carries test code; harmless).
* `www.jokesfor.net` is in `ALLOWED_HOSTS` but not served by Firebase Hosting (TLS failure).
* Frontend SPA shell cached 1 h at CDN/browser for `/` and deep routes despite the intended
  `no-cache` rule.
* Cloud Scheduler API not enabled — prerequisite for activating digests.
* gcloud default configuration on this machine points at project `epigraphyatlas`; all
  JokesFor commands need `--project jokesfor` (easy to run against the wrong project).

---

## 13b. Addendum — idle-latency probe (this session) and cold-start breakdown

* Cold `/readyz` at `2026-08-25T08:26:07Z` (first request after the `08:25:50` container start):
  app-measured total **9877 ms**, of which the `SELECT 1` DB check alone reported
  **2999.62 ms** (Neon compute resume — the endpoint's `started_at` is `08:26:06Z`); every
  subsequent warm `/readyz` reports `db ≈ 215–300 ms`.
* After **240 s idle** (no traffic from anyone): `/readyz` 0.97 s / 0.97 s end-to-end — same
  container instance (no new STARTUP line in Cloud Logging), Neon still active (db 224–249 ms).
  So a 4-minute gap is fully warm.
* After a further **420 s idle (≈ 11 min since the previous request, ≈ 18 min since container
  start)**: `/readyz` 0.97 s / 1.22 s — still warm (Cloud Run had not yet reclaimed the idle
  instance and Neon had not suspended). A true cold start therefore needs a longer gap
  (Cloud Run idle reclaim is typically ~15 min *after the last request*; Neon default
  auto-suspend is 5 min but did not fire here — it may have been kept alive by the DatabaseCache
  traffic of the probes themselves). The 5.5–11 s cold numbers in §10 come from Cloud Logging
  over the past week, not from this session's synthetic idle.

## 14. Read-only commands used (for reproducibility)

```
gcloud config list; gcloud auth list; gcloud projects list
gcloud run services list --platform managed --project jokesfor
gcloud run services describe jokesforbackend --region us-east1 --project jokesfor --format=yaml
gcloud run revisions list --service jokesforbackend --region us-east1 --project jokesfor
gcloud run services get-iam-policy jokesforbackend --region us-east1 --project jokesfor
gcloud secrets list --project jokesfor; gcloud secrets versions list <name> --project jokesfor
gcloud builds triggers list/describe … --project jokesfor --region global
gcloud builds list --project jokesfor --limit 5
gcloud logging metrics list; gcloud monitoring dashboards list; gcloud monitoring uptime list-configs
gcloud scheduler jobs list --location us-east1 (API disabled)
gcloud storage buckets list; gcloud artifacts repositories list; gcloud services list --enabled
gcloud projects get-iam-policy jokesfor
gcloud logging read '… textPayload:"STARTUP" …' / '… jsonPayload.latency_ms>5000 …' / '… logName:"requests" …'
gh run list --repo Nard248/JokesForBackEnd|JokesFor-Front; gh variable list; gh secret list (names only)
curl -D - https://jokesforbackend-332865216810.us-east1.run.app/{healthz,readyz,...}
Neon MCP: list_projects, list_branch_computes (read-only)
```
