# Prod-Integrity Fixes (Wave 0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close four live production gaps with zero design decisions: remove the dead Celery stack, harden transport + shared throttle cache + observability, make media storage durable on GCS, and route the frontend Trending/Favorites/Preferences adapters to the real backend.

**Architecture:** Four independent, individually-shippable work-streams. Three are backend (Django/Cloud Run/Neon, honoring the single-app no-worker principle); one is frontend (React/Vite). They share no state and can run in parallel.

**Tech Stack:** Django 5.2 + DRF + Postgres (Neon) + gunicorn/Cloud Run; django-storages[google]; sentry-sdk; React 18 + Vite + TS + vitest.

---

**Sequence within this wave:** celery → hardening (depends on celery for a clean baseline); gcs and unmock run fully in parallel.

---

## Remove the dead Celery stack entirely

**Goal:** Delete the entire (already-dead) Celery integration from the JokesForPeople Django backend — the app factory, the celery_app export, the two unused @shared_task functions, the INSTALLED_APPS entries for django_celery_beat/django_celery_results, the CELERY_* settings block, the .env/.env.example CELERY entries, and the celery-only dependency family from requirements.txt — and prove via `manage.py check` + the full Django test suite (run before and after, against local Postgres) that nothing breaks. Daily-joke generation already happens lazily inside the views, so there is no runtime behavior to preserve.

**Architecture:** Celery is fully vestigial. Grep confirms the two @shared_task functions in jokes/tasks.py (generate_daily_jokes, generate_daily_joke_for_user) are never imported, never enqueued (.delay/.apply_async), and never scheduled (no beat schedule defined in settings — only CELERY_BEAT_SCHEDULER points at the DB scheduler, with no PeriodicTask seeding code in the repo). The DailyJoke feature is served entirely by inline lazy generation in jokes/views.py: DailyJokeViewSet.today/tomorrow create the row on first request (views.py:961, :1004 with the explicit comment 'Lazy-generate (replaces the Celery beat task)'), and the module-level helper _select_daily_joke_for (views.py:2138, comment 'replaces the Celery beat task') does DailyJoke.objects.get_or_create. So deleting tasks.py removes pure dead code with zero runtime impact.

The Django project is a single Cloud Run gunicorn app (wsgi:application). celery.py defines the Celery() app, JokesForProject/__init__.py imports it as celery_app so autodiscover runs at Django startup, and settings.py registers django_celery_beat + django_celery_results in INSTALLED_APPS and defines a CELERY_* block (broker/result backend = redis://localhost). Removing __init__.py's import severs Celery from Django startup; removing the two apps from INSTALLED_APPS stops their migrations/models from loading. wsgi.py and asgi.py contain no celery references, so the gunicorn entrypoint is unaffected.

Dependency analysis (pip reverse-deps) is the one subtlety. The celery-only chain is: celery -> {amqp(via kombu), billiard, kombu, vine, tzlocal, click-didyoumean, click-plugins, click-repl(->prompt-toolkit->wcwidth), click}; redis(->async-timeout); django-celery-beat(->cron-descriptor, python-crontab); django-celery-results. These are all safe to drop. CRITICAL EXCEPTIONS that look celery-related but MUST be kept: python-dateutil and six are required-by svix (svix is pulled by django-anymail[resend], which powers the LIVE email-verification stack), so they stay; packaging is required-by gunicorn so it stays. Removing python-dateutil/six would break the email path — do not remove them.

Migration/orphan-table note: django_celery_beat and django_celery_results created their tables in the DB (local + Neon prod) when they were last migrated. Django does not auto-drop tables for removed apps. Recommended (YAGNI): just remove the apps and leave the orphan tables in place — they are inert and harmless on Neon; no data migration needed. Document this in the commit body. Optionally a follow-up raw-SQL cleanup could DROP them, but that is out of scope for closing this gap.

Test harness: no pytest is installed and there is no pytest config — the project uses Django's built-in runner (`manage.py test`). settings.py calls load_dotenv(), and .env sets DATABASE_URL to Neon (which _build_default_db() prefers), so tests must override DATABASE_URL to empty to fall back to local Postgres (postgres/6969@localhost/jokesfor), which is confirmed reachable. Baseline `manage.py check` already passes (0 issues).

**Tech Stack:** Django 5.2.10 + DRF 3.16, Python 3.11, single gunicorn app on Google Cloud Run, Neon Postgres (local Postgres for tests), Anymail->Resend for live email. Tests via Django's built-in manage.py test runner against local Postgres. No pytest, no Celery/Redis/cron/workers (being removed).

**Files:**

| Action | Path | Responsibility |
|---|---|---|
| delete | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/celery.py` | Celery app factory (Celery() + config_from_object + autodiscover_tasks). Fully dead — delete the file. |
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/__init__.py` | Remove `from .celery import app as celery_app` and the `__all__ = ('celery_app',)` export; leave the file empty (a valid empty package __init__). |
| delete | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tasks.py` | The two unused @shared_task funcs (generate_daily_jokes, generate_daily_joke_for_user). Confirmed never imported/enqueued/scheduled; views do lazy generation instead. Delete the whole file. |
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py` | Remove 'django_celery_beat' and 'django_celery_results' from INSTALLED_APPS (L62-63); remove the entire CELERY_* config block (L342-351, plus the two comment lines L342-343). |
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/requirements.txt` | Remove celery-only deps: amqp, billiard, celery, click, click-didyoumean, click-plugins, click-repl, cron-descriptor, django-celery-beat, django-celery-results, kombu, prompt-toolkit, python-crontab, redis, async-timeout, tzlocal, vine, wcwidth. KEEP python-dateutil and six (needed by svix via anymail[resend]) and packaging (needed by gunicorn). |
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/.env.example` | Remove the 'Celery (Redis broker)' comment + CELERY_BROKER_URL + CELERY_RESULT_BACKEND lines (L34-36). |
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/.env` | Remove the 'Celery (Redis broker)' comment + CELERY_BROKER_URL + CELERY_RESULT_BACKEND lines (L60-62). (.env is gitignored — local hygiene only, not committed.) |

### Task 1: Baseline: prove green before any change

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject`

- [ ] **Step 1 (run): Run Django system check against current tree to capture the passing baseline.**

```
cd /Users/narekmeloyan/PycharmProjects/JokesForProject && DJANGO_SETTINGS_MODULE=JokesForProject.settings .venv/bin/python manage.py check
```

  - Expected: System check identified no issues (0 silenced). (A few unrelated dj-rest-auth UserWarning deprecation lines are pre-existing and fine.)

- [ ] **Step 2 (run): Run the FULL test suite against LOCAL Postgres (override DATABASE_URL so _build_default_db() falls back to DB_* local vars). This is the before-state proof.**

```
cd /Users/narekmeloyan/PycharmProjects/JokesForProject && DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test --verbosity=2
```

  - Expected: All tests pass (OK). Record the exact test count to compare after the change. If Neon is accidentally hit, you'll see a slow/SSL connection — the DATABASE_URL= override prevents that.

- [ ] **Step 3 (note): Create a working branch before editing (currently on main). e.g. git checkout -b chore/remove-celery.**

### Task 2: Delete the Celery app wiring (celery.py + __init__ export)

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/celery.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/__init__.py`

- [ ] **Step 1 (impl): Delete the Celery app factory file.**

```
rm /Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/celery.py
```

- [ ] **Step 2 (impl): Empty out JokesForProject/__init__.py — remove the celery_app import + __all__ so it's a plain empty package init. Replace the whole file content with nothing (Write an empty file).**

```
# New full contents of /Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/__init__.py:
# (empty file)
```

- [ ] **Step 3 (run): Confirm Django still imports (this is the moment the celery_app autodiscover hook is gone).**

```
cd /Users/narekmeloyan/PycharmProjects/JokesForProject && DJANGO_SETTINGS_MODULE=JokesForProject.settings .venv/bin/python -c "import django; django.setup(); print('django setup OK without celery_app')"
```

  - Expected: Prints 'django setup OK without celery_app' with no ImportError. (settings.py still references the two apps at this point — that's fine because the packages are still installed; they're removed in the next task.)

### Task 3: Delete the dead tasks module

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tasks.py`

- [ ] **Step 1 (note): Re-confirm zero importers one last time before deleting (defense in depth).**

```
grep -rn "from .tasks\|from jokes.tasks\|import tasks\|generate_daily_jokes\|generate_daily_joke_for_user\|\.delay(\|\.apply_async(" --include=*.py /Users/narekmeloyan/PycharmProjects/JokesForProject/jokes /Users/narekmeloyan/PycharmProjects/JokesForProject/notifications /Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject  # expect: only jokes/tasks.py self-matches
```

- [ ] **Step 2 (impl): Delete the tasks module — both functions are dead (views do lazy DailyJoke.get_or_create instead).**

```
rm /Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tasks.py
```

### Task 4: Strip Celery from settings.py

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py`

- [ ] **Step 1 (impl): Remove the two celery apps from INSTALLED_APPS (lines 62-63: 'django_celery_beat', 'django_celery_results').**

```
# Edit INSTALLED_APPS — delete these two lines:
    'django_celery_beat',
    'django_celery_results',
# (Leave 'pgtrigger' above and 'anymail' below intact.)
```

- [ ] **Step 2 (impl): Remove the entire Celery configuration block at the end of settings (the comment header + all CELERY_* assignments, lines 342-351).**

```
# Delete this whole block:
# Celery Configuration
# https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html

CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
```

- [ ] **Step 3 (run): Run the system check now that the apps are de-registered (packages still installed, but no longer in INSTALLED_APPS).**

```
cd /Users/narekmeloyan/PycharmProjects/JokesForProject && DJANGO_SETTINGS_MODULE=JokesForProject.settings .venv/bin/python manage.py check
```

  - Expected: System check identified no issues (0 silenced). No 'app not found' errors. (Pre-existing dj-rest-auth deprecation warnings may still print.)

- [ ] **Step 4 (run): Confirm there are no unapplied/lost migration dependencies after dropping the apps (informational — expect 'No changes detected' for jokes/notifications; the celery apps' migrations simply stop being tracked).**

```
cd /Users/narekmeloyan/PycharmProjects/JokesForProject && DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py makemigrations --check --dry-run
```

  - Expected: No changes detected (exit 0). Our own apps need no new migrations. The django_celery_* tables remain as harmless orphans in the DB — no migration generated or needed.

### Task 5: Prune requirements.txt and the .env files

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/requirements.txt`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/.env.example`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/.env`

- [ ] **Step 1 (impl): Remove celery-only lines from requirements.txt. Delete exactly these pins: amqp==5.3.1, async-timeout==5.0.1, billiard==4.2.4, celery==5.6.2, click==8.3.1, click-didyoumean==0.3.1, click-plugins==1.1.1.2, click-repl==0.3.0, cron-descriptor==2.0.6, django-celery-beat==2.8.1, django-celery-results==2.6.0, kombu==5.6.2, prompt-toolkit==3.0.52, python-crontab==3.3.0, redis==7.1.0, tzlocal==5.3.1, vine==5.1.0, wcwidth==0.2.14. DO NOT remove python-dateutil==2.9.0.post0 or six==1.17.0 (needed by svix via anymail[resend]) or packaging==25.0 (needed by gunicorn).**

```
# Lines to DELETE from requirements.txt (leave everything else):
amqp==5.3.1
async-timeout==5.0.1
billiard==4.2.4
celery==5.6.2
click==8.3.1
click-didyoumean==0.3.1
click-plugins==1.1.1.2
click-repl==0.3.0
cron-descriptor==2.0.6
django-celery-beat==2.8.1
django-celery-results==2.6.0
kombu==5.6.2
prompt-toolkit==3.0.52
python-crontab==3.3.0
redis==7.1.0
tzlocal==5.3.1
vine==5.1.0
wcwidth==0.2.14
# KEEP: python-dateutil==2.9.0.post0, six==1.17.0, packaging==25.0
```

- [ ] **Step 2 (impl): Remove the Celery block from .env.example (lines 34-36).**

```
# Delete from .env.example:
# Celery (Redis broker)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

- [ ] **Step 3 (impl): Remove the Celery block from .env (lines 60-62). Local hygiene only; .env is gitignored and not committed.**

```
# Delete from .env:
# Celery (Redis broker)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

- [ ] **Step 4 (run): Recreate the virtualenv deps from the pruned requirements to prove the pinned set still resolves WITHOUT celery and WITH the email path intact. (Use --dry-run first to avoid mutating the active venv unexpectedly; then actually sync if it looks right.)**

```
cd /Users/narekmeloyan/PycharmProjects/JokesForProject && .venv/bin/pip install -r requirements.txt --dry-run 2>&1 | tail -20
```

  - Expected: Resolves with no conflict. svix/standardwebhooks (and their python-dateutil/six deps) stay satisfied; no 'celery' anywhere. (Note: --dry-run won't uninstall the now-unlisted celery packages from the venv; that's fine — they're just unused. A clean rebuild happens in the Docker image from requirements.txt.)

### Task 6: Final verification: check + full suite (after-state proof)

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject`

- [ ] **Step 1 (run): Run system check on the fully-cleaned tree.**

```
cd /Users/narekmeloyan/PycharmProjects/JokesForProject && DJANGO_SETTINGS_MODULE=JokesForProject.settings .venv/bin/python manage.py check
```

  - Expected: System check identified no issues (0 silenced).

- [ ] **Step 2 (test): Run the FULL Django test suite against local Postgres again. This is the proof nothing broke — compare the test count to the baseline from task 1.**

```
cd /Users/narekmeloyan/PycharmProjects/JokesForProject && DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test --verbosity=2
```

  - Expected: Same number of tests as baseline, all OK. No import errors for celery/tasks, no 'app not found' for django_celery_*. The notifications email/verification tests still pass (proves python-dateutil/six were correctly kept).

- [ ] **Step 3 (run): Belt-and-suspenders: grep the whole repo to confirm zero remaining celery references in code/config (Docs/ may still mention 'no Celery' design notes — those are intentional and fine to leave).**

```
grep -rn -i "celery\|shared_task\|CELERY_\|django_celery" --include=*.py --include=*.txt --include=*.cfg --include=*.toml --include=Dockerfile* /Users/narekmeloyan/PycharmProjects/JokesForProject | grep -v site-packages | grep -v /.venv/
```

  - Expected: No matches in .py/.txt/config (only Docs/*.md design notes describing the no-Celery architecture remain, which is correct).

### Task 7: Commit

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject`

- [ ] **Step 1 (commit): Stage tracked changes (NOT .env — it's gitignored) and commit with a plain description, no Co-Authored-By / generated-with footer. Note orphan tables in the body.**

```
cd /Users/narekmeloyan/PycharmProjects/JokesForProject && git add JokesForProject/__init__.py JokesForProject/settings.py jokes/tasks.py JokesForProject/celery.py requirements.txt .env.example && git status && git commit -m "Remove dead Celery stack

Delete celery.py app factory, the celery_app export in __init__.py, and
jokes/tasks.py (two @shared_task funcs that were never enqueued or
scheduled). Daily-joke rows are generated lazily in the views, so there
is no runtime behavior to preserve.

Drop django_celery_beat/django_celery_results from INSTALLED_APPS, the
CELERY_* settings block, and the CELERY_* entries in .env.example.
Prune the celery-only dependency family from requirements.txt (celery,
amqp, billiard, kombu, vine, redis, async-timeout, django-celery-beat,
django-celery-results, cron-descriptor, python-crontab, tzlocal, and the
click-repl/prompt-toolkit chain). Keep python-dateutil/six (used by svix
via anymail[resend]) and packaging (used by gunicorn).

The django_celery_beat/results tables remain as inert orphans in the DB
(local + Neon); they are harmless and intentionally not dropped.

Verified: manage.py check clean and full test suite green before/after."
```

**Decisions made in this plan:**

- *Delete jokes/tasks.py outright, or convert a function to a plain callable?* → Delete it. Both @shared_task functions are 100% dead: grep finds no importers, no .delay()/.apply_async(), and no beat schedule. The views already do the equivalent work inline (lazy DailyJoke.get_or_create at views.py:961/1004 and _select_daily_joke_for at views.py:2138). Converting to a plain callable would add an unused function — violates YAGNI.
- *What to do about the django_celery_beat / django_celery_results tables already in the DB (local + Neon prod)?* → Leave them as orphan tables; do not write a migration to drop them. Django won't auto-drop tables for removed apps, and the tables are inert once the apps are gone. On Neon they cost nothing meaningful and dropping them is risk for zero benefit. Document this in the commit body. A raw-SQL DROP could be a trivial future follow-up if cleanliness is ever wanted, but it's out of scope here.
- *Are python-dateutil, six, and packaging celery-only deps to remove?* → No — keep all three. python-dateutil and six are required-by svix, which django-anymail[resend] pulls in for the LIVE email-verification stack; removing them would break email. packaging is required-by gunicorn (the prod entrypoint). Only the strictly celery-rooted packages get pruned.
- *How should tests run given .env points DATABASE_URL at Neon?* → Override DATABASE_URL to empty on the test command so settings._build_default_db() falls back to the local DB_* vars (postgres/6969@localhost/jokesfor, confirmed reachable). Use Django's built-in `manage.py test` (no pytest is installed in this venv despite the general project convention). Run check + full suite before and after the change to prove parity.
- *Should the CELERY_* lines be removed from .env (which is gitignored)?* → Yes, for local hygiene, but it is not part of the commit (gitignored). The committed surface is requirements.txt, settings.py, the deleted files, and .env.example. Also leave the Docs/*.md 'no Celery' design notes untouched — they correctly describe the intended architecture.

**Risks:**

- python-dateutil/six look celery-related but are transitively required by svix (via django-anymail[resend], the LIVE email stack). Removing them would break email verification. The plan explicitly keeps them; the after-state test run (notifications suite) is the guard.
- The active .venv won't have the now-unlisted celery packages uninstalled by `pip install -r` (pip doesn't prune). Local imports of celery would still technically succeed until a clean venv/Docker rebuild — so rely on grep + check (not 'it imports') to prove removal. The Docker image rebuilds cleanly from requirements.txt.
- orphan django_celery_* tables persist in Neon prod. Harmless, but if anyone later runs a strict schema-diff tool it will flag them as untracked. Documented in the commit body to set expectations.
- If tests are accidentally run without DATABASE_URL= override, they hit Neon prod (the .env value) — slow and pointed at the live DB. Always pass DATABASE_URL= DB_*=... as shown.
- No beat schedule existed in the repo, but if any PeriodicTask rows were ever seeded directly in a DB they'd now be orphaned with no scheduler. Grep shows no PeriodicTask seeding code, so this is informational only.
- settings.py line numbers (62-63, 342-351) are from the current snapshot; if the file shifts, match on the exact text (the app strings and the CELERY_ block) rather than line numbers when editing.


---

## Transport/abuse hardening + shared throttle cache + observability (TDD plan)

**Goal:** Close five production-readiness gaps in the single Cloud Run Django app without introducing Redis, Celery, cron, or any background worker: (1) make DRF throttle counters shared across gunicorn workers AND Cloud Run instances via a Postgres DatabaseCache; (2) turn on transport/security headers in production only; (3) fail fast if SECRET_KEY is missing in prod; (4) add an unauthenticated GET /healthz for Cloud Run health checks; (5) wire optional Sentry gated on SENTRY_DSN. Each fix is request-triggered / config-only, honoring the no-worker and YAGNI principles.

**Architecture:** FINDINGS FROM ACTUAL CODE:
- No CACHES is configured in settings.py, so Django falls back to the default per-process LocMemCache. DRF throttling imports `from django.core.cache import cache as default_cache` and every throttle (AnonRateThrottle, UserRateThrottle, notifications.throttles.ResendThrottle) reads/writes that `default` alias (verified in .venv rest_framework/throttling.py:6,62,123,140). The Dockerfile runs `gunicorn --workers 2 --threads 4`, so each Cloud Run instance has 2 processes each with its own LocMemCache, and Cloud Run scales to N instances -> throttle counters are NOT shared today. A user can exceed anon/user/verification_resend limits by ~2x per instance x N instances. THE FIX: configure the `default` cache as Django's DatabaseCache on the existing Neon Postgres connection; since DRF reads the `default` alias, this transparently shares all throttle counters across processes and instances with zero throttle-code changes.
- WHY DatabaseCache over alternatives: LocMemCache is per-process (the current bug). Redis/Memcached would introduce a new always-on stateful service to provision, secure, and pay for, plus a network dependency on the hot path — and the project's HARD PRINCIPLE forbids adding infrastructure beyond the single web app + Neon. DatabaseCache reuses the Postgres connection the app already holds, is strongly consistent, survives instance churn, needs no worker/cron, and is request-triggered (each throttle check is one indexed SELECT + UPSERT on a tiny table that Django self-prunes). Throughput is modest (auth/verification endpoints), so the per-request DB round-trip is acceptable. This is the narrowest thing that closes the gap.
- CACHE TABLE LIFECYCLE: `createcachetable` is a management command, NOT a migration, so the table is absent from a freshly-created test DB. We make table creation deterministic by adding an empty migration that runs `createcachetable` via RunPython (so prod deploys and the test DB both get the table through `migrate`). This avoids a manual post-deploy step and keeps the single-app deploy story intact.
- SECRET_KEY currently falls back to 'django-insecure-dev-only-key' (settings.py:31) with no prod guard. FIX: when DEBUG is False, raise ImproperlyConfigured if SECRET_KEY env is unset/blank; keep the dev fallback only when DEBUG is True. SIMPLE_JWT.SIGNING_KEY = SECRET_KEY (settings.py:301) so this also hardens JWT signing.
- SECURITY HEADERS: CSRF_COOKIE_SECURE and SESSION_COOKIE_SECURE are already gated on `not DEBUG` (settings.py:268-269) — verified, no change needed. MISSING: SECURE_HSTS_SECONDS (+INCLUDE_SUBDOMAINS+PRELOAD), SECURE_SSL_REDIRECT, SECURE_CONTENT_TYPE_NOSNIFF. All must be gated on `not DEBUG` so local dev over http keeps working. SECURE_PROXY_SSL_HEADER is already set (settings.py:258) so SECURE_SSL_REDIRECT will correctly detect Cloud Run's terminated TLS and not infinite-loop.
- NO /healthz exists (checked urls.py). Cloud Run startup/liveness probes need an unauthenticated, fast endpoint. Add GET /healthz at the project urlconf root (NOT under /api/v1/, no auth, no versioning, no throttle) that returns 200 with a light DB ping (SELECT 1) so the probe also catches a dead DB connection without heavy work.
- NO Sentry installed (not in requirements.txt). Add sentry-sdk, initialize in settings.py ONLY when SENTRY_DSN env is non-empty (so dev/test stay clean and no DSN = no-op). Use the Django integration; send_default_pii=False (privacy/COPPA/GDPR posture from project memory); traces_sample_rate from env, default 0.
- TEST RUNNER: this project uses Django TestCase via `python manage.py test <path> -v 2 --keepdb` (NOT pytest — verified: no pytest.ini/pyproject pytest config; Docs plans all use manage.py test --keepdb because the Neon pooler blocks DROP DATABASE). Tests use APITestCase + override_settings + cache.clear() (pattern in notifications/tests/test_throttling.py). New tests live in a new app-less test module under JokesForProject/ plus notifications/tests for the cache behavior. Local DB fallback for tests when Neon is unreachable: postgres/6969@localhost/jokesfor.
- CELERY: This plan does NOT touch Celery. Celery removal is a separate work-stream; bundling it here would violate YAGNI. The DatabaseCache choice independently honors the no-worker principle regardless of when Celery is removed.

**Tech Stack:** Django 5.2.10, djangorestframework 3.16.1, Postgres (Neon prod / local Postgres for tests), gunicorn 23 (gthread, 2 workers x 4 threads) on Google Cloud Run, sentry-sdk (new). Tests: Django TestCase / DRF APITestCase run with `python manage.py test ... -v 2 --keepdb`.

**Files:**

| Action | Path | Responsibility |
|---|---|---|
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py` | Add CACHES (DatabaseCache, default alias) so DRF throttles share state; harden SECRET_KEY (ImproperlyConfigured in prod); add prod-gated SECURE_HSTS_SECONDS/SECURE_HSTS_INCLUDE_SUBDOMAINS/SECURE_HSTS_PRELOAD/SECURE_SSL_REDIRECT/SECURE_CONTENT_TYPE_NOSNIFF; add SENTRY_DSN-gated sentry_sdk.init. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/health.py` | healthz(request) function-based view: AllowAny, no auth/throttle, light DB ping (SELECT 1), returns JsonResponse {status:ok\|db_error} with 200/503. |
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/urls.py` | Register path('healthz', healthz) at project root (outside /api/v1/). |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/migrations/__init__.py` | Make JokesForProject a migratable app namespace so the cache-table migration can live there (only if we register it as an app; alternative is to place the migration in an existing app — see task). |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/notifications/migrations/0002_create_cache_table.py` | Empty migration with RunPython that calls createcachetable so the throttle cache table exists in prod and in the test DB after migrate. Placed in the notifications app (existing migratable app) to avoid creating a new app. |
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/requirements.txt` | Add sentry-sdk pin. |
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/.env.example` | Document SENTRY_DSN, SENTRY_TRACES_SAMPLE_RATE, SECURE_HSTS_SECONDS override; note SECRET_KEY is required when DEBUG=False. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/__init__.py` | Make JokesForProject/tests a discoverable test package. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_healthz.py` | healthz returns 200 unauthenticated; correct shape; no auth required. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_security_settings.py` | Assert security headers ON when DEBUG=False and OFF when DEBUG=True; assert SECRET_KEY guard raises in prod when blank. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/notifications/tests/test_throttle_cache.py` | Assert the throttle counter persists through the Postgres DatabaseCache table (round-trips DB), proving counters are shared across processes. |

### Task 1: Task 1 — Shared throttle cache via Postgres DatabaseCache (no Redis, no worker)

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/notifications/migrations/0002_create_cache_table.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/notifications/tests/test_throttle_cache.py`

- [ ] **Step 1 (note): WHY DatabaseCache: LocMemCache (today's implicit default) is per-process; with gunicorn --workers 2 each Cloud Run instance has 2 independent throttle counters, and Cloud Run runs N instances, so anon/user/verification_resend limits are bypassable by ~2N. Redis/Memcached would add an always-on stateful service the HARD PRINCIPLES forbid. DatabaseCache reuses the existing Neon connection, is strongly consistent, survives instance churn, needs no worker/cron, and is request-triggered. DRF reads the `default` cache alias, so swapping `default` to DatabaseCache shares ALL throttle counters with zero throttle-code edits.**

- [ ] **Step 2 (test): Write failing test asserting the throttle cache key lands in the Postgres cache table. It creates the cache table, drives the ResendThrottle endpoint, and asserts the cache row exists via the DatabaseCache backend (not LocMem). Run: python manage.py test notifications.tests.test_throttle_cache -v 2 --keepdb**

```
from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APITestCase

User = get_user_model()
RESEND_URL = '/api/v1/auth/resend-verification/'

# Force the DatabaseCache for this test class regardless of DEBUG, so we prove
# the counter survives in Postgres (i.e. is shareable across processes).
@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_REQUIRED=True,
    CACHES={'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'jokesfor_cache',
    }},
)
class ThrottleCachePersistsInDbTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # createcachetable is idempotent; ensures the table exists in the test DB
        call_command('createcachetable', 'jokesfor_cache')

    def setUp(self):
        caches['default'].clear()
        self.user = User.objects.create_user(
            username='c@example.com', email='c@example.com', password='pw',
            is_active=False,
        )

    def tearDown(self):
        caches['default'].clear()

    def test_resend_counter_round_trips_through_postgres(self):
        db_cache = caches['default']
        # Sanity: we really are using the DB backend, not LocMem.
        self.assertEqual(
            db_cache.__class__.__module__,
            'django.core.cache.backends.db',
        )
        r = self.client.post(RESEND_URL, {'email': self.user.email}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        # The throttle stored its history under a 'throttle_...' key in the DB cache.
        throttle_keys = [k for k in self._all_db_cache_keys() if 'throttle' in k]
        self.assertTrue(throttle_keys, 'throttle counter was not written to the DB cache')

    def _all_db_cache_keys(self):
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT cache_key FROM jokesfor_cache')
            return [row[0] for row in cur.fetchall()]
```

- [ ] **Step 3 (impl): Add a CACHES block to settings.py. Use DatabaseCache on the default alias so DRF throttles share state. Add it right after the DATABASES definition (after settings.py line 152).**

```
# Cache — Django DatabaseCache on the existing Postgres connection.
#
# DRF throttling reads/writes the `default` cache alias. Without this block,
# Django falls back to a per-process LocMemCache, so each gunicorn worker (and
# each Cloud Run instance) keeps its OWN throttle counters and the anon/user/
# verification_resend limits are bypassable by ~workers x instances.
#
# We use DatabaseCache (not Redis/Memcached) on purpose: it reuses the Neon
# connection we already hold, is strongly consistent, survives instance churn,
# and needs NO extra service or background worker — honoring the single-app,
# no-worker principle. The cache table is created by a migration (see
# notifications/migrations/0002_create_cache_table.py) so it exists in prod and
# in the test DB after `migrate`.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'jokesfor_cache',
        # Cap the table so it self-prunes; throttle entries are short-lived.
        'OPTIONS': {'MAX_ENTRIES': 10000, 'CULL_FREQUENCY': 3},
    }
}
```

- [ ] **Step 4 (impl): Create the cache-table migration in the notifications app (an existing migratable app, so no new app is needed). It runs createcachetable on apply and is a no-op on reverse. Confirm the latest notifications migration number first with: ls notifications/migrations — name the new file 0002_create_cache_table.py (or next free number).**

```
from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    # createcachetable is idempotent and respects the target connection, so it
    # works for prod migrate and for the test DB. Uses the LOCATION from CACHES.
    call_command('createcachetable', database=schema_editor.connection.alias)


def drop_cache_table(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        cur.execute('DROP TABLE IF EXISTS jokesfor_cache')


class Migration(migrations.Migration):
    dependencies = [
        ('notifications', '0001_initial'),
    ]
    operations = [
        migrations.RunPython(create_cache_table, drop_cache_table),
    ]
```

- [ ] **Step 5 (run): Verify migration applies and creates the table. Run: python manage.py migrate notifications --keepdb (or python manage.py migrate notifications against local DB). Then python manage.py createcachetable --dry-run to confirm idempotency.**

  - Expected: Migration 0002_create_cache_table applies without error; table jokesfor_cache exists.

- [ ] **Step 6 (run): Run the new test green. python manage.py test notifications.tests.test_throttle_cache -v 2 --keepdb**

  - Expected: OK — throttle counter round-trips through the Postgres jokesfor_cache table.

- [ ] **Step 7 (run): Regression: run the existing throttle suite to confirm nothing broke. python manage.py test notifications.tests.test_throttling -v 2 --keepdb**

  - Expected: OK (2 tests). Note: those tests rely on cache.clear() and now hit DatabaseCache; the cache table exists via migration so they still pass.

- [ ] **Step 8 (commit): Commit. Message: 'Share DRF throttle counters via Postgres DatabaseCache' with body explaining the per-process LocMemCache bypass and why DB cache over Redis. No Co-Authored-By footer.**

### Task 2: Task 2 — Production-gated transport/security headers

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/__init__.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_security_settings.py`

- [ ] **Step 1 (note): Verified already present and correct: CSRF_COOKIE_SECURE / SESSION_COOKIE_SECURE = not DEBUG (settings.py:268-269) and SECURE_PROXY_SSL_HEADER (settings.py:258). MISSING and to add, all gated on not DEBUG so local http dev is unaffected: SECURE_HSTS_SECONDS + INCLUDE_SUBDOMAINS + PRELOAD, SECURE_SSL_REDIRECT, SECURE_CONTENT_TYPE_NOSNIFF. SECURE_SSL_REDIRECT is safe because SECURE_PROXY_SSL_HEADER lets Django see Cloud Run's already-terminated TLS (no redirect loop).**

- [ ] **Step 2 (impl): Create the test package marker.**

```
# (empty file) JokesForProject/tests/__init__.py
```

- [ ] **Step 3 (test): Write failing tests that reimport settings under DEBUG=False and DEBUG=True and assert header presence/absence. Run: python manage.py test JokesForProject.tests.test_security_settings -v 2 --keepdb**

```
import importlib
import os
from unittest import mock

from django.test import SimpleTestCase


class SecuritySettingsTests(SimpleTestCase):
    def _reload_settings(self, env):
        # Reimport the settings module under a patched environment to observe the
        # DEBUG-gated branches. We import the module object directly (not django
        # settings) so we read the computed module-level values.
        with mock.patch.dict(os.environ, env, clear=False):
            import JokesForProject.settings as s
            return importlib.reload(s)

    def test_security_headers_on_in_production(self):
        s = self._reload_settings({'DEBUG': 'False', 'SECRET_KEY': 'x' * 50})
        self.assertFalse(s.DEBUG)
        self.assertGreaterEqual(s.SECURE_HSTS_SECONDS, 31536000)
        self.assertTrue(s.SECURE_HSTS_INCLUDE_SUBDOMAINS)
        self.assertTrue(s.SECURE_HSTS_PRELOAD)
        self.assertTrue(s.SECURE_SSL_REDIRECT)
        self.assertTrue(s.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertTrue(s.SESSION_COOKIE_SECURE)
        self.assertTrue(s.CSRF_COOKIE_SECURE)

    def test_security_headers_off_in_debug(self):
        s = self._reload_settings({'DEBUG': 'True'})
        self.assertTrue(s.DEBUG)
        self.assertEqual(s.SECURE_HSTS_SECONDS, 0)
        self.assertFalse(s.SECURE_SSL_REDIRECT)
        # NOSNIFF is harmless in dev; assert it is False here only because we gate it.
        self.assertFalse(s.SECURE_CONTENT_TYPE_NOSNIFF)

    @classmethod
    def tearDownClass(cls):
        # Restore the real settings module after reloads.
        import importlib
        import JokesForProject.settings as s
        importlib.reload(s)
        super().tearDownClass()
```

- [ ] **Step 4 (impl): Add the security block to settings.py near the existing cookie-security lines (after settings.py:269). Gate everything on `not DEBUG`. Allow HSTS duration override via env for staged rollout (start small, ramp to 1 year before submitting to the HSTS preload list).**

```
# Transport security — production only. Local dev runs over plain http, so these
# stay OFF when DEBUG=True. SECURE_PROXY_SSL_HEADER (set above) lets Django see
# Cloud Run's terminated TLS, so SECURE_SSL_REDIRECT won't loop.
if not DEBUG:
    # Start lower (e.g. 3600) on first prod rollout, then ramp to a year before
    # adding the domain to the browser HSTS preload list.
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
else:
    SECURE_HSTS_SECONDS = 0
    SECURE_SSL_REDIRECT = False
    SECURE_CONTENT_TYPE_NOSNIFF = False
```

- [ ] **Step 5 (run): Run the security settings tests. python manage.py test JokesForProject.tests.test_security_settings -v 2 --keepdb**

  - Expected: OK — headers present under DEBUG=False, absent under DEBUG=True.

- [ ] **Step 6 (run): Sanity: Django's own deploy checklist. DEBUG=False SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(50))") ALLOWED_HOSTS=example.com python manage.py check --deploy 2>&1 | tail -20**

  - Expected: No W004/W008/W012/W016 warnings for HSTS/SSL-redirect/nosniff/secure-cookies.

- [ ] **Step 7 (commit): Commit. Message: 'Enable HSTS, SSL redirect and nosniff in production'. No footer.**

### Task 3: Task 3 — Fail fast on missing SECRET_KEY in production

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_security_settings.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/.env.example`

- [ ] **Step 1 (note): Today SECRET_KEY=os.getenv('SECRET_KEY','django-insecure-dev-only-key') (settings.py:31) — a deploy that forgets to set SECRET_KEY would silently sign JWTs (SIMPLE_JWT.SIGNING_KEY=SECRET_KEY, settings.py:301) with a publicly-known key. FIX: keep the dev fallback only when DEBUG is True; raise ImproperlyConfigured when DEBUG is False and the env var is missing/blank. DEBUG is read at settings.py:34 AFTER SECRET_KEY at line 31, so the SECRET_KEY logic must be MOVED to after DEBUG is computed (reorder lines 31-36).**

- [ ] **Step 2 (test): Add a test that reloading settings with DEBUG=False and no SECRET_KEY raises ImproperlyConfigured, and that DEBUG=True without SECRET_KEY uses the dev fallback. Append to test_security_settings.py. Run: python manage.py test JokesForProject.tests.test_security_settings -v 2 --keepdb**

```
    def test_missing_secret_key_in_prod_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        import importlib
        import JokesForProject.settings as s
        with mock.patch.dict(os.environ, {'DEBUG': 'False'}, clear=False):
            os.environ.pop('SECRET_KEY', None)
            with self.assertRaises(ImproperlyConfigured):
                importlib.reload(s)

    def test_dev_fallback_secret_key_when_debug(self):
        s = self._reload_settings({'DEBUG': 'True'})
        # pop SECRET_KEY then reload to confirm the dev fallback path
        with mock.patch.dict(os.environ, {'DEBUG': 'True'}, clear=False):
            os.environ.pop('SECRET_KEY', None)
            import importlib
            s = importlib.reload(s)
        self.assertTrue(s.SECRET_KEY)
```

- [ ] **Step 3 (impl): Reorder so DEBUG is computed first, then guard SECRET_KEY. Replace settings.py lines 30-36 (the SECRET_KEY / DEBUG / ALLOWED_HOSTS block).**

```
from django.core.exceptions import ImproperlyConfigured  # add near top imports if not present

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')

# SECURITY WARNING: keep the secret key used in production secret!
# In production (DEBUG=False) a real key MUST be provided via env — a missing
# key would otherwise silently sign JWTs with a publicly-known fallback.
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-dev-only-key'
    else:
        raise ImproperlyConfigured('SECRET_KEY environment variable is required when DEBUG=False')

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]
```

- [ ] **Step 4 (impl): Document in .env.example that SECRET_KEY is mandatory when DEBUG=False.**

```
# Django settings
# SECRET_KEY is REQUIRED when DEBUG=False (the app refuses to start without it).
SECRET_KEY=your-secret-key-here
DEBUG=True
```

- [ ] **Step 5 (run): Verify the Dockerfile build-time collectstatic still works: it sets SECRET_KEY=build-only-key DEBUG=False (Dockerfile:51), so the guard passes (key is non-blank). Confirm with: DEBUG=False SECRET_KEY=build-only-key ALLOWED_HOSTS=* python manage.py check**

  - Expected: System check passes; no ImproperlyConfigured (key is provided).

- [ ] **Step 6 (run): Run tests. python manage.py test JokesForProject.tests.test_security_settings -v 2 --keepdb**

  - Expected: OK — prod-without-key raises, dev falls back.

- [ ] **Step 7 (commit): Commit. Message: 'Require SECRET_KEY in production instead of insecure fallback'. No footer.**

### Task 4: Task 4 — GET /healthz for Cloud Run health checks

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/health.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/urls.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_healthz.py`

- [ ] **Step 1 (note): Cloud Run startup/liveness probes need an unauthenticated, cheap endpoint. Put it at the project root (/healthz) — NOT under /api/v1/ — so it skips DRF auth/versioning/throttling entirely. Do a light DB ping (SELECT 1) so the probe also catches a dead DB pool; return 503 if the DB is unreachable so Cloud Run can recycle the instance. Keep it a plain Django function view (no DRF) to avoid pulling throttle/auth machinery onto the probe path.**

- [ ] **Step 2 (test): Write failing test: /healthz returns 200 + {status:'ok'} with no credentials. Run: python manage.py test JokesForProject.tests.test_healthz -v 2 --keepdb**

```
from django.test import TestCase


class HealthzTests(TestCase):
    def test_healthz_returns_200_unauthenticated(self):
        resp = self.client.get('/healthz')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json().get('status'), 'ok')

    def test_healthz_is_not_versioned_or_throttled(self):
        # Hitting it many times must never 429 (it is outside DRF throttling).
        for _ in range(20):
            resp = self.client.get('/healthz')
            self.assertEqual(resp.status_code, 200)
```

- [ ] **Step 3 (impl): Create the health view.**

```
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def healthz(request):
    """Unauthenticated liveness probe for Cloud Run.

    Plain Django view (not DRF) so it bypasses auth, versioning and throttling.
    Does a light DB ping so the probe also surfaces a dead DB pool; returns 503
    in that case so Cloud Run recycles the instance.
    """
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
            cur.fetchone()
    except Exception:
        return JsonResponse({'status': 'db_error'}, status=503)
    return JsonResponse({'status': 'ok'}, status=200)
```

- [ ] **Step 4 (impl): Register the route in JokesForProject/urls.py. Add the import and a path at the top of urlpatterns (before the API includes).**

```
from JokesForProject.health import healthz
# ... inside urlpatterns, as the first entry:
    path('healthz', healthz, name='healthz'),
```

- [ ] **Step 5 (run): Run the test. python manage.py test JokesForProject.tests.test_healthz -v 2 --keepdb**

  - Expected: OK (2 tests) — 200 with {status: ok}, never 429.

- [ ] **Step 6 (note): Optional ops follow-up (not code): set the Cloud Run startup/liveness probe HTTP path to /healthz. No Dockerfile change required.**

- [ ] **Step 7 (commit): Commit. Message: 'Add unauthenticated /healthz endpoint for Cloud Run probes'. No footer.**

### Task 5: Task 5 — Optional Sentry, gated on SENTRY_DSN

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/requirements.txt`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/.env.example`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_security_settings.py`

- [ ] **Step 1 (note): Add sentry-sdk and initialize it ONLY when SENTRY_DSN is non-empty, so dev and tests stay clean (no DSN => no network, no-op). Use the Django integration. send_default_pii=False to match the project's COPPA/GDPR privacy posture (from memory). traces_sample_rate from env, default 0 (errors-only by default; performance tracing opt-in).**

- [ ] **Step 2 (impl): Pin sentry-sdk in requirements.txt (alphabetical neighborhood near 'six'). Use the Django extra.**

```
sentry-sdk[django]==2.20.0
```

- [ ] **Step 3 (run): Install into the venv so tests can import it. /Users/narekmeloyan/PycharmProjects/JokesForProject/.venv/bin/pip install 'sentry-sdk[django]==2.20.0'**

  - Expected: Successfully installed sentry-sdk.

- [ ] **Step 4 (test): Add a test that import + init is a no-op without DSN and that the settings module exposes a SENTRY_DSN value. Append to test_security_settings.py. Run after impl. Keep it light: assert that with no DSN, sentry is not initialized (sentry_sdk.Hub/get_client has no DSN).**

```
    def test_sentry_not_initialized_without_dsn(self):
        with mock.patch.dict(os.environ, {'DEBUG': 'True'}, clear=False):
            os.environ.pop('SENTRY_DSN', None)
            import importlib
            import JokesForProject.settings as s
            importlib.reload(s)
        import sentry_sdk
        client = sentry_sdk.get_client()
        # No DSN configured => client is not active.
        self.assertFalse(getattr(client, 'is_active', lambda: bool(client.dsn))())
```

- [ ] **Step 5 (impl): Add the Sentry block near the end of settings.py (after the email/verification section). Guard strictly on a non-empty DSN.**

```
# Error monitoring — Sentry, opt-in via SENTRY_DSN. No DSN => fully no-op, so
# local dev and the test suite never phone home. send_default_pii=False keeps
# user identifiers out of events (COPPA/GDPR posture).
SENTRY_DSN = os.getenv('SENTRY_DSN', '').strip()
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=float(os.getenv('SENTRY_TRACES_SAMPLE_RATE', '0')),
        send_default_pii=False,
        environment=os.getenv('SENTRY_ENVIRONMENT', 'production' if not DEBUG else 'development'),
    )
```

- [ ] **Step 6 (impl): Document the env vars in .env.example (append at end).**

```
# Error monitoring (optional) — leave SENTRY_DSN empty to disable entirely.
SENTRY_DSN=
SENTRY_TRACES_SAMPLE_RATE=0
SENTRY_ENVIRONMENT=development
```

- [ ] **Step 7 (run): Run the Sentry test. python manage.py test JokesForProject.tests.test_security_settings.SecuritySettingsTests.test_sentry_not_initialized_without_dsn -v 2 --keepdb**

  - Expected: OK — Sentry client inactive when no DSN.

- [ ] **Step 8 (commit): Commit. Message: 'Add optional Sentry error monitoring gated on SENTRY_DSN'. No footer.**

### Task 6: Task 6 — Full-suite verification

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py`

- [ ] **Step 1 (run): Run the entire test suite to confirm no regressions across jokes + notifications + new project tests. python manage.py test -v 1 --keepdb 2>&1 | tail -15. If Neon pooler is unreachable, fall back to local Postgres (postgres/6969@localhost/jokesfor) by unsetting DATABASE_URL and using DB_* env vars.**

  - Expected: OK — all tests pass; the new cache table migration is applied to the test DB so throttle tests pass.

- [ ] **Step 2 (run): Final deploy-checklist gate. DEBUG=False SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(50))") ALLOWED_HOSTS=example.com python manage.py check --deploy 2>&1 | tail -20**

  - Expected: No remaining security warnings for HSTS, SSL redirect, nosniff, secure cookies, or SECRET_KEY.

- [ ] **Step 3 (note): Do NOT touch Celery in this work-stream — its removal is a separate task and bundling it would violate YAGNI. The DatabaseCache choice already honors the no-worker principle independently.**

**Decisions made in this plan:**

- *Why DatabaseCache instead of LocMemCache or Redis for shared throttle counters?* → LocMemCache is per-process — with gunicorn --workers 2 and N Cloud Run instances, throttle counters fragment and limits are bypassable (the current bug). Redis/Memcached would add an always-on stateful service the HARD PRINCIPLES forbid (single app + Neon only) and a hot-path network dependency. DatabaseCache reuses the existing Neon connection, is strongly consistent, survives instance churn, needs no worker/cron, and DRF already reads the `default` alias — so it shares all throttle counters with zero throttle-code changes. It is the narrowest fix that closes the gap.
- *How does the DB cache table get created so it exists in prod AND the test DB without a manual step?* → Add an empty migration in the existing notifications app whose RunPython calls `createcachetable` (idempotent, respects the target connection). This runs on `migrate` in prod and on test-DB setup, so `--keepdb` test runs and Cloud Run deploys both get the table. Avoids a fragile manual post-deploy command and needs no new app.
- *Should /healthz hit the database?* → Yes, a light SELECT 1. A no-DB probe can report healthy while the DB pool is dead, defeating the point. SELECT 1 is cheap and lets Cloud Run recycle an instance with a broken connection (return 503 on failure). Keep it a plain Django view at the project root so it bypasses DRF auth/versioning/throttling.
- *Is SECURE_SSL_REDIRECT safe behind Cloud Run's TLS terminator?* → Yes. SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https') is already set (settings.py:258), so Django sees the original TLS scheme and will not enter a redirect loop. Gate it on `not DEBUG` so local http dev is unaffected.
- *Does the SECRET_KEY guard break the Docker build's collectstatic step?* → No. The Dockerfile runs collectstatic with SECRET_KEY=build-only-key DEBUG=False (Dockerfile:51) — a non-blank key, so the guard passes. The guard only fires when DEBUG=False AND the key is missing/blank.
- *Should this plan also remove Celery (per the no-worker principle)?* → No. Celery removal is a separate settled work-stream; bundling it here violates YAGNI. The DatabaseCache approach already honors the no-worker principle regardless of Celery's presence. Keep this plan scoped to the five named hardening/observability fixes.
- *pytest or Django test runner?* → Django test runner: there is no pytest config, and all project Docs/plans use `python manage.py test <path> -v 2 --keepdb` (Neon pooler blocks DROP DATABASE, hence --keepdb). New tests are APITestCase/TestCase/SimpleTestCase mirroring notifications/tests patterns.
- *How to make Sentry safe in dev/test?* → Initialize only when SENTRY_DSN is a non-empty env value; otherwise it is a complete no-op (no network). Set send_default_pii=False for COPPA/GDPR posture and traces_sample_rate default 0 (errors-only unless explicitly opted in).

**Risks:**

- DatabaseCache adds a DB round-trip per throttled request (indexed SELECT + UPSERT on a small self-pruning table). For the auth/verification endpoints this is negligible, but if a very hot endpoint is ever throttled, watch Neon connection pressure; the cap (MAX_ENTRIES=10000, CULL_FREQUENCY=3) keeps the table tiny.
- The cache-table migration uses RunPython call_command('createcachetable'); if CACHES is somehow undefined at migrate time the command errors — CACHES is added in the same Task 1, so order matters (add CACHES to settings before running migrate).
- Existing notifications throttle tests (test_throttling.py) call cache.clear() and now operate against DatabaseCache; they require the cache table to exist in the test DB. The migration provides it, but if someone runs those tests against a pre-existing --keepdb test DB created before the migration, they must re-run migrate (or drop --keepdb once) so the table appears.
- SECURE_SSL_REDIRECT relies on SECURE_PROXY_SSL_HEADER being correct; if Cloud Run's proxy header ever changes, redirects could loop. Mitigated by /healthz being a plain view and by --check --deploy gate.
- Reload-based settings tests (importlib.reload on the settings module) are slightly fragile across Python state; tearDownClass restores the module. If these prove flaky in CI, convert to subprocess-based `manage.py check`/`diffsettings` assertions.
- Adding sentry-sdk grows the image and adds an import; gated init keeps it inert without a DSN, but ensure the venv and the Docker build both install the new pin (requirements.txt change is picked up by the builder stage).


---

## Durable production media storage on Google Cloud Storage (env-gated, FileSystemStorage default)

**Goal:** Persist user/generated media (share cards, avatars) durably in production by switching Django's default file storage to Google Cloud Storage when GS_BUCKET_NAME is set, while keeping FileSystemStorage as the local-dev/test default so nothing in tests or dev needs GCS. Share-card generation stays fully synchronous in Joke.save() (no workers). share_image_url and avatar_url must remain absolute URLs in all cases.

**Architecture:** Cloud Run runs a single gunicorn app; the container filesystem is ephemeral, so the current FileSystemStorage default silently loses every generated share card and uploaded avatar on each new revision/instance. The fix is to make STORAGES['default'] env-driven: when GS_BUCKET_NAME is present, use storages.backends.gcloud.GoogleCloudStorage; otherwise keep django.core.files.storage.FileSystemStorage (the existing local/test default). staticfiles stays on WhiteNoise CompressedManifestStaticFilesStorage untouched.

The two ImageFields (Joke.share_image upload_to='share-cards/', UserProfile.avatar upload_to='avatars/') do not change — they go through Django's default storage automatically, so flipping STORAGES['default'] routes both to GCS with zero model edits. Joke.save() already saves the field name back via .update(share_image=self.share_image.name); that works identically on GCS (the name is the blob path). cairosvg PNG generation stays inline in _generate_share_image (no-worker principle preserved).

Public-read vs signed-URL decision: both share cards and avatars are intended to be publicly viewable (share cards are explicitly built for social-media crawler scraping in joke_share_page / Open Graph tags; avatars render on public profiles where public_profile defaults True). Cloud Run's default service account CANNOT sign V4 URLs without the IAM Credentials API (GS_IAM_SIGN_BLOB) and signed URLs would break OG crawler caching and expire. Therefore: bucket uses Uniform bucket-level access set to public-read, and we configure GS_DEFAULT_ACL=None + GS_QUERYSTRING_AUTH=False so .url returns a stable, non-expiring https://storage.googleapis.com/<bucket>/<path> URL. This is the django-storages-recommended combination for a uniform-access public bucket (setting GS_DEFAULT_ACL='publicRead' would require fine-grained ACLs and 400 on uniform buckets). Content-type for blobs is guessed by django-storages from the filename; joke-<pk>.png yields image/png, and ImageField avatar uploads carry their own extension, so no object_parameters override is needed.

MEDIA_URL: currently undefined. For the FileSystemStorage (dev/test) branch we add MEDIA_URL='/media/' and MEDIA_ROOT=BASE_DIR/'media' so .url is well-formed locally; serializers wrap it in build_absolute_uri so it becomes absolute against the request host. For the GCS branch, GoogleCloudStorage.url ignores MEDIA_URL and returns the absolute GCS URL; build_absolute_uri is idempotent on already-absolute URLs (Django's build_absolute_uri returns the input unchanged when it has a scheme+host), so views.py:1063, views.py:1282, and both serializers keep working unmodified in both modes.

Credentials: Cloud Run injects Application Default Credentials via the attached service account, which google-cloud-storage picks up automatically — no GS_CREDENTIALS or key file needed in prod. We still honor GOOGLE_APPLICATION_CREDENTIALS if a developer points it at a key file. GS_PROJECT_ID is optional (inferred from ADC) but we wire it through env for explicitness.

No Celery/cron/worker is added; the only new runtime work (PNG render) was already synchronous. collectstatic in the Dockerfile is unaffected because staticfiles storage is untouched and runs before any GCS env is set.

**Tech Stack:** Django 5.2 + DRF; django-storages[google]==1.14.6 + google-cloud-storage==3.12.0; cairosvg (existing) for synchronous share-card PNG; Postgres (local for tests); Google Cloud Run single gunicorn app; WhiteNoise for static (unchanged). Tests: Django TestCase/SimpleTestCase via manage.py test with override_settings.

**Files:**

| Action | Path | Responsibility |
|---|---|---|
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/requirements.txt` | Add django-storages[google]==1.14.6 and google-cloud-storage==3.12.0 (and its transitive google-* deps if pip-compiled) so the GCS backend is importable in the runtime image. |
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py` | Add MEDIA_URL/MEDIA_ROOT; make STORAGES['default'] env-gated on GS_BUCKET_NAME (GCS backend with GS_DEFAULT_ACL=None, GS_QUERYSTRING_AUTH=False, GS_FILE_OVERWRITE=True, optional GS_PROJECT_ID/GS_LOCATION) else keep FileSystemStorage; leave staticfiles WhiteNoise entry untouched. |
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/.env.example` | Document new GCS env vars (GS_BUCKET_NAME, GS_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS) under a Production-only Media storage section; note that leaving GS_BUCKET_NAME empty uses local filesystem. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests_storage.py` | New TDD test module: (1) share_image_url is absolute in default/local mode; (2) STORAGES['default'] resolves to FileSystemStorage when GS_BUCKET_NAME unset and to GoogleCloudStorage when set, via a settings-builder helper; (3) MEDIA_URL defined; (4) share-card regeneration path still calls storage.save with the joke-<pk>.png name. |
| modify | `/Users/narekmeloyan/PycharmProjects/JokesForProject/Dockerfile` | No functional change required for storage, but verify collectstatic step is unaffected (staticfiles untouched). Add a comment that GS_BUCKET_NAME is supplied at runtime, not build time, so collectstatic never touches GCS. (Comment-only edit.) |

### Task 1: Task 1 — Add dependencies

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/requirements.txt`

- [ ] **Step 1 (note): django-storages reads the GCS backend lazily (only when STORAGES['default'] points at it), so adding the dep is safe even though local/test runs use FileSystemStorage. Installing it locally lets the env-switch test import the backend path.**

- [ ] **Step 2 (impl): Append the two pins (keep file alphabetical-ish like the rest; google-cloud-storage pulls google-* transitive deps which pip will resolve). Pin to the latest verified versions.**

```
# add to requirements.txt
django-storages[google]==1.14.6
google-cloud-storage==3.12.0
```

- [ ] **Step 3 (run): Install into the project venv so tests can import storages.backends.gcloud.**

```
/Users/narekmeloyan/PycharmProjects/JokesForProject/.venv/bin/pip install 'django-storages[google]==1.14.6' 'google-cloud-storage==3.12.0'
```

  - Expected: Successfully installed django-storages-1.14.6 google-cloud-storage-3.12.0 google-* (and deps).

- [ ] **Step 4 (run): Confirm the GCS backend imports cleanly.**

```
/Users/narekmeloyan/PycharmProjects/JokesForProject/.venv/bin/python -c "from storages.backends.gcloud import GoogleCloudStorage; print('ok')"
```

  - Expected: ok

### Task 2: Task 2 — Write failing tests (TDD red)

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests_storage.py`

- [ ] **Step 1 (note): To test the env-switch deterministically without mutating module-level settings, refactor the STORAGES selection in settings.py into a small pure helper build_default_storage(bucket_name) that returns the correct dict. The tests import that helper and assert both branches. This avoids needing to re-import settings under different env.**

- [ ] **Step 2 (test): Create jokes/tests_storage.py with four tests. Test A and the regeneration test patch cairosvg so no real Cairo render is needed (mirrors existing tests.py @patch('jokes.models.Joke._generate_share_image')). Run with manage.py test.**

```
# /Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests_storage.py
from unittest.mock import patch

from django.conf import settings
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory

from jokes.models import Joke, Format
from jokes.serializers import JokeSerializer
from JokesForProject.settings import build_default_storage


class StorageBackendSelectionTests(TestCase):
    """STORAGES['default'] switches by GS_BUCKET_NAME env."""

    def test_local_default_is_filesystem(self):
        cfg = build_default_storage(bucket_name='')
        self.assertEqual(
            cfg['BACKEND'],
            'django.core.files.storage.FileSystemStorage',
        )

    def test_gcs_default_when_bucket_set(self):
        cfg = build_default_storage(bucket_name='jokesfor-media-prod')
        self.assertEqual(
            cfg['BACKEND'],
            'storages.backends.gcloud.GoogleCloudStorage',
        )
        opts = cfg['OPTIONS']
        self.assertEqual(opts['bucket_name'], 'jokesfor-media-prod')
        # Public, uniform-access bucket -> stable non-expiring URLs.
        self.assertIsNone(opts['default_acl'])
        self.assertFalse(opts['querystring_auth'])

    def test_media_url_defined(self):
        self.assertTrue(settings.MEDIA_URL)


class ShareImageUrlAbsoluteTests(TestCase):
    """share_image_url is always an absolute URL (local FS mode)."""

    @patch('jokes.models.Joke._generate_share_image')
    def _make_joke_with_image(self, _mock_img):
        fmt, _ = Format.objects.get_or_create(
            slug='oneliner', defaults={'name': 'One-liner'}
        )
        joke = Joke.objects.create(text='Absolute url test joke.', format=fmt)
        # Attach a fake file through the *default* storage (FS in tests).
        joke.share_image.save(
            f'joke-{joke.pk}.png', ContentFile(b'PNGDATA'), save=True
        )
        return joke

    def test_share_image_url_is_absolute(self):
        joke = self._make_joke_with_image()
        request = APIRequestFactory().get('/api/v1/jokes/')
        data = JokeSerializer(joke, context={'request': request}).data
        url = data['share_image_url']
        self.assertIsNotNone(url)
        self.assertTrue(
            url.startswith('http://') or url.startswith('https://'),
            f'expected absolute URL, got {url!r}',
        )
        self.assertIn('joke-%d.png' % joke.pk, url)


class ShareCardRegenerationTests(TestCase):
    """Joke.save() still routes the generated PNG through default storage."""

    def test_regeneration_saves_via_storage(self):
        fmt, _ = Format.objects.get_or_create(
            slug='oneliner', defaults={'name': 'One-liner'}
        )
        # Patch the cairosvg render so save() runs the real storage path
        # with deterministic bytes (no Cairo dependency in the assertion).
        with patch(
            'jokes.share_cards.generate_share_card_png'
        ) as gen:
            import io
            gen.return_value = io.BytesIO(b'PNGDATA')
            joke = Joke.objects.create(text='Regen path joke.', format=fmt)
        joke.refresh_from_db()
        self.assertTrue(joke.share_image)
        self.assertTrue(joke.share_image.name.endswith(f'joke-{joke.pk}.png'))
        self.assertEqual(joke.share_image.read(), b'PNGDATA')
```

- [ ] **Step 3 (run): Run the new tests — they must FAIL first (build_default_storage and MEDIA_URL do not exist yet).**

```
/Users/narekmeloyan/PycharmProjects/JokesForProject/.venv/bin/python manage.py test jokes.tests_storage -v2
```

  - Expected: ImportError/AttributeError for build_default_storage (red). If DB unreachable on Neon, ensure DATABASE_URL is unset so it falls back to local Postgres (postgres/6969@localhost/jokesfor) per project convention.

### Task 3: Task 3 — Implement settings (TDD green)

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py`

- [ ] **Step 1 (impl): Add MEDIA_URL/MEDIA_ROOT right after STATIC settings, and replace the STORAGES block with a helper-driven version. Keep the staticfiles entry byte-identical (WhiteNoise). The helper centralizes the env switch so the test can assert both branches.**

```
# --- in settings.py, replace the existing STORAGES block (L193-196) ---

# Media files (user uploads + generated share cards).
# Local dev/test serve from the filesystem; production overrides the default
# storage to Google Cloud Storage when GS_BUCKET_NAME is set (see below).
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


def build_default_storage(bucket_name: str) -> dict[str, Any]:
    """Return the STORAGES['default'] config.

    With GS_BUCKET_NAME set -> Google Cloud Storage (durable prod storage).
    Without it -> the filesystem (local dev + tests need no GCS).

    The bucket uses Uniform bucket-level access set to public-read, so we keep
    default_acl=None and querystring_auth=False: django-storages then returns a
    stable, non-expiring https://storage.googleapis.com/<bucket>/<path> URL.
    Signed URLs are deliberately avoided -- Cloud Run's default service account
    cannot V4-sign without the IAM Credentials API, and share cards must be
    crawler-fetchable (Open Graph) without expiry.
    """
    bucket_name = (bucket_name or '').strip()
    if not bucket_name:
        return {'BACKEND': 'django.core.files.storage.FileSystemStorage'}

    options: dict[str, Any] = {
        'bucket_name': bucket_name,
        'default_acl': None,
        'querystring_auth': False,
        'file_overwrite': True,
    }
    project_id = os.getenv('GS_PROJECT_ID', '').strip()
    if project_id:
        options['project_id'] = project_id
    location = os.getenv('GS_LOCATION', '').strip()
    if location:
        options['location'] = location
    return {
        'BACKEND': 'storages.backends.gcloud.GoogleCloudStorage',
        'OPTIONS': options,
    }


# Hashed + gzipped static assets so WhiteNoise can serve them with far-future
# cache headers (filename embeds content hash -> safe to cache forever).
STORAGES = {
    'default': build_default_storage(os.getenv('GS_BUCKET_NAME', '')),
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
```

- [ ] **Step 2 (note): Credentials: in prod, google-cloud-storage auto-discovers Application Default Credentials from the Cloud Run service account, so no GS_CREDENTIALS is wired. If GOOGLE_APPLICATION_CREDENTIALS points at a key file, the client honors it automatically. No code needed.**

- [ ] **Step 3 (run): Re-run the tests — all four must now PASS (green).**

```
/Users/narekmeloyan/PycharmProjects/JokesForProject/.venv/bin/python manage.py test jokes.tests_storage -v2
```

  - Expected: OK (4 tests). build_default_storage('') -> FileSystemStorage; build_default_storage('jokesfor-media-prod') -> GoogleCloudStorage with default_acl=None, querystring_auth=False; MEDIA_URL truthy; share_image_url absolute; regeneration writes joke-<pk>.png with bytes.

### Task 4: Task 4 — Regression: full existing suite + share-card path

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests.py`

- [ ] **Step 1 (run): Run the whole jokes + notifications suites to confirm nothing regressed (serializers, admin approve path that triggers share-image generation, share page view).**

```
/Users/narekmeloyan/PycharmProjects/JokesForProject/.venv/bin/python manage.py test jokes notifications -v1
```

  - Expected: All pass. The admin approve_and_publish tests (which patch _generate_share_image) and the format-rules tests are unaffected; no new failures.

- [ ] **Step 2 (run): Sanity: django check with a simulated prod env to prove the GCS branch loads and system check passes (no real network call is made at check time).**

```
GS_BUCKET_NAME=jokesfor-media-prod /Users/narekmeloyan/PycharmProjects/JokesForProject/.venv/bin/python manage.py check
```

  - Expected: System check identified no issues. STORAGES['default'] now points at GoogleCloudStorage but is not instantiated/contacted by check.

### Task 5: Task 5 — Docs + Dockerfile note

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/.env.example`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/Dockerfile`

- [ ] **Step 1 (impl): Document the new env vars in .env.example under the Production-only section.**

```
# --- append to .env.example Production-only section ---

# Media storage (durable uploads + generated share cards).
# Leave GS_BUCKET_NAME EMPTY for local dev/tests -> files go to ./media.
# In production (Cloud Run) set it to the public, uniform-access GCS bucket;
# credentials come from the attached service account (Application Default
# Credentials) -- no key file needed. GOOGLE_APPLICATION_CREDENTIALS is only
# for pointing at a local key file during manual prod-like testing.
GS_BUCKET_NAME=
GS_PROJECT_ID=
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

- [ ] **Step 2 (impl): Add a clarifying comment to the Dockerfile collectstatic step so future maintainers know GS_BUCKET_NAME is intentionally absent at build time (collectstatic must use WhiteNoise/local, never GCS).**

```
# --- edit the comment above the collectstatic RUN line ---
# Build-time collectstatic so the static layer is cached and served by WhiteNoise.
# SECRET_KEY/DEBUG values here are throwaway -- nothing sensitive is read.
# GS_BUCKET_NAME is intentionally unset at build time: collectstatic targets the
# WhiteNoise staticfiles storage only; media (GCS) is configured at runtime.
```

- [ ] **Step 3 (note): Operational (out-of-code, document in PR description, not a code step): create the GCS bucket with Uniform bucket-level access; grant allUsers roles/storage.objectViewer for public read; grant the Cloud Run service account roles/storage.objectAdmin (or objectCreator+objectViewer) so uploads succeed; set GS_BUCKET_NAME (and optionally GS_PROJECT_ID) on the Cloud Run service. Existing prod media (if any) regenerates: share cards re-render on next Joke save; avatars must be re-uploaded (they were ephemeral and already lost across revisions).**

### Task 6: Task 6 — Commit

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/requirements.txt`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/.env.example`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/Dockerfile`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests_storage.py`

- [ ] **Step 1 (note): Branch first (currently on main). Commit message is a plain description with NO Co-Authored-By / generated-with footer, per project rules.**

- [ ] **Step 2 (commit): Stage and commit on a feature branch.**

```
cd /Users/narekmeloyan/PycharmProjects/JokesForProject && git checkout -b feat/gcs-media-storage && git add requirements.txt JokesForProject/settings.py .env.example Dockerfile jokes/tests_storage.py && git commit -m "Use Google Cloud Storage for media when GS_BUCKET_NAME is set

Switch STORAGES['default'] to django-storages' GoogleCloudStorage backend in
production (env-gated on GS_BUCKET_NAME), keeping FileSystemStorage as the
local/dev/test default so nothing offline needs GCS. Add MEDIA_URL/MEDIA_ROOT.
Public uniform-access bucket -> non-expiring URLs (default_acl=None,
querystring_auth=False). Share-card and avatar fields route through the default
storage unchanged; PNG generation stays synchronous in Joke.save()."
```

**Decisions made in this plan:**

- *Public-read or signed URLs for share cards vs avatars?* → Public-read for both. Share cards exist to be fetched by social-media crawlers via Open Graph tags (joke_share_page) and must not expire; avatars render on public profiles. Use a Uniform bucket-level-access bucket set to public read with GS_DEFAULT_ACL=None + GS_QUERYSTRING_AUTH=False so .url returns stable non-expiring URLs. Signed URLs are rejected because Cloud Run's default service account cannot V4-sign without enabling the IAM Credentials API (GS_IAM_SIGN_BLOB), and signed URLs expire/break crawler caching. If avatars later need privacy, subclass the backend per-field rather than globally.
- *Do share_image / avatar model fields or the serializers need to change?* → No. Both ImageFields use Django's default storage implicitly, so flipping STORAGES['default'] routes them to GCS with zero model/serializer edits. build_absolute_uri is idempotent on the absolute GCS URL, so views.py:1063, views.py:1282, and both serializer get_share_image_url methods keep working in both FS and GCS modes.
- *How are GCS credentials provided in production?* → Rely on Application Default Credentials from the Cloud Run service account — google-cloud-storage auto-discovers them, so no GS_CREDENTIALS / key file is wired in code. Grant the runtime service account storage.objectAdmin on the bucket. GOOGLE_APPLICATION_CREDENTIALS is supported implicitly for local prod-like testing against a key file.
- *Does this violate the no-worker / no-Celery principle?* → No. The only runtime work (cairosvg PNG render) was already synchronous inside Joke.save()._generate_share_image and stays there. Uploading the rendered bytes to GCS happens inline during the same request via storage.save. No background task, cron, or worker is introduced.
- *Is the static-files (WhiteNoise) pipeline affected?* → No. Only STORAGES['default'] changes; the staticfiles entry stays on whitenoise.storage.CompressedManifestStaticFilesStorage. Dockerfile collectstatic runs at build time with GS_BUCKET_NAME unset, so it never touches GCS — a clarifying comment is added to prevent future regressions.
- *What about already-stored prod media on the ephemeral filesystem?* → It was already being lost on every Cloud Run revision (that's the bug being fixed). Share cards self-heal: they re-render and upload to GCS on the next save of each Joke (consider a one-off management-style re-save only if immediate backfill is needed — out of scope per YAGNI). Avatars must be re-uploaded by users; there is no durable source to migrate from.

**Risks:**

- Cloud Run service account permissions: if the SA lacks storage.objectAdmin on the bucket, uploads 500 at save time (and Joke creation/admin approval fails because _generate_share_image runs inline). Grant the role before flipping GS_BUCKET_NAME.
- Uniform vs fine-grained access mismatch: with Uniform bucket-level access, setting GS_DEFAULT_ACL='publicRead' causes HTTP 400 on upload. The plan deliberately uses default_acl=None + querystring_auth=False; do not set publicRead unless the bucket switches to fine-grained.
- google-cloud-storage 3.12.0 pulls a large tree of google-* transitive deps; confirm the Docker builder stage resolves them and the runtime image size is acceptable. No new system libs are needed (pure-Python + existing certifi/cryptography).
- build_absolute_uri idempotence assumption: it holds for absolute http(s) URLs in Django; the regeneration/absolute-URL tests lock this in for the FS branch. The GCS branch returns an absolute URL by construction (querystring_auth=False), so build_absolute_uri returns it unchanged.
- Tests require a reachable Postgres; if Neon is down, unset DATABASE_URL to use local Postgres (postgres/6969@localhost/jokesfor) per project convention, otherwise the TestCase-based storage tests cannot create the Joke rows.
- If GS_PROJECT_ID is omitted and ADC cannot infer the project (rare on Cloud Run), signed operations could fail — not an issue here since querystring_auth=False avoids signing, but worth setting GS_PROJECT_ID explicitly in prod for clarity.


---

## Un-mock Trending, Favorites & Preferences adapters to use the real backend in production (TDD)

**Goal:** Route trendingAdapter, favoritesAdapter, and preferencesAdapter through the real *Api clients in production by gating them on the existing USE_MOCKS flag (and flipping VITE_USE_REAL_PREFERENCES to true), removing the unconditional mock calls, adding DTO->mock-type mappers so page consumers don't change, fixing the mistyped api.ts methods, and proving each adapter hits the real api when mocks are off via vitest. profileAdapter and draftsAdapter are explicitly OUT of scope (shape gaps documented below).

**Architecture:** The frontend already has the seam: src/lib/api-adapter.ts exposes per-feature adapter objects that the React Query hooks (src/features/*/api.ts) call; pages consume the hook results in camelCase mock shapes. jokesAdapter/dailyJokeAdapter/collectionsAdapter/savedJokesAdapter (L30-119) already branch on `const USE_MOCKS = !import.meta.env.VITE_API_URL || import.meta.env.VITE_USE_MOCKS === 'true'` (L26-27). trendingAdapter (L124-139) and favoritesAdapter (L142-154) currently call the mock unconditionally — that is the entire bug. preferencesAdapter (L250-260) already branches but on a separate flag VITE_USE_REAL_PREFERENCES that defaults to false.

Both deploy workflows (.github/workflows/firebase-hosting-merge.yml L17, firebase-hosting-pull-request.yml L19) already build with VITE_USE_MOCKS=false and VITE_API_URL=the Cloud Run backend. So the moment trending/favorites branch on USE_MOCKS, they become real in prod with no workflow change. Preferences additionally needs the workflow var VITE_USE_REAL_PREFERENCES flipped to 'true' (both files L27/L29) and the same in .env.example.

The non-trivial part is SHAPE MAPPING. The backend returns snake_case and wraps lists in {results:[...]} (often NOT DRF-paginated for the trending/themes/jokesters/tags endpoints), while pages consume the camelCase mock interfaces from src/lib/mock-data.ts. Verified backend shapes (jokes/views.py, jokes/serializers.py):
- GET /jokes/trending/ (paginated): results:[{rank, joke, likes, shares, comments, trending_since}] -> mock TrendingJoke needs {joke, rank, likes, shares, comments, trendingSince}. Only diff is trending_since->trendingSince.
- GET /tags/trending/ (NOT paginated): {results:[{name, slug, count, growth_percent}]} -> mock TrendingTag {name, count, growth}.
- GET /tags/rising/ (NOT paginated): {results:[{name, slug, growth_percent}]} -> consumer wants {name, growth}.
- GET /users/top-jokesters/ (NOT paginated): {results:[{id, name, username, avatar_url, punchline_count, rank, top_vibes}]} -> mock TopJokester {id, name, punchlineCount, rank, avatarUrl?}.
- GET /themes/popular/ (NOT paginated): {results:["name",...]} -> string[].
- GET /favorites/ (DRF-paginated): results:[{id, joke, favorited_at}] -> mock FavoriteJoke {joke, favoritedAt} (consumers also key off id for remove).
- POST /favorites/ -> {id, joke, favorited_at}.
- GET /favorites/stats/: {total_count, top_tone, this_week_count} (snake_case!) -> adapter contract {totalCount, topTone, thisWeekCount}.

Two api.ts bugs to fix while here: (1) trendingApi.* return `unknown` (L412-426) — give them typed DTO returns; (2) FavoriteJokeDTO uses `added_at` (L278) but backend serializer field is `favorited_at`, and favoritesApi.stats (L290-291) is typed camelCase but backend is snake_case — fix both so the adapter mapper compiles honestly.

Pattern to follow exactly: preferencesAdapter's toDTO/fromDTO mappers (api-adapter.ts L202-260) and src/features/create/adapter.ts (USE_REAL branch + fromDTO). Test pattern to follow: src/features/auth/api.verify.test.tsx (vi.mock('@/lib/api') then assert the mocked method was called) plus src/features/create/adapter.test.ts (default mock-path assertion).

IMPORTANT subtlety: USE_MOCKS is computed at module-load from import.meta.env. To test the real path, the test must set import.meta.env.VITE_USE_MOCKS='false' and VITE_API_URL before importing the adapter module, using vi.stubEnv + dynamic import (await import) and vi.resetModules between cases. The api-adapter test file therefore drives env per-test via vi.stubEnv and re-imports the module.

**Tech Stack:** React 18 + Vite + TypeScript; @tanstack/react-query; axios (src/lib/axios.ts); vitest + @testing-library + jsdom (vitest.config.ts, setup src/test/setup.ts); Playwright for e2e. Backend: Django 5.2 + DRF (already deployed, endpoints all exist). Deploy: GitHub Actions -> Firebase Hosting.

**Files:**

| Action | Path | Responsibility |
|---|---|---|
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api.ts` | Add typed return shapes for trendingApi (replace `unknown` at L412-426 with TrendingJokeDTO paginated, TrendingTagDTO[], RisingTagDTO[], ThemesPopularResponse, keep TopJokesterDTO). Fix FavoriteJokeDTO to use favorited_at (not added_at) at L275-279. Fix favoritesApi.stats return type to snake_case {total_count, top_tone, this_week_count} at L290-291. These reflect the ACTUAL backend responses verified in jokes/views.py + serializers.py. |
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api-adapter.ts` | Import trendingApi + favoritesApi. Add fromDTO mappers (trendingJokeFromDTO, trendingTagFromDTO, risingFromDTO, topJokesterFromDTO, favoriteFromDTO, favoriteStatsFromDTO). Rewrite trendingAdapter (L121-139) and favoritesAdapter (L141-154) to branch on the existing USE_MOCKS flag exactly like jokesAdapter, mapping real responses back to the mock camelCase types. Flip preferencesAdapter to also honor USE_MOCKS as a fallback while keeping VITE_USE_REAL_PREFERENCES (so it goes real once either is set). Handle favorites.remove(jokeId): real path must resolve the favorite id from the list before DELETE (backend deletes by favorite id, not joke id). |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api-adapter.test.ts` | New vitest suite. For each adapter method, stub env (VITE_USE_MOCKS='false', VITE_API_URL set) via vi.stubEnv, vi.mock('@/lib/api'), dynamic-import the adapter, assert the real *Api method was called and the DTO was mapped to the camelCase mock shape. Also one default-path test per adapter asserting the mock is used when VITE_USE_MOCKS is unset/true. |
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/.github/workflows/firebase-hosting-merge.yml` | Flip VITE_USE_REAL_PREFERENCES default from 'false' to 'true' at L27 so the preferences adapter writes to the real backend in prod. (VITE_USE_MOCKS already 'false' at L17 — no change needed for trending/favorites.) |
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/.github/workflows/firebase-hosting-pull-request.yml` | Same flip: VITE_USE_REAL_PREFERENCES default 'false' -> 'true' at L29 for preview builds parity. |
| modify | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/.env.example` | Document that VITE_USE_REAL_PREFERENCES now defaults to 'true' in deploy; update the comment at L15-17. Note that trending/favorites are governed by VITE_USE_MOCKS. |

### Task 1: Task 0 — Establish green baseline & confirm env-driven test seam

- [ ] **Step 1 (run): Confirm the existing suite passes before any change, so new failures are attributable.**

```
cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend && npm run test
```

  - Expected: All existing tests pass (auth verify, create adapter, etc.). Record the count.

- [ ] **Step 2 (note): Confirm the USE_MOCKS env seam works with vi.stubEnv + dynamic import. api-adapter.ts computes USE_MOCKS at module top-level (L26-27), so tests MUST vi.resetModules() and await import('@/lib/api-adapter') AFTER vi.stubEnv so the flag re-evaluates. This is the load-bearing technique for every real-path test below.**

### Task 2: Task 1 — Fix api.ts types to match actual backend (red->green via tsc)

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api.ts`

- [ ] **Step 1 (impl): Fix FavoriteJokeDTO to the real serializer shape (favorited_at, not added_at).**

```
// src/lib/api.ts — replace the FavoriteJokeDTO interface (around L275-279)
export interface FavoriteJokeDTO {
  id: number
  joke: Joke
  favorited_at: string
}
```

- [ ] **Step 2 (impl): Fix favoritesApi.stats return type to the real snake_case shape.**

```
// src/lib/api.ts — favoritesApi.stats (around L290-291)
  // Backend returns snake_case; adapter maps to camelCase.
  stats: () =>
    api.get<{ total_count: number; top_tone: string | null; this_week_count: number }>('/favorites/stats/'),
```

- [ ] **Step 3 (impl): Add typed trending DTOs and replace the `unknown` returns in trendingApi.**

```
// src/lib/api.ts — add near the trending section (replacing L410-426)
export interface TrendingJokeDTO {
  rank: number
  joke: Joke
  likes: number
  shares: number
  comments: number
  trending_since: string
}
export interface TrendingTagDTO {
  name: string
  slug: string
  count: number
  growth_percent: number
}
export interface RisingTagDTO {
  name: string
  slug: string
  growth_percent: number
}

export const trendingApi = {
  jokes: (period?: string) =>
    api.get<PaginatedResponse<TrendingJokeDTO>>('/jokes/trending/', { params: { period } }),

  tags: () => api.get<{ results: TrendingTagDTO[] }>('/tags/trending/'),

  risingTags: () => api.get<{ results: RisingTagDTO[] }>('/tags/rising/'),

  themes: () => api.get<{ results: string[] }>('/themes/popular/'),

  jokesters: (limit?: number) =>
    api.get<{ results: TopJokesterDTO[] }>('/users/top-jokesters/', { params: { limit } }),
}
```

- [ ] **Step 4 (run): Type-check compiles with the new shapes (adapter still uses mocks, so no break yet).**

```
cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend && npx tsc -b --noEmit
```

  - Expected: tsc passes. (trendingApi.collections was unused/never wired — removing it is safe; grep confirms no consumers.)

### Task 3: Task 2 — TDD trendingAdapter real path

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api-adapter.test.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api-adapter.ts`

- [ ] **Step 1 (test): Write failing tests asserting trendingAdapter hits the real trendingApi and maps DTO->mock shape when VITE_USE_MOCKS='false'.**

```
// src/lib/api-adapter.test.ts (new)
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const realApi = {
  trendingApi: {
    jokes: vi.fn(),
    tags: vi.fn(),
    risingTags: vi.fn(),
    jokesters: vi.fn(),
    themes: vi.fn(),
  },
  // other api objects stubbed minimally so the module imports cleanly
  jokesApi: {}, dailyJokeApi: {}, collectionsApi: {}, savedJokesApi: {},
  favoritesApi: { list: vi.fn(), add: vi.fn(), remove: vi.fn(), stats: vi.fn() },
  preferencesApi: { get: vi.fn(), update: vi.fn() },
}
vi.mock('@/lib/api', () => realApi)

async function loadAdapterReal() {
  vi.resetModules()
  vi.stubEnv('VITE_API_URL', 'http://x/api/v1')
  vi.stubEnv('VITE_USE_MOCKS', 'false')
  return await import('@/lib/api-adapter')
}

beforeEach(() => vi.clearAllMocks())
afterEach(() => vi.unstubAllEnvs())

describe('trendingAdapter (real path)', () => {
  it('getJokes calls trendingApi.jokes and maps trending_since->trendingSince', async () => {
    realApi.trendingApi.jokes.mockResolvedValue({ data: { count: 1, next: null, previous: null, results: [
      { rank: 1, joke: { id: 9 }, likes: 5, shares: 2, comments: 0, trending_since: '2026-06-01T00:00:00Z' },
    ] } })
    const { trendingAdapter } = await loadAdapterReal()
    const out = await trendingAdapter.getJokes('week')
    expect(realApi.trendingApi.jokes).toHaveBeenCalledWith('week')
    expect(out[0]).toMatchObject({ rank: 1, likes: 5, shares: 2, trendingSince: '2026-06-01T00:00:00Z' })
  })

  it('getTags maps growth_percent->growth from {results}', async () => {
    realApi.trendingApi.tags.mockResolvedValue({ data: { results: [{ name: 'Dad', slug: 'dad', count: 3, growth_percent: 42 }] } })
    const { trendingAdapter } = await loadAdapterReal()
    const out = await trendingAdapter.getTags()
    expect(out[0]).toEqual({ name: 'Dad', count: 3, growth: 42 })
  })

  it('getRisingTopics maps {name, growth_percent}->{name, growth}', async () => {
    realApi.trendingApi.risingTags.mockResolvedValue({ data: { results: [{ name: 'AI', slug: 'ai', growth_percent: 120 }] } })
    const { trendingAdapter } = await loadAdapterReal()
    expect(await trendingAdapter.getRisingTopics()).toEqual([{ name: 'AI', growth: 120 }])
  })

  it('getTopJokesters maps punchline_count->punchlineCount, avatar_url->avatarUrl', async () => {
    realApi.trendingApi.jokesters.mockResolvedValue({ data: { results: [{ id: 1, name: 'Jerry', username: '@j', avatar_url: null, punchline_count: 12, rank: 1, top_vibes: [] }] } })
    const { trendingAdapter } = await loadAdapterReal()
    const out = await trendingAdapter.getTopJokesters(5)
    expect(realApi.trendingApi.jokesters).toHaveBeenCalledWith(5)
    expect(out[0]).toMatchObject({ id: 1, name: 'Jerry', punchlineCount: 12, rank: 1 })
  })

  it('getPopularThemes returns the results string array', async () => {
    realApi.trendingApi.themes.mockResolvedValue({ data: { results: ['Coding', 'Coffee'] } })
    const { trendingAdapter } = await loadAdapterReal()
    expect(await trendingAdapter.getPopularThemes()).toEqual(['Coding', 'Coffee'])
  })
})
```

  - Expected: All 5 trending tests FAIL (adapter still calls mockTrendingApi unconditionally).

- [ ] **Step 2 (impl): Rewrite trendingAdapter to branch on USE_MOCKS with DTO mappers. Add mappers above it.**

```
// src/lib/api-adapter.ts — add trendingApi to the api import (L13)
import { jokesApi, dailyJokeApi, collectionsApi, savedJokesApi, trendingApi, favoritesApi } from './api'
import type { TrendingJokeDTO, TrendingTagDTO, RisingTagDTO, TopJokesterDTO, FavoriteJokeDTO } from './api'

// ── Trending mappers ──
const trendingJokeFromDTO = (d: TrendingJokeDTO): TrendingJoke => ({
  joke: d.joke, rank: d.rank, likes: d.likes, shares: d.shares, comments: d.comments, trendingSince: d.trending_since,
})
const trendingTagFromDTO = (d: TrendingTagDTO): TrendingTag => ({ name: d.name, count: d.count, growth: d.growth_percent })
const risingFromDTO = (d: RisingTagDTO) => ({ name: d.name, growth: d.growth_percent })
const topJokesterFromDTO = (d: TopJokesterDTO): TopJokester => ({ id: d.id, name: d.name, punchlineCount: d.punchline_count, rank: d.rank, avatarUrl: undefined })

// ── Trending Adapter ──
export const trendingAdapter = {
  getJokes: (period?: string): Promise<TrendingJoke[]> =>
    USE_MOCKS ? mockTrendingApi.getJokes(period)
      : trendingApi.jokes(period).then((r) => r.data.results.map(trendingJokeFromDTO)),

  getTags: (): Promise<TrendingTag[]> =>
    USE_MOCKS ? mockTrendingApi.getTags()
      : trendingApi.tags().then((r) => r.data.results.map(trendingTagFromDTO)),

  getRisingTopics: (): Promise<{ name: string; growth: number }[]> =>
    USE_MOCKS ? mockTrendingApi.getRisingTopics()
      : trendingApi.risingTags().then((r) => r.data.results.map(risingFromDTO)),

  getTopJokesters: (limit?: number): Promise<TopJokester[]> =>
    USE_MOCKS ? mockTrendingApi.getTopJokesters(limit)
      : trendingApi.jokesters(limit).then((r) => r.data.results.map(topJokesterFromDTO)),

  getPopularThemes: (): Promise<string[]> =>
    USE_MOCKS ? mockTrendingApi.getPopularThemes()
      : trendingApi.themes().then((r) => r.data.results),
}
```

- [ ] **Step 3 (run): Trending tests now pass.**

```
cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend && npx vitest run src/lib/api-adapter.test.ts
```

  - Expected: 5 trending tests green.

### Task 4: Task 3 — TDD favoritesAdapter real path (incl. remove-by-favorite-id)

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api-adapter.test.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api-adapter.ts`

- [ ] **Step 1 (test): Add failing favorites tests: list maps favorited_at, stats maps snake->camel, add maps DTO, remove resolves favorite id from list then DELETEs.**

```
// append to src/lib/api-adapter.test.ts
describe('favoritesAdapter (real path)', () => {
  it('list maps favorited_at->favoritedAt and preserves pagination', async () => {
    realApi.favoritesApi.list.mockResolvedValue({ data: { count: 1, next: null, previous: null, results: [
      { id: 7, joke: { id: 3 }, favorited_at: '2026-06-01T00:00:00Z' },
    ] } })
    const { favoritesAdapter } = await loadAdapterReal()
    const out = await favoritesAdapter.list({ page: 1 })
    expect(realApi.favoritesApi.list).toHaveBeenCalledWith({ page: 1 })
    expect(out.results[0]).toMatchObject({ favoritedAt: '2026-06-01T00:00:00Z' })
  })

  it('stats maps total_count/top_tone/this_week_count -> camelCase', async () => {
    realApi.favoritesApi.stats.mockResolvedValue({ data: { total_count: 9, top_tone: 'Dad', this_week_count: 2 } })
    const { favoritesAdapter } = await loadAdapterReal()
    expect(await favoritesAdapter.stats()).toEqual({ totalCount: 9, topTone: 'Dad', thisWeekCount: 2 })
  })

  it('add maps the created DTO to FavoriteJoke', async () => {
    realApi.favoritesApi.add.mockResolvedValue({ data: { id: 5, joke: { id: 3 }, favorited_at: '2026-06-02T00:00:00Z' } })
    const { favoritesAdapter } = await loadAdapterReal()
    const out = await favoritesAdapter.add(3)
    expect(realApi.favoritesApi.add).toHaveBeenCalledWith(3)
    expect(out).toMatchObject({ favoritedAt: '2026-06-02T00:00:00Z' })
  })

  it('remove(jokeId) resolves favorite id from list then DELETEs that favorite id', async () => {
    realApi.favoritesApi.list.mockResolvedValue({ data: { count: 1, next: null, previous: null, results: [
      { id: 42, joke: { id: 3 }, favorited_at: 'x' },
    ] } })
    realApi.favoritesApi.remove.mockResolvedValue({})
    const { favoritesAdapter } = await loadAdapterReal()
    await favoritesAdapter.remove(3)
    expect(realApi.favoritesApi.remove).toHaveBeenCalledWith(42)
  })
})
```

  - Expected: 4 favorites tests FAIL (adapter still mock-only).

- [ ] **Step 2 (impl): Rewrite favoritesAdapter with USE_MOCKS branch + mappers. remove() must look up the favorite id by joke id (backend DELETE is by favorite id, but the hook passes a jokeId).**

```
// src/lib/api-adapter.ts — mappers
const favoriteFromDTO = (d: FavoriteJokeDTO): FavoriteJoke => ({ joke: d.joke, favoritedAt: d.favorited_at })

// ── Favorites Adapter ──
export const favoritesAdapter = {
  list: (params?: { tones?: string; page?: number }): Promise<PaginatedResponse<FavoriteJoke>> =>
    USE_MOCKS ? mockFavoritesApi.list(params)
      : favoritesApi.list(params).then((r) => ({ ...r.data, results: r.data.results.map(favoriteFromDTO) })),

  add: (jokeId: number): Promise<FavoriteJoke> =>
    USE_MOCKS ? mockFavoritesApi.add(jokeId)
      : favoritesApi.add(jokeId).then((r) => favoriteFromDTO(r.data)),

  remove: (jokeId: number): Promise<void> =>
    USE_MOCKS ? mockFavoritesApi.remove(jokeId)
      : favoritesApi.list().then((r) => {
          const fav = r.data.results.find((f) => f.joke.id === jokeId)
          if (!fav) return undefined
          return favoritesApi.remove(fav.id).then(() => undefined)
        }),

  stats: (): Promise<{ totalCount: number; topTone: string; thisWeekCount: number }> =>
    USE_MOCKS ? mockFavoritesApi.stats()
      : favoritesApi.stats().then((r) => ({
          totalCount: r.data.total_count,
          topTone: r.data.top_tone ?? '',
          thisWeekCount: r.data.this_week_count,
        })),
}
```

- [ ] **Step 3 (run): Favorites tests pass.**

```
cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend && npx vitest run src/lib/api-adapter.test.ts
```

  - Expected: trending + favorites tests all green.

### Task 5: Task 4 — preferencesAdapter: honor USE_MOCKS as fallback + default-path tests

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api-adapter.test.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api-adapter.ts`

- [ ] **Step 1 (test): Add a test: when VITE_USE_MOCKS='false' AND VITE_USE_REAL_PREFERENCES unset, preferencesAdapter.get still hits the real preferencesApi (mocks off in prod should mean real prefs). Also add default-path tests for trending/favorites asserting the MOCK is used when env is mock-mode.**

```
// append to src/lib/api-adapter.test.ts
async function loadAdapterMock() {
  vi.resetModules()
  vi.stubEnv('VITE_API_URL', '')
  vi.stubEnv('VITE_USE_MOCKS', 'true')
  return await import('@/lib/api-adapter')
}

describe('preferencesAdapter (real path via USE_MOCKS=false)', () => {
  it('get() calls preferencesApi.get and maps fromDTO when mocks are off', async () => {
    realApi.preferencesApi.get.mockResolvedValue({ data: { humor_types: ['dad'], theme: 'dark' } })
    const { preferencesAdapter } = await loadAdapterReal()
    const out = await preferencesAdapter.get()
    expect(realApi.preferencesApi.get).toHaveBeenCalled()
    expect(out.humorTypes).toEqual(['dad'])
    expect(out.theme).toBe('dark')
  })
})

describe('default mock path', () => {
  it('trendingAdapter.getTags does NOT call the real api when mocks on', async () => {
    const { trendingAdapter } = await loadAdapterMock()
    await trendingAdapter.getTags()
    expect(realApi.trendingApi.tags).not.toHaveBeenCalled()
  })
  it('favoritesAdapter.stats does NOT call the real api when mocks on', async () => {
    const { favoritesAdapter } = await loadAdapterMock()
    await favoritesAdapter.stats()
    expect(realApi.favoritesApi.stats).not.toHaveBeenCalled()
  })
})
```

  - Expected: The preferences real-path test FAILS (currently gated only on VITE_USE_REAL_PREFERENCES, which is unset here); default-path tests pass.

- [ ] **Step 2 (impl): Make preferences go real when EITHER USE_REAL_PREFERENCES is true OR mocks are off (USE_MOCKS false). This aligns prefs with trending/favorites so a single VITE_USE_MOCKS=false makes the whole app real, while keeping the explicit override.**

```
// src/lib/api-adapter.ts — change the gate (L200) and the adapter body (L250-260)
const USE_REAL_PREFERENCES =
  import.meta.env.VITE_USE_REAL_PREFERENCES === 'true' || !USE_MOCKS

// preferencesAdapter body unchanged (already branches on USE_REAL_PREFERENCES)
```

- [ ] **Step 3 (run): Full adapter suite green.**

```
cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend && npx vitest run src/lib/api-adapter.test.ts
```

  - Expected: All trending + favorites + preferences + default-path tests pass.

### Task 6: Task 5 — Flip deploy flags + env docs

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/.github/workflows/firebase-hosting-merge.yml`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/.github/workflows/firebase-hosting-pull-request.yml`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/.env.example`

- [ ] **Step 1 (impl): merge.yml: flip VITE_USE_REAL_PREFERENCES default to 'true' (L27).**

```
          VITE_USE_REAL_PREFERENCES: ${{ vars.VITE_USE_REAL_PREFERENCES || 'true' }}
```

- [ ] **Step 2 (impl): pull-request.yml: same flip (L29).**

```
          VITE_USE_REAL_PREFERENCES: ${{ vars.VITE_USE_REAL_PREFERENCES || 'true' }}
```

- [ ] **Step 3 (impl): .env.example: update the comment block (L15-17) to reflect that prefs default real in deploy and trending/favorites follow VITE_USE_MOCKS.**

```
# Trending & Favorites follow VITE_USE_MOCKS (real backend when VITE_USE_MOCKS=false).
# Preferences: real when VITE_USE_MOCKS=false OR VITE_USE_REAL_PREFERENCES=true.
# Deploy workflows build with VITE_USE_MOCKS=false and VITE_USE_REAL_PREFERENCES=true.
VITE_USE_REAL_PREFERENCES=
```

- [ ] **Step 4 (note): No change needed to VITE_USE_MOCKS in either workflow — already 'false'. That single flag now makes trending + favorites real. Confirm no GitHub repo-level `vars.VITE_USE_MOCKS` override is set to 'true' in the repo settings (if it is, trending/favorites stay mocked); call this out for the user to check in repo Settings > Variables.**

### Task 7: Task 6 — Full verification (types, unit, build)

- [ ] **Step 1 (run): Type-check the whole frontend with the new mappers and types.**

```
cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend && npx tsc -b --noEmit
```

  - Expected: Clean. Pages consume unchanged camelCase shapes; adapters return those shapes; no type errors.

- [ ] **Step 2 (run): Run the full unit suite (ensures no regressions in auth/create/other adapters).**

```
cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend && npm run test
```

  - Expected: All tests pass, including the new api-adapter.test.ts.

- [ ] **Step 3 (run): Production-style build with mocks off to catch any prod-only type/env issue.**

```
cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend && VITE_USE_MOCKS=false VITE_USE_REAL_PREFERENCES=true VITE_API_URL=https://jokesforbackend-332865216810.us-east1.run.app/api/v1 npm run build
```

  - Expected: Build succeeds (tsc -b && vite build).

- [ ] **Step 4 (commit): Commit with a plain description (no Co-Authored-By footer, per project rule).**

```
git add -A && git commit -m "frontend: route trending, favorites, preferences adapters through real backend

- gate trendingAdapter and favoritesAdapter on existing USE_MOCKS flag
- add DTO->mock-type mappers so page consumers stay unchanged
- fix FavoriteJokeDTO (favorited_at) and favoritesApi.stats snake_case types
- type trendingApi responses (were unknown)
- preferences go real when mocks off or VITE_USE_REAL_PREFERENCES=true
- flip VITE_USE_REAL_PREFERENCES default to true in deploy workflows
- vitest proves each adapter hits the real api when mocks are off"
```

### Task 8: Task 7 (optional) — e2e smoke against real prod build

- [ ] **Step 1 (note): If desired, add/extend a Playwright spec that loads /trending and /favorites against a build with VITE_USE_MOCKS=false pointed at a staging backend, asserting the network calls go to /api/v1/jokes/trending/ etc. Keep this OUT of the default CI unit run (e2e is excluded in vitest.config.ts and run separately via npm run e2e). YAGNI: only add if the team wants live-network coverage; the unit tests already prove the routing.**

**Decisions made in this plan:**

- *Should profileAdapter and draftsAdapter also be flipped to real in this change?* → No — keep them OUT of scope (YAGNI; the settled work-stream is Trending, Favorites, Preferences). They have real shape gaps that would balloon the change: (1) profileAdapter.getActivity — backend /users/me/activity/ returns {results:[{id, type, description, created_at}]} but the mock ActivityItem needs {timeAgo, icon} which the backend does not provide (would require client-side relative-time formatting + an icon map). (2) profileAdapter.get maps cleanly (member_since->memberSince, is_premium->isPremium, humor_dna->humorDNA) and could be done, but achievements maps {unlocked_at->unlockedAt} and activity is the blocker. (3) draftsApi exists and is wired, but mock DraftJoke uses {setup, punchline, format:string, status:'draft'|'pending'|'published'|'rejected', tones:string[], lastEditedAt} while DraftJokeDTO uses {text, format:object, status:'draft'|'submitted'|'approved'|'rejected', created_at/updated_at} — a non-trivial bidirectional mapper. Document these as a clearly-scoped follow-up rather than bundling.
- *How to test the real path given USE_MOCKS is computed once at module load?* → Use vi.stubEnv + vi.resetModules() + dynamic `await import('@/lib/api-adapter')` per test, with vi.mock('@/lib/api') providing spy objects. This is the only reliable way because the flag is a top-level const; a beforeAll import would freeze the flag. Mirror the create/adapter.test.ts default-path style for the mock-on cases.
- *favoritesAdapter.remove takes a jokeId but the backend DELETEs by favorite id — how to reconcile?* → In the real path, fetch /favorites/, find the favorite whose joke.id === jokeId, then DELETE that favorite id. This keeps the hook signature (mutationFn: (jokeId) => ...) and the optimistic-update logic in features/favorites/api.ts unchanged. Alternative (cleaner long-term) would be to thread the favorite id through the UI, but that changes the hook contract and the page — out of scope for an un-mock. The list-then-delete adds one GET but is correct and YAGNI-appropriate. Add a backend follow-up note to support DELETE /favorites/?joke=<id> if the extra round-trip ever matters.
- *Should preferences keep its own VITE_USE_REAL_PREFERENCES flag or just use USE_MOCKS?* → Keep the flag but OR it with !USE_MOCKS. Rationale: the flag was added to let prefs go real independently before the rest of the app; folding it into USE_MOCKS=false means a single prod flag flips everything, while the explicit override still allows enabling prefs in an otherwise-mocked build. Then default VITE_USE_REAL_PREFERENCES to 'true' in the workflows for clarity/parity. This is backward-compatible and removes a footgun where prod (mocks off) was silently still writing prefs to a mock.
- *trendingApi.collections() returns unknown and is never consumed — remove it?* → Yes, remove it while typing trendingApi (grep shows zero consumers and no adapter method maps to it). Keeps the surface honest. If you prefer minimal churn, leaving it typed as unknown is acceptable, but removing dead code is the YAGNI-consistent choice.

**Risks:**

- A repo-level GitHub Actions variable `vars.VITE_USE_MOCKS` set to 'true' would override the workflow default 'false' and keep trending/favorites mocked in prod despite this change. Must verify in repo Settings > Secrets and variables > Actions that no such variable exists (the `vars.X || 'false'` pattern means a set var wins).
- Backend trending/tags/themes/jokesters endpoints return {results:[...]} but are NOT DRF-paginated (no count/next/previous) — except /jokes/trending/ and /favorites/ which ARE paginated. The mappers must read r.data.results directly for the non-paginated ones and r.data.results (+ keep count/next/previous) for the paginated ones. Getting this wrong yields runtime 'cannot read results of undefined'. The plan's mappers are written to the verified shapes; re-verify against a live response before shipping if the backend changed since 2026-06-15.
- favoritesApi.stats backend returns top_tone possibly null (no favorites yet); the adapter coerces to '' to satisfy the {topTone: string} contract. Confirm the Favorites page renders '' acceptably (empty state) rather than showing a literal empty pill.
- Email-verification gate is LIVE — favorites/preferences endpoints require an authenticated, verified user. In prod, unauthenticated/unverified users hitting these (e.g., via React Query on mount) will get 401/403 instead of mock data. Ensure the pages/guards already require auth for Favorites/Preferences (Trending tags/jokes are AllowAny on the backend, so those still work logged-out). Verify routing guards before flipping, or the logged-out experience regresses from 'shows mocks' to 'shows errors'.
- The remove-by-favorite-id list-then-delete adds a GET before each unfavorite; if a user spams unfavorite, there's a small race (list may be stale). React Query invalidation after onSettled mitigates it, but note it. Acceptable for now.
- import.meta.env type: VITE_USE_MOCKS is already declared in vite-env.d.ts; no .d.ts change needed for this work. VITE_USE_REAL_PREFERENCES is also already declared (optional). No new env vars are introduced, so vite-env.d.ts needs no edit.


---
