# JokesFor — Local Full-Stack E2E Runbook (derived from code, not executed)

Analyzer key: `local-dev-runbook`  
Date: 2026-08-25  
Backend repo: `/Users/narekmeloyan/PycharmProjects/JokesForProject` (Django 5.2.17, DRF 3.16, Python 3.11.0 in `.venv`)  
Frontend repo: `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend` (Vite 7, React 19, Node v22.16.0)

Everything below is derived from reading code/config. Nothing was started, migrated, or written. The only live checks performed were read-only: `pg_isready`, `SELECT`s on the local Postgres, `lsof` on ports, `which`, and Python `import` probes in the venv.

---

## 0. TL;DR — the exact command set

```bash
# ── 0. Free the ports (see §1.3: 8000 and 5173 are currently held by ANOTHER project) ──
kill 85134   # "python manage.py runserver" from PycharmProjects/WebViewer-V2-BackEnd (holds :8000)
kill 3410    # vite from WebstormProjects/WebViewer-V2-FrontEnd (holds :5173)

# ── 1. Backend, forced onto LOCAL Postgres, console email, no Stripe/Vision/GCS ──
cd /Users/narekmeloyan/PycharmProjects/JokesForProject
export DATABASE_URL=                      # empty string => settings falls back to DB_* (local)
export EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib   # cairosvg needs libcairo (share cards)
export STRIPE_SECRET_KEY=                 # optional: dormant billing (503s) — omit to keep sk_test_ from .env
export FRONTEND_URL=http://localhost:5173 # password-reset links + CSRF_TRUSTED_ORIGINS seed

.venv/bin/python manage.py migrate --noinput            # local DB already at jokes 0033; safe/no-op
.venv/bin/python manage.py setup_social_app             # syncs Site#1 + Google SocialApp to .env (local DB row is STALE, see §5)
.venv/bin/python manage.py seed_achievements            # idempotent (12 rows already present locally)
.venv/bin/python manage.py seed_demo_creator            # idempotent; demo.creator@jokesfor.dev / DemoCreator!2026
.venv/bin/python manage.py createsuperuser --email admin@localhost --username admin   # local DB has 0 superusers
.venv/bin/python manage.py runserver 8000               # http://localhost:8000

# ── 2. Frontend, mocks OFF, real create + preferences ON ──
cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend
VITE_API_URL=http://localhost:8000/api/v1 \
VITE_USE_MOCKS=false \
VITE_USE_REAL_PREFERENCES=true \
VITE_USE_REAL_CREATE=true \
VITE_GOOGLE_OAUTH_REDIRECT_URI= \
npm run dev -- --strictPort --port 5173      # http://localhost:5173  (strictPort: never drift to 5174 -> CORS breaks)
```

Verification (§8): `curl -s localhost:8000/healthz` → `{"status":"ok"}`; `curl -s localhost:8000/readyz` → `{"status":"ready",...}`; `curl -s localhost:5173/ | grep -c '<div id="root">'` → 1.

---

## 1. Preconditions (verified read-only on this machine)

### 1.1 Toolchain present
| Need | Found | Evidence |
|---|---|---|
| Python venv | `.venv` → Python 3.11.0; `django 5.2.17`, `stripe`, `anymail`, `storages`, `pgtrigger`, `freezegun`, `google.cloud.vision/storage` import OK | `.venv/bin/python -c "import ..."` |
| **cairosvg** (share cards) | **FAILS by default**: `cannot load library 'libcairo-2.dll'`. Works with `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` (brew `cairo 1.18.4`, `/opt/homebrew/lib/libcairo.2.dylib` exists) | import probe with/without env |
| Postgres | `pg_isready localhost:5432 - accepting connections`; `/opt/homebrew/bin/psql` | |
| ffmpeg / ffprobe | `/opt/homebrew/bin/ffmpeg`, `/opt/homebrew/bin/ffprobe` (video/audio/GIF upload pipeline shells out: `jokes/media_probe.py:38`, `jokes/media_processing.py:237`) | |
| Node / npm | v22.16.0 / 11.7.0; `node_modules` present in frontend | |
| Stripe CLI | `/opt/homebrew/bin/stripe` (for webhook forwarding, §6) | |

### 1.2 Local database state (`postgres/6969@localhost:5432/jokesfor`)
| Table | Count / note |
|---|---|
| `jokes_joke` | **304** (all `is_removed=false`); 17 have `creator_id` (the demo creator's 14 + 3 others); only 3 have a `share_image` |
| `auth_user` | 117 total; **101** are `@jokesfor.dev` seed accounts; **0 superusers** |
| `django_site` id=1 | `localhost:8000` / "Jokes For (Development)" |
| `socialaccount_socialapp` | 1 row, provider=google, **client_id `738592872836-…`** — does NOT match `.env` `GOOGLE_CLIENT_ID` (`332865216810-7kou…`) → run `setup_social_app` (§5) |
| `billing_plan` | `free` (default), `supporter` (500¢), `creator_pro` (1500¢); **all `stripe_price_id` blank** |
| `jokes_achievement` / `jokes_vibe` / `jokes_jokepack` | 12 / 12 / 4 |
| `jokes_format` slugs | oneliner, setup-punchline, short-story, setup, knock, story, anti, observ, image, video, audio |
| `jokes_jokesubmission` | draft 2, pending 1, published 17 |
| `jokes_mediaasset` | 4 (files under `./media/media-assets/<uuid>/`) |
| `django_migrations` | jokes at `0033_jokewatch` (head), notifications 2 (cache table exists), billing 3. Stale `django_celery_beat`/`django_celery_results` rows exist from an older era — harmless (apps no longer installed). |

### 1.3 Ports — CURRENTLY OCCUPIED BY A DIFFERENT PROJECT
`lsof` shows:
- `:8000` ← PID 85134 `python manage.py runserver`, cwd `/Users/narekmeloyan/PycharmProjects/WebViewer-V2-BackEnd`
- `:5173` ← PID 3410 `vite`, cwd `/Users/narekmeloyan/WebstormProjects/WebViewer-V2-FrontEnd`

These must be stopped (owner action) before the runbook. Using alternate ports is NOT a drop-in workaround because:
- backend CORS defaults are hardcoded to `http://localhost:5173` / `http://127.0.0.1:5173` (`settings.py:340-343`), and
- `GOOGLE_OAUTH_CALLBACK_URL` (`.env`) is `http://localhost:5173/auth/google/callback`.
If you must use other ports, add `CORS_ALLOWED_ORIGINS=http://localhost:5174 CSRF_TRUSTED_ORIGINS=http://localhost:5174 GOOGLE_OAUTH_CALLBACK_URL=http://localhost:5174/auth/google/callback` to the backend env and `VITE_API_URL=http://localhost:8001/api/v1` on the frontend.

### 1.4 Always use `localhost` on BOTH sides
Auth is cookie-based (`jokes-access-token`, `jokes-refresh-token`, `csrftoken`) with `SameSite=Lax`, `Secure=False` under `DEBUG=True` (`settings.py:386-391, 441-442`). Cookies are host-scoped: opening the SPA at `127.0.0.1:5173` while the API is `localhost:8000` breaks login persistence. Use `http://localhost:5173` and `http://localhost:8000/api/v1`.

---

## 2. Backend settings — how the DB is chosen and how to force LOCAL without editing `.env`

### 2.1 The selection logic (`JokesForProject/settings.py:141-171`)
```python
def _build_default_db():
    url = os.getenv('DATABASE_URL', '').strip()
    if not url:
        return {... 'NAME': os.getenv('DB_NAME','jokesfor'), 'USER': os.getenv('DB_USER','postgres'),
                'PASSWORD': os.getenv('DB_PASSWORD',''), 'HOST': os.getenv('DB_HOST','localhost'),
                'PORT': os.getenv('DB_PORT','5432')}
    parsed = urlparse(url) ...   # Neon; '-pooler' host => DISABLE_SERVER_SIDE_CURSORS=True
```
- `DATABASE_URL` wins whenever non-empty (after `.strip()`).
- `.env` currently sets **both**: `DATABASE_URL=postgresql://…@ep-round-brook-aq0p3j8j-pooler.c-8.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require` (PROD Neon) **and** `DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432`.
- Therefore, **by default every `manage.py` invocation in this repo hits production Neon.** The `.env` comment (`WARNING: registrations now send REAL emails AND … create REAL users in the production DB`) confirms this.

### 2.2 Why a shell override works (python-dotenv semantics)
`settings.py:22` calls `load_dotenv()` with the default `override=False` (`.venv/.../dotenv/main.py:387`). A variable already present in the process environment is **not** replaced by `.env`. So exporting `DATABASE_URL=` (empty string) on the command line makes `os.getenv('DATABASE_URL','').strip()` return `''` → local `DB_*` branch. The `DB_*` values still come from `.env` (they are not in the process env), i.e. `jokesfor/postgres/6969@localhost:5432`.

Canonical one-liner (this exact form is documented in `jokes/management/commands/seed_demo_creator.py:11-14`):
```bash
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 \
  .venv/bin/python manage.py <command>
```
(`DATABASE_URL=` alone is sufficient given the current `.env`; the explicit `DB_*` are belt-and-braces.)

Tests: there is no pytest config (no `pytest.ini`/`[tool.pytest]`); the runner is `manage.py test`. Django creates `test_jokesfor` on whatever DB is selected, so the same `DATABASE_URL=` override is REQUIRED to keep tests off Neon (local `postgres` role is superuser → CREATEDB OK).

### 2.3 Other env-driven switches relevant locally (all in `settings.py`)
| Var | `.env` value | Effect | Line |
|---|---|---|---|
| `DEBUG` | `True` | `SECRET_KEY` fallback allowed, cookies non-Secure, HSTS/SSL-redirect off, plain-text logs | 32-42, 390-414, 548-550 |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | | 44 |
| `CORS_ALLOWED_ORIGINS` | `https://jokesforfront.web.app` (APPENDED to hardcoded `localhost:5173`, `127.0.0.1:5173`) | `CORS_ALLOW_CREDENTIALS=True`; `x-csrftoken` header allowed | 340-352 |
| `CSRF_TRUSTED_ORIGINS` | `https://jokesforfront.web.app,http://localhost:5173,http://127.0.0.1:5173` (+ `FRONTEND_URL` auto-appended) | Origin check for cookie-auth mutations | 369-371 |
| `FRONTEND_URL` | unset → default `https://jokesforfront.web.app` | Password-reset email links point at PROD SPA unless overridden → set `FRONTEND_URL=http://localhost:5173` for local reset-flow tests | 357 |
| `JWT_COOKIE_SAMESITE` | `Lax` | correct for localhost↔localhost | 386, 442 |
| `EMAIL_BACKEND` | `anymail.backends.resend.EmailBackend` (REAL sends) | override to console (§3) | 474-476 |
| `EMAIL_VERIFICATION_REQUIRED` | `true` | gated registration | 483 |
| `GS_BUCKET_NAME` | unset | `FileSystemStorage` → `./media` | 241-281 |
| `SAFESEARCH_ENABLED` | unset | Vision screening returns `{'status':'skipped'}` | 286; `jokes/media_screening.py:36-37` |
| `STRIPE_SECRET_KEY` | `sk_test_…` (test mode) | billing ENABLED locally (§6) | 508 |
| `BILLING_*_URL` | unset → `http://localhost:5173/billing/success|cancel`, `/account` | already local-correct | 513-515 |
| `BILLING_ENABLED` | unset | **not used for gating** (only `STRIPE_SECRET_KEY` is; confirmed by grep + `Docs/STRIPE_GOLIVE.md`) | 512 |
| `SENTRY_DSN` | unset | Sentry no-op | 631 |
| `DIGEST_CRON_TOKEN` | unset | `/api/v1/internal/run-digests/` 404s for everyone | 505 |
| `GOOGLE_OAUTH_CALLBACK_URL` | `http://localhost:5173/auth/google/callback` | must equal the SPA's redirect_uri (§5) | 541 |
| `SITE_DOMAIN`/`SITE_NAME` | `localhost:8000` / `JokesFor (dev)` | consumed only by `setup_social_app` | — |
| Throttles | hardcoded: anon `100/hour`, user `1000/hour`, `media-upload 30/hour`, `tips-checkout 30/hour`, `verification_resend 3/15min`, `appeals 10/day` | NOT env-tunable; counters live in the `jokesfor_cache` DatabaseCache table | 303-316, 187-194 |

Throttle note for automated E2E: an anonymous test run that fires >100 API calls/hour from one IP will start receiving 429s. Reset between runs with `DATABASE_URL= .venv/bin/python manage.py shell -c "from django.core.cache import cache; cache.clear()"` (or run authenticated: 1000/hour).

Cache/readiness: `readyz` (`JokesForProject/health.py:45`) does `SELECT 1` + a `cache.set/get/delete` round-trip on `jokesfor_cache`; the table is created by `notifications/migrations/0002_create_cache_table.py` (applied locally).

---

## 3. Email locally — console backend + how to verify an address without Resend

### 3.1 Switch the transport
`EMAIL_BACKEND` defaults to console (`settings.py:474-476`) but `.env` overrides it to Resend with a real key. Force console per-process:
```bash
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```
`notifications/service.py:21-50` still writes an `EmailMessageLog` row (`status='sent'`) — the console backend never raises, so the gated flow behaves exactly as in prod minus the network.

### 3.2 What the gated registration flow does (`jokes/views.py:821-890`)
- `EMAIL_VERIFICATION_REQUIRED=true` → `POST /api/v1/auth/registration/ {email,password1,password2,date_of_birth}` creates the user with `is_active=False`, calls `verification.issue_and_send(user)` and returns **201 `{detail:'Verification code sent to your email.', email}` with NO cookies**.
- `date_of_birth` is REQUIRED; under-13 → 400 (`JokesForProject/serializers.py:58-69`).
- `POST /api/v1/auth/verify-email/ {email, code}` (`notifications/views.py:39-83`) → sets `is_active=True`, returns 200 `{user:{id,email}}` and SETS the JWT cookies.
- `POST /api/v1/auth/resend-verification/ {email}` re-issues (throttled `3/15min`).
- An unverified user cannot log in: dj-rest-auth's `LoginSerializer` rejects `is_active=False` with "User account is disabled." (`.venv/.../dj_rest_auth/serializers.py:111-112`).
- Code: 6 digits, SHA-256 hashed at rest (`notifications/verification.py:22-48`), TTL `EMAIL_VERIFICATION_CODE_TTL_MINUTES` (default 10), `EMAIL_VERIFICATION_MAX_ATTEMPTS` (default 5).

### 3.3 Reading the code locally (three options)
1. **Console output.** The runserver stdout prints the text body from `notifications/templates/notifications/email/verification_code.txt`; the line is literally `Your code: 123456`. Grep the server log: `grep -o 'Your code: [0-9]\{6\}' backend.log | tail -1`.
2. **Issue a fresh code from a shell (no email needed)** — `issue_code` returns plaintext and invalidates prior codes:
   ```bash
   DATABASE_URL= EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend \
   .venv/bin/python manage.py shell -c "from django.contrib.auth import get_user_model as G; from notifications.verification import issue_code; print(issue_code(G().objects.get(email__iexact='e2e@test.local')))"
   ```
   Then `POST /auth/verify-email/` with it — this exercises the real verify path.
3. **Bypass entirely (test seeding only):** `User.objects.filter(email__iexact='...').update(is_active=True)`.
   There is **no management command** for verifying/activating a user; the code hash cannot be recovered from the DB.

### 3.4 Legacy (ungated) mode
`EMAIL_VERIFICATION_REQUIRED=false` on the command line → registration returns 201 with cookies immediately (`jokes/views.py:836-851`). Useful for tests that don't care about verification. The frontend already handles both shapes (`src/features/auth/api.ts:60-76` checks `'access' in data`).

Password reset locally: `POST /auth/password/reset/` emails a link built from `FRONTEND_URL` (`jokes/password_reset.py` via `REST_AUTH.PASSWORD_RESET_SERIALIZER`) — set `FRONTEND_URL=http://localhost:5173` or the printed link points at prod.

---

## 4. Stripe — test-mode requirements

Gating is purely `bool(settings.STRIPE_SECRET_KEY)` (`billing/stripe_gateway.py:15-16`). `.env` has `sk_test_…`, `pk_test_…`, `whsec_…` → billing is **live in test mode** locally by default.

| Endpoint | Dormant (`STRIPE_SECRET_KEY=`) | With `sk_test_` |
|---|---|---|
| `GET /api/v1/billing/plans` | works (seeded plans) | same |
| `GET /billing/my-subscription`, `/billing/entitlements` | work | same |
| `POST /billing/checkout-session {plan_slug}` | 503 `{code:'billing_unavailable'}` | **422 "This plan is not yet available for purchase."** because local `billing_plan.stripe_price_id` is blank for all plans (`billing/views.py` checkout: `if not plan.stripe_price_id: 422`). Fix: Django admin `/admin/billing/plan/` → action "Push to Stripe" (`billing/admin.py:51`, needs superuser) or paste a test `price_…` id. |
| `POST /billing/portal-session` | 503 | needs an existing Stripe customer on the user's Subscription |
| `POST /api/v1/tips/checkout/ {creator_id, joke_id?, amount_cents∈{100,300,500,1000}}` | 503 | **works with no plan mapping** — uses inline `price_data` (`billing/stripe_gateway.py:79-133`), returns a Checkout `url`; success/cancel redirect to `http://localhost:5173/billing/success|cancel` |
| `POST /api/v1/billing/webhook` | 200 `{detail:'billing_dormant'}` | signature-verified against `STRIPE_WEBHOOK_SECRET`; forward with `stripe listen --forward-to localhost:8000/api/v1/billing/webhook` and export the CLI's `whsec_` as `STRIPE_WEBHOOK_SECRET` (the `.env` value belongs to the prod/dashboard endpoint and will NOT verify CLI-forwarded events) |

Checkout completion itself (card entry on `checkout.stripe.com`, test card `4242…`) is a hosted Stripe page — automatable with Playwright but it is an external dependency; the state transition (`Tip.status='pending'→'paid'`, `Subscription` upsert) only happens via the webhook.

---

## 5. Google OAuth locally

Flow (`src/features/auth/google-oauth.ts`, `src/pages/GoogleCallbackPage.tsx`, `jokes/views.py:893-927`):
1. SPA builds the consent URL with `VITE_GOOGLE_CLIENT_ID` and `redirect_uri = VITE_GOOGLE_OAUTH_REDIRECT_URI || window.location.origin + '/auth/google/callback'` → locally `http://localhost:5173/auth/google/callback` (keep `VITE_GOOGLE_OAUTH_REDIRECT_URI` EMPTY — `.env` already does).
2. Google redirects back with `?code=…`; the page POSTs `{code, redirect_uri, date_of_birth?}` ONCE to `POST /api/v1/auth/google/`.
3. Backend (`GoogleLogin`) redeems the code with `callback_url = settings.GOOGLE_OAUTH_CALLBACK_URL`. dj-rest-auth 7.0.2 **ignores the body's `redirect_uri`** (`dj_rest_auth/registration/serializers.py:66-78` reads `view.callback_url` only), so the backend env value must equal the SPA's URI exactly → `.env` `GOOGLE_OAUTH_CALLBACK_URL=http://localhost:5173/auth/google/callback` ✓.
4. Client id/secret come from the DB `SocialApp` bound to `Site` id 1 (allauth). **The local DB row has client_id `738592872836-…`, while `.env` and the frontend both use `332865216810-7kouajjg51jiceqk4g2h0qa3t3nbk4ga`** → run `DATABASE_URL= .venv/bin/python manage.py setup_social_app` (`jokes/management/commands/setup_social_app.py`: `update_or_create` Site#1 from `SITE_DOMAIN/SITE_NAME`, SocialApp from `GOOGLE_CLIENT_ID/SECRET`). Without this, the code exchange fails.
5. COPPA gate: new Google users must send `date_of_birth`; missing → 400 `{code:'dob_required'}`; <13 → 400 `{date_of_birth:[…]}` (`JokesForProject/adapters.py`). The SPA stashes DOB in `sessionStorage` before redirecting.

What can be tested locally: everything up to and including the backend's error branches with a fake `code` (expect 400 from Google token exchange), the `dob_required` / under-13 paths need a valid code so they are effectively **prod/manual-only**. The Google consent screen requires a real Google account + the GCP OAuth client having `http://localhost:5173/auth/google/callback` registered (the handout `Docs/API/Frontend_Integration_Handout.md:158` says "plus localhost variants" are registered — not verifiable from code).

---

## 6. Media locally

- Storage: `GS_BUCKET_NAME` empty → `FileSystemStorage`, `MEDIA_ROOT=<repo>/media`, `MEDIA_URL=/media/` (`settings.py:237-281`). Uploads land at `media/media-assets/<uuid>/<name>`, share cards at `media/share-cards/joke-<pk>.png`.
- **Local serving gap:** `JokesForProject/urls.py` has **no** `static(settings.MEDIA_URL, document_root=MEDIA_ROOT)` and WhiteNoise only serves `STATIC_ROOT`. Serializers return `request.build_absolute_uri(field_file.url)` (`jokes/serializers.py:156,250,388`) → `http://localhost:8000/media/...` which **404s under runserver**. Media-joke images/posters/share-card `og:image` will be broken in the local SPA; the upload/draft/submit/approve DATA flow still works. (Docs and code agree that local dev uses the filesystem, but neither adds a dev-only media route.)
- Screening: `SAFESEARCH_ENABLED` unset → `screen_image()` returns `{'status':'skipped'}` before touching Vision (`jokes/media_screening.py:36-37`); no ADC needed. Even when enabled, thrown client errors fail OPEN (`status:'error'`). Hash matcher is a `NullMatcher`. So locally every image passes automated screening; the human review queue (admin) remains the publish gate.
- Pipeline deps: Pillow for images (max 10 MB, ≤4096px source, 1600px output); ffprobe/ffmpeg for video (30 MB), GIF (15 MB), audio (10 MB), 60 s max (`jokes/media_processing.py:17-19,140-144`). Both binaries present.
- Endpoint: `POST /api/v1/media/uploads/` multipart `file` + `kind∈{image,video,audio}`; `IsAuthenticated`; scoped throttle `media-upload 30/hour`; 422 on screening block; 429 on throttle.
- Share cards: `Joke.save()` for a NEW joke (or text change / missing card) calls `cairosvg` (`jokes/models.py:191-252`, `jokes/share_cards.py:6`). Without `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` this raises on this Mac → affects `seed_jokes` (uses `Joke.objects.create`), admin `approve_and_publish` (`jokes/admin.py:322`), `backfill_share_cards --apply`. `seed_demo_creator` uses `bulk_create` and is unaffected (which is why 14 of its 17 creator jokes have no card).

---

## 7. Seed / demo data commands (`jokes/management/commands/`) and fixtures

| Command | What it does | Accounts / credentials | Idempotent? |
|---|---|---|---|
| `migrate` | Data migrations already seed: taxonomy + 12 vibes + ~150 jokes + 4 packs (`jokes/migrations/0013_seed_vibes.py`, `0021_seed_demo_data.py`), `image/video/audio` formats (`0031`, `0032`), 3 billing plans (`billing/0002_seed_plans.py`) + `free_joke_reads_per_day=10` on free (`billing/0003`), cache table (`notifications/0002`). | none | yes (update_or_create) |
| `seed_achievements` | upserts 12 `Achievement` rows | none | yes |
| `seed_demo_creator [--email] [--password] [--jokes 14] [--viewers 140] [--days 30] [--fresh]` | creates creator **`demo.creator@jokesfor.dev` / `DemoCreator!2026`** (display "Dara Punwell", handle `@darapun`, `is_active=True`, `public_profile=True`), 14 tier_1 published jokes with backdated impressions/views/dwells/reactions/saves/favs/shares, ~140 viewer users `demo.viewer.<pk>.<i>@jokesfor.dev` (unusable password `!`), 72–90% of them following. Prints a `build_creator_insights` summary. `--fresh` wipes ALL `@jokesfor.dev` users first. Already present locally (user id 582 → 101 seed accounts). | `demo.creator@jokesfor.dev` / `DemoCreator!2026` (`seed_demo_creator.py:51-52`) | yes (resets its own jokes/viewers each run) |
| `seed_jokes [--count 150] [--clear]` | loads `jokes/fixtures/jokes.json` (137 `jokes.joke` entries) via `Joke.objects.create` → **needs cairo** and requires lookup tables populated (else `CommandError: … Run "python manage.py loaddata lookup_data" first`). `--clear` deletes ALL jokes. Fixture FK ids (format 1/2, age_rating 1-4…) refer to `lookup_data.json` pks; the migration-seeded taxonomy already occupies those ids with different slugs, so loading it on the current DB is **not recommended** (would mis-tag; `loaddata lookup_data` would also overwrite names of pk 1-3 formats). Legacy path; not needed — DB already has 304 jokes. | none | no (duplicates on re-run) |
| `loaddata lookup_data` | 27 rows: formats/age ratings/tones/context tags/culture tags/languages/sources (`jokes/fixtures/lookup_data.json`) | none | overwrites by pk |
| `setup_social_app` | Site#1 + Google SocialApp from env (§5) | none | yes |
| `backfill_share_cards [--apply] [--only-media] [--limit N]` | dry-run by default; regenerates cards for live jokes with blank `share_image` (301 locally) — needs cairo | none | yes |
| `createsuperuser` | needed for `/admin/` (moderation queue: `JokeSubmissionAdmin.approve_and_publish`, appeals, `ContentReportAdmin.take_down_joke`, Plan "Push to Stripe"). **No superuser exists locally**; no code defines a default admin credential. | choose your own | — |

Other pre-existing local test accounts (from earlier manual runs, passwords unknown/not in code): `test2@example.com`, `smoke@test.local`, `apitest_*`, `flowtest_28848@example.com`, `meloyann87@gmail.com`, … Some are `is_active=False` (`apitest_6588`, `throttle_8395`, `attempts_32275`). Treat as disposable.

Recommended E2E account strategy: register fresh `e2e+<ts>@test.local` accounts through the real gated flow (verify via §3.3), plus `demo.creator@jokesfor.dev` for creator-side pages (`/create`, `/create/insights`, `/creators/<id>`), plus a `createsuperuser` admin for moderation approvals.

---

## 8. Ordered runbook with verification at each layer

### Step 1 — free ports (owner)
```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN; lsof -nP -iTCP:5173 -sTCP:LISTEN   # expect empty after kill
```

### Step 2 — DB reachable, and confirm the override actually selects local
```bash
pg_isready -h localhost -p 5432                                        # "accepting connections"
PGPASSWORD=6969 psql -h localhost -U postgres -d jokesfor -Atc 'select count(*) from jokes_joke'   # 304
cd /Users/narekmeloyan/PycharmProjects/JokesForProject
DATABASE_URL= .venv/bin/python manage.py shell -c "from django.conf import settings as s; d=s.DATABASES['default']; print(d['HOST'], d['NAME'])"
# MUST print: localhost jokesfor   (anything containing neon.tech => override not applied)
DATABASE_URL= .venv/bin/python manage.py showmigrations --plan | grep -c '\[ \]'   # 0 unapplied
```

### Step 3 — one-time local prep (all with `DATABASE_URL=` prefix)
```bash
export DATABASE_URL= EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib FRONTEND_URL=http://localhost:5173
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py setup_social_app
.venv/bin/python manage.py seed_achievements
.venv/bin/python manage.py seed_demo_creator          # (or --fresh to rebuild the 101 seed users)
.venv/bin/python manage.py createsuperuser            # interactive; or DJANGO_SUPERUSER_PASSWORD=... createsuperuser --noinput --username admin --email admin@localhost
.venv/bin/python manage.py backfill_share_cards --apply --limit 20   # optional: gives some jokes a share card
.venv/bin/python manage.py check                      # "System check identified no issues"
```

### Step 4 — run backend
```bash
.venv/bin/python manage.py runserver 8000 2>&1 | tee /tmp/backend.log
```
Verify:
```bash
curl -s http://localhost:8000/healthz                      # {"status":"ok"}
curl -s http://localhost:8000/readyz                       # {"status":"ready","checks":{"db":{"status":"ok"...},"cache":{"status":"ok"...}},"version":"unknown"}
curl -s 'http://localhost:8000/api/v1/jokes/?page_size=1' | head -c 300   # {"count":304,...}
curl -s http://localhost:8000/api/v1/jokes/daily-reads/    # {"limit":10,"used":0,"remaining":10,"over":false,"reset_at":"...T00:00:00+00:00"}
curl -s http://localhost:8000/api/v1/billing/plans | head -c 200          # [{"slug":"free",...
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/schema/  # 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/sitemap.xml  # 200
# CORS preflight from the SPA origin:
curl -s -i -X OPTIONS http://localhost:8000/api/v1/auth/login/ -H 'Origin: http://localhost:5173' -H 'Access-Control-Request-Method: POST' -H 'Access-Control-Request-Headers: content-type,x-csrftoken' | grep -i 'access-control-allow-origin'   # http://localhost:5173
```
Auth smoke via curl (cookie jar):
```bash
J=/tmp/jar; B=http://localhost:8000/api/v1
curl -s -c $J -b $J $B/auth/csrf/                          # {"csrfToken":"..."}  (+ csrftoken cookie)
curl -s -c $J -b $J -X POST $B/auth/registration/ -H 'Content-Type: application/json' \
  -d '{"email":"e2e1@test.local","password1":"Str0ng-Pass-123","password2":"Str0ng-Pass-123","date_of_birth":"1995-05-05"}'
# 201 {"detail":"Verification code sent to your email.","email":"e2e1@test.local"} — code printed in /tmp/backend.log
CODE=$(grep -o 'Your code: [0-9]\{6\}' /tmp/backend.log | tail -1 | awk '{print $3}')
curl -s -c $J -b $J -X POST $B/auth/verify-email/ -H 'Content-Type: application/json' -d "{\"email\":\"e2e1@test.local\",\"code\":\"$CODE\"}"
# 200 {"user":{"id":..,"email":..}} + Set-Cookie jokes-access-token / jokes-refresh-token
curl -s -c $J -b $J -X POST $B/auth/token/refresh/ -H 'Content-Type: application/json' -d '{}'   # {"access":"..."} (not CSRF-checked)
curl -s -b $J $B/auth/user/                                # {"pk":..,"email":..,"date_of_birth":"1995-05-05"}
# cookie-auth mutation MUST carry X-CSRFToken (JWT_AUTH_COOKIE_USE_CSRF=True):
T=$(curl -s -b $J -c $J $B/auth/csrf/ | sed 's/.*"csrfToken":"\([^"]*\)".*/\1/')
curl -s -b $J -X POST $B/jokes/1/reveal/ -H "X-CSRFToken: $T" -H 'Content-Type: application/json' -d '{}'   # 200 paywall payload; without header => 403 "CSRF Failed"
curl -s -c $J -b $J -X POST $B/auth/login/ -H 'Content-Type: application/json' -d '{"email":"demo.creator@jokesfor.dev","password":"DemoCreator!2026"}' | head -c 200   # 200 {"access":..,"refresh":..,"user":{...}}
```

### Step 5 — run frontend (mocks OFF)
`.env` currently: `VITE_API_URL=http://localhost:8000/api/v1`, `VITE_USE_MOCKS=true`, `VITE_GOOGLE_OAUTH_REDIRECT_URI=` (blank), `VITE_USE_REAL_PREFERENCES` unset, `VITE_USE_REAL_CREATE` unset. Vite reads shell env over `.env` (Vite: process env has priority), so:
```bash
cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend
VITE_API_URL=http://localhost:8000/api/v1 VITE_USE_MOCKS=false VITE_USE_REAL_PREFERENCES=true VITE_USE_REAL_CREATE=true \
  npm run dev -- --strictPort --port 5173
```
Alternative without shell noise: create `.env.local` (gitignored by Vite convention; check `.gitignore` before committing) with those four lines — it overrides `.env`.

What each flag gates (code):
- `VITE_USE_MOCKS==='true'` or empty `VITE_API_URL` → `USE_MOCKS` in `src/lib/api-adapter.ts:33-34` (jokes, daily joke, collections, saved, trending, favorites, drafts, profile, insights, follows, creator profile, billing, tips, notifications, moderation, appeals); same gate copied in `src/features/daily-reads/api.ts:16` (paywall nudge OFF under mocks), `src/features/tips/TipButton.tsx:11`, `src/features/telemetry/recordShare.ts:6`, `src/lib/telemetry.ts:55`, `src/pages/BillingPage.tsx:19`.
- `VITE_USE_REAL_PREFERENCES==='true' || !USE_MOCKS` → real `/users/me/preferences/` (`api-adapter.ts:676-677`); with mocks off it is already real, the flag is belt-and-braces (CI sets it too).
- `VITE_USE_REAL_CREATE==='true'` → **independent** of `USE_MOCKS` (`src/features/create/adapter.ts:22`); without it the creator editor uses `mockContentApi` even when everything else is real. Must be set explicitly. Real path hits `/formats/`, `/age-ratings/`, `/tones/`, `/context-tags/`, `/culture-tags/`, `/languages/`, `/jokes/my-drafts/…`, `/media/uploads/` (`src/features/create/api.ts:18-40`).
- Auth (`src/lib/axios.ts`, `src/app/providers/AuthProvider.tsx`) is ALWAYS real (no mock): `baseURL=VITE_API_URL`, `withCredentials:true`, boots with `GET /auth/csrf/` + `POST /auth/token/refresh/` + `GET /auth/user/`.
- Firebase Analytics init (`src/lib/firebase.ts`) runs with the real `jokesforfront` keys in `.env` — gated by `isSupported()`; harmless locally but sends analytics to the prod Firebase project.
- CI/prod build values for reference (`.github/workflows/ci.yml:23-33`): `VITE_USE_MOCKS=false`, `VITE_USE_REAL_PREFERENCES=true`, `VITE_USE_REAL_CREATE=true`, `VITE_GOOGLE_OAUTH_REDIRECT_URI=https://jokesforfront.web.app/auth/google/callback`.

Verify:
```bash
curl -s http://localhost:5173/ | grep -c 'id="root"'        # 1
curl -s http://localhost:5173/src/lib/axios.ts | grep -o 'localhost:8000/api/v1' | head -1   # baseURL fallback visible in dev-served module
# In the browser: DevTools → Network on load shows GET http://localhost:8000/api/v1/auth/csrf/ (200) and POST /auth/token/refresh/ (401 when logged out) — proves mocks are off.
```
Playwright: `playwright.config.ts` uses `baseURL http://localhost:5173`, `webServer: npm run dev` with `reuseExistingServer` (non-CI) — so start the dev server yourself with the env above, then `npx playwright test`; the existing `e2e/example.spec.ts` asserts a legacy hero ("Find Your Perfect Joke") that likely no longer matches the current `LandingPage`.

### Step 6 — key SPA routes to drive (`src/app/routes.tsx`)
`/` (landing, anon) · `/login` · `/register` → `/verify-email?email=…` · `/auth/google/callback` · `/forgot-password`, `/reset-password` · `/search` · `/daily` · `/library` · `/trending` · `/jokes/:id` · `/packs/:slug` · `/creators/:creatorId` · protected: `/flow`, `/explore`, `/favorites`, `/collections`, `/profile`, `/settings`, `/settings/billing`, `/create`, `/create/insights`, `/create/new/:formatSlug`, `/create/:draftId`.

---

## 9. Prod-only / not locally testable

| Capability | Why | Local substitute |
|---|---|---|
| Google consent screen + real code exchange | needs real Google account, GCP client with localhost redirect registered, live `SocialApp` secret | assert `POST /auth/google/` with bogus code → 400; UI-side redirect URL construction |
| Resend delivery, `noreply@jokesfor.net` domain, bounce handling | network + provider | console backend + `EmailMessageLog` rows |
| GCS storage (`GS_BUCKET_NAME`), public `storage.googleapis.com` URLs, `file_overwrite`, quarantine moves within the bucket | ADC/service account; local is `FileSystemStorage` and `/media/` is not even served by runserver | verify DB fields + files on disk under `./media/` |
| Vision SafeSearch (`SAFESEARCH_ENABLED=true`, ADC) | GCP creds; local returns `skipped` | unit tests mock `screen_image` |
| Stripe hosted Checkout / Customer Portal / webhooks | external; local needs `stripe listen` + CLI `whsec_`; checkout for PLANS also needs `stripe_price_id` mapping (blank locally) | tips checkout (`price_data`) creates a real test-mode session; `Tip(pending)` row assertable; dormant-mode 503/200 paths |
| Cloud Scheduler → `/api/v1/internal/run-digests/` (`DIGEST_CRON_TOKEN`) | dormant unless token set; can be exercised locally by exporting a token and POSTing with `X-Digest-Token` | yes, locally testable if token exported |
| Secure/SameSite=None cookies, HSTS, `SECURE_PROXY_SSL_HEADER`, cross-site CSRF (`Origin: https://jokesforfront.web.app`) | only meaningful over HTTPS/cross-eTLD+1 | local is same-site `Lax` |
| Sentry, JSON Cloud Logging format | `SENTRY_DSN` unset; `LOG_FORMAT=plain` in DEBUG | set `LOG_FORMAT=json` to eyeball the formatter |
| Frontend sitemap generation `npm run build` (`prebuild: node scripts/gen-sitemap.mjs`) fetching backend `/sitemap.xml` | build-time; points at whatever `VITE_API_URL`/script default is | run `npm run build` with local env to check it fetches `localhost:8000/sitemap.xml` |

---

## 10. Discrepancies / gotchas found (code vs docs vs environment)

1. **`.env` defaults every local `manage.py` run to PRODUCTION Neon** (both `DATABASE_URL` and `DB_*` present; URL wins). The `DATABASE_URL=` override is mandatory for any local test session. Memory note `project_local_db_test_fallback.md` agrees.
2. **`.env` `EMAIL_BACKEND` sends real Resend email** — override to console for tests.
3. **Ports 8000/5173 are held by another project's servers** (WebViewer-V2) right now.
4. **cairosvg cannot find libcairo** without `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` — any `Joke.save()` that generates a share card (admin approve, `seed_jokes`, `backfill_share_cards`) will 500/raise locally otherwise.
5. **Local `SocialApp` client id is stale** (`738592872836-…` vs `.env`/frontend `332865216810-…`) → `setup_social_app` required before any Google-login attempt.
6. **No `/media/` route in `urls.py`** → local uploaded media and share-card URLs 404 in the browser even though files exist under `./media`.
7. **No superuser in local DB** and no default admin credentials in code → `createsuperuser` needed for admin moderation/approval flows and the "Push to Stripe" action.
8. **Plan checkout returns 422 locally** (blank `stripe_price_id`) even with `sk_test_`; tips checkout works. `.env` `STRIPE_WEBHOOK_SECRET` is not the Stripe-CLI secret.
9. **Frontend `VITE_USE_REAL_CREATE` is a separate switch** from `VITE_USE_MOCKS` and is not typed in `src/vite-env.d.ts` (only `VITE_USE_REAL_PREFERENCES` is) — easy to forget; CI sets it.
10. **`FRONTEND_URL` defaults to prod** → local password-reset emails link to `https://jokesforfront.web.app/reset-password…` unless overridden.
11. **Frontend `.env` contains a `FIGMA_TOKEN`** (`figd_…`) alongside VITE vars — not consumed by the app, but it is a live-looking secret sitting in a file that `Hosting_Setup.md` says is gitignored; worth confirming it is not committed.
12. **`e2e/example.spec.ts` targets legacy landing copy** ("Find Your Perfect Joke", "Search for jokes about...") that predates the conversion `LandingPage`; expect it to fail against the current UI.
13. **`jokes/fixtures/*.json` + `seed_jokes`** predate the migration-seeded taxonomy (different pks/slugs) — do not load them onto the current DB; the 304 jokes already present are the test corpus.
14. Throttle rates are hardcoded (anon 100/h) and shared via the DB cache — long anonymous E2E runs need `cache.clear()` between suites.
15. `Docs/API/Frontend_Integration_Handout.md:158` states the backend `GOOGLE_OAUTH_CALLBACK_URL` is the web.app URL — true for Cloud Run env, but the local `.env` sets the localhost URL; the doc's claim that the SPA-sent `redirect_uri` can override it is wrong for dj-rest-auth 7.0.2 (view `callback_url` wins).
