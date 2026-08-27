# Backend Testing & Quality Map — JokesFor (`/Users/narekmeloyan/PycharmProjects/JokesForProject`)

Analysis date: 2026-08-25, repo @ `56e4945` (main). All facts below come from reading code/config;
where docs disagree with code it is called out. Nothing in the repo was modified; the only things
executed were read-only (`ruff check`, `bandit`, `import cairosvg` probe, `grep`, `python` counting scripts).

---

## 1. Test runner

| Item | Fact | Evidence |
|---|---|---|
| Runner | Django's built-in `manage.py test` (`django.test.runner.DiscoverRunner`) | `manage.py` is the stock Django stub; `JokesForProject/settings.py` has **no** `TEST_RUNNER` override |
| pytest | **Not configured anywhere.** No `pytest.ini`, `setup.cfg`, `tox.ini`, `conftest.py`; `pyproject.toml` has no `[tool.pytest.*]`; `pytest`/`pytest-django` absent from `requirements.txt` and from `.venv/bin` | `ls pytest.ini setup.cfg tox.ini conftest.py` → all missing |
| Discovery pattern | Django default `test*.py` — matches all three naming styles in use: `tests.py`, `tests_*.py`, `test_*.py`, plus `tests/test_*.py` packages (each `tests/` dir has `__init__.py`) | `billing/tests/__init__.py`, `creator_insights/tests/__init__.py`, `notifications/tests/__init__.py`, `JokesForProject/tests/__init__.py` exist |
| Coverage | None. No `coverage`/`.coveragerc`, nothing in CI | `ls .coveragerc` missing; `grep -i coverage requirements.txt` empty |
| Type checking | None (no mypy/pyright config) | dotfiles listing |
| pre-commit | None (`.pre-commit-config.yaml` absent) | dotfiles listing |
| Python | 3.11.0 in `.venv` (`.venv/bin/python --version`); CI uses 3.11; Docker `python:3.11-slim` | |
| Framework versions | Django 5.2.17, DRF 3.16.1, freezegun 1.5.5, stripe 12.2.0, cairosvg 2.9.0, google-cloud-vision 3.10.2, django-storages[google] 1.14.6, django-pgtrigger 4.17.0 | `requirements.txt` |

`.planning/codebase/TESTING.md` (dated 2026-01-11) says "No tests currently exist" and recommends
pytest-django/factory_boy/coverage. **It is fully stale**: 834 tests exist, none of those recommendations
were adopted. Treat that file as historical only.

---

## 2. Test file layout and counts

Total: **52 test files, 834 `def test_` methods** (my count; matches `Docs/Testing/2026-08-25-e2e-verification/00-run-log.md` line 27).

Historical size for context (from docs): 143 tests (2026-06-16, `Docs/superpowers/2026-06-16-wave1-decisions-and-user-action-items.md:61`) → 362 (2026-06-19, `Docs/2026-06-19-iteration-review.md:90`) → 834 today.

### Per app (tests / lines)

**jokes/ — 479 tests, 22 files, flat layout (mix of `tests.py`, `tests_*.py`, `test_*.py`)**

| File | tests | lines | Topic |
|---|---|---|---|
| `jokes/tests.py` | 54 | 757 | core models/API (incl. SimpleTestCase units) |
| `jokes/tests_appeals.py` | 78 | 1503 | DSA appeals, SLA queue, quarantine/reversal |
| `jokes/tests_media_wave2.py` | 61 | 1125 | video/audio/GIF pipeline (28 need ffmpeg), format rules, watch telemetry |
| `jokes/tests_media.py` | 62 | 963 | media assets, uploads, SafeSearch screening, locking |
| `jokes/tests_compliance.py` | 54 | 868 | age gate, reports, takedown, COPPA/DSA flows |
| `jokes/tests_share_cards.py` | 25 | 773 | **real** cairosvg share-card rendering (needs libcairo) |
| `jokes/tests_telemetry.py` | 22 | 357 | reveal/view telemetry |
| `jokes/tests_moderation.py` | 18 | 216 | removed-joke serving gates |
| `jokes/tests_sitemap.py` | 18 | 188 | `/sitemap.xml` |
| `jokes/test_paywall.py` | 11 | 253 | freemium 10 reveals/day, `is_locked`, `/daily-reads` (freezegun) |
| `jokes/test_streak_time_progression.py` | 11 | 257 | streak signal across frozen days |
| `jokes/tests_identity.py` | 9 | 115 | Google OAuth identity (adapters patched) |
| `jokes/tests_share_page.py` | 9 | 181 | `/s/<joke>` share page redirect/OG/JSON-LD |
| `jokes/test_time_progression.py` | 8 | 298 | daily joke, mystery box, history window (freezegun) |
| `jokes/tests_creator_fk.py` | 7 | 131 | creator FK backfill/behaviour |
| `jokes/tests_csrf.py` | 7 | 140 | cookie-JWT CSRF enforcement |
| `jokes/tests_launch_blockers.py` | 7 | 156 | P0 launch-blocker regressions |
| `jokes/tests_google_age_gate.py` | 5 | 142 | Google sign-up age gate |
| `jokes/tests_storage.py` | 5 | 131 | `build_default_storage()` FS vs GCS config, absolute share URLs |
| `jokes/tests_backfill_share_cards.py` | 4 | 72 | `backfill_share_cards` mgmt command (via `call_command`) |
| `jokes/tests_feed_n1.py` | 3 | 165 | feed query-count (N+1) guard |
| `jokes/test_reset_roundtrip.py` | 1 | 43 | password reset email → confirm round trip |

**billing/tests/ — 94 tests, 7 files (package)**

| File | tests | lines |
|---|---|---|
| `test_entitlements.py` | 21 | 138 |
| `test_tips.py` | 19 | 326 |
| `test_checkout_portal.py` | 18 | 258 |
| `test_webhook.py` | 17 | 468 |
| `test_gating.py` | 9 | 192 |
| `test_quota_lazy_reset.py` | 8 | 142 |
| `test_quota_time_progression.py` | 2 | 72 |

**creator_insights/tests/ — 89 tests, 5 files**: `test_services.py` 45 (974 lines), `test_profile.py` 20, `test_compliance.py` 10, `test_views.py` 10, `test_permissions.py` 4.

**notifications/tests/ — 83 tests, 12 files**: `test_digests.py` 24 (558 lines), `test_unsubscribe.py` 15, `test_digest_trigger.py` 14, `test_verification.py` 8, `test_verify_resend.py` 6, `test_models.py` 4, `test_registration_flow.py` 3, `test_throttling.py` 3, `test_engine.py` 2, `test_templates.py` 2, `test_google_exemption.py` 1, `test_throttle_cache.py` 1.

**JokesForProject/tests/ — 41 tests, 3 files**: `test_observability.py` 28 (logging/trace/Sentry scrub — SimpleTestCase), `test_healthz.py` 8 (`/healthz`, `/readyz`), `test_security_settings.py` 5 (SimpleTestCase).

**Single-file apps**: `follows/tests.py` 24, `inbox/tests.py` 13, `audit/tests.py` 11.

**Apps/dirs with no tests**: `media/` and `ops/` are not Django apps (`media/` = `MEDIA_ROOT` upload dir with `media-assets/` + `share-cards/`; `ops/monitoring/` = ops config). Every app in `INSTALLED_APPS` (`jokes`, `notifications`, `creator_insights`, `follows`, `audit`, `billing`, `inbox`) has tests.

---

## 3. Base classes, fixtures, factories

- **Base classes used** (class-declaration count): `TestCase` 143, `APITestCase` (DRF) 61, `SimpleTestCase` 8 (in `jokes/tests.py`, `JokesForProject/tests/test_observability.py`, `JokesForProject/tests/test_security_settings.py`). **No** `TransactionTestCase`/`LiveServerTestCase` anywhere → every DB test runs inside a rolled-back transaction, so DatabaseCache throttle counters and mail outbox are isolated per test.
- **Project-local base classes** (not shared across files):
  - `jokes/test_paywall.py:51 class _Base(APITestCase)` — `setUpTestData` creates `free@example.com`, `setUp` force-authenticates, helpers `_consume(count)`, `_retrieve(joke)`, `_status()`.
  - `jokes/tests_moderation.py:41 class ModerationBase(TestCase)` — fetches seeded `Format(slug='oneliner')`, `AgeRating.first()`, `Language(code='en')`, creates creator/viewer users.
  - `jokes/test_streak_time_progression.py:47 class _StreakBase(APITestCase)` — 10 jokes, `view_on(when, joke)` creates a `JokeView` inside `freeze_time`.
- **No factory_boy / model-bakery / Django fixtures (`fixtures = [...]`)**. Test data is built with ad-hoc module-level helpers, one per file: `_make_joke`, `_make_user`, `_make_published_submission`, `make_asset`, `make_image_joke`, `make_video_asset`, `make_audio_asset`, `make_clip`/`make_gif`/`make_audio` (ffmpeg-generated), `_make_stripe_event` (`billing/tests/test_webhook.py:13`), `make_creator`, etc. (full list in §Appendix A).
- **Cross-file helper imports** (a de-facto shared fixture module): `jokes/tests_media.py` exports `make_user`, `make_asset`, `make_image_joke`, `_taxonomy`, `locked_state`, imported by `jokes/tests_appeals.py:50`, `jokes/tests_media_wave2.py:411,650`, `jokes/tests_share_cards.py:48`, `creator_insights/tests/test_services.py:883`. Renaming helpers in `tests_media.py` breaks four other files.
- **Seed data comes from data migrations, not fixtures.** Tests call `Format.objects.get(slug='oneliner'|'setup')`, `Language.objects.get(code='en')`, `AgeRating.objects.first()`, `Tone.objects.all()[:2]` and rely on: `jokes/migrations/0013_seed_vibes.py`, `0021_seed_demo_data.py` (`seed_taxonomy`, `seed_vibe_recipes`, `seed_jokes` — ~158 demo joke dicts, so the test DB is **not empty** of jokes), `0031_seed_image_format.py`, `0032_seed_video_audio_formats.py`. Consequences: (a) the test DB must be migrated (default behaviour; `--keepdb` still applies pending migrations); (b) count-based assertions against `Joke.objects` must account for seeded rows; (c) `creator_insights/tests/test_services.py:669` raises `cls.skipTest("Need at least 2 Tone objects in fixture")` from `setUpTestData` if the Tone seed is missing (skips the whole class).
- `setUpTestData` is used in 25 files; `override_settings` in 26 files (heaviest: `jokes/tests_appeals.py` 14, `billing/tests/test_checkout_portal.py` 13, `jokes/tests_media.py` 12, `notifications/tests/test_digests.py` 12).
- `notifications/tests/test_throttle_cache.py:25` calls `call_command('createcachetable', 'jokesfor_cache')` to prove the DatabaseCache table exists; `jokes/tests_backfill_share_cards.py` drives the `backfill_share_cards` command through `call_command`.

---

## 4. Time control, mocks, and external services

### freezegun (`freezegun==1.5.5`)
Used in 9 files (occurrence counts): `notifications/tests/test_digests.py` 27, `jokes/test_time_progression.py` 15, `jokes/tests_appeals.py` 12, `jokes/test_streak_time_progression.py` 11, `jokes/tests_media.py` 6, `jokes/test_paywall.py` 5, `billing/tests/test_quota_time_progression.py` 5, `notifications/tests/test_unsubscribe.py` 3, `notifications/tests/test_digest_trigger.py` 2. Canonical frozen instant is `2026-07-14T12:00:00Z` (paywall/daily-joke/history tests). `billing.entitlements.date` is patched directly in 2 places instead of freezegun.

### Patch targets (unique, with counts) — `unittest.mock.patch` only, no `responses`/`requests-mock`/`vcr`
| Target | count | Purpose |
|---|---|---|
| `jokes.models.Joke._generate_share_image` (+5 `patch.object(Joke, ...)`) | 43 | Skip cairosvg rendering on every `Joke.objects.create()` in ordinary tests |
| `billing.stripe_gateway.stripe` | 11 | Stripe SDK module replaced with `MagicMock` (checkout, portal, tips, webhooks) |
| `notifications.views.run_daily_digests` | 7 | `/internal/run-digests/` trigger tests |
| `jokes.media_screening._client` | 4 | Google Vision `ImageAnnotatorClient` stub |
| `jokes.media_processing.probe_media` / `_run_ffmpeg` / `_spool_to_disk` | 3/3/2 | ffmpeg pipeline faults, timeouts, spool reuse |
| `jokes.views.screen_image` | 2 | SafeSearch outcome injection |
| `django.db.connection.cursor` | 2 | `/readyz` 503 when DB down (`JokesForProject/tests/test_healthz.py:20,41`) |
| `django.core.cache.cache.set` | 1 | `/readyz` 503 when cache down |
| `GoogleOAuth2Adapter.complete_login` / `.parse_token`, `OAuth2Client.get_access_token` | 1 each | Google sign-in without network (`tests_identity.py`, `tests_google_age_gate.py`) |
| `EmailMultiAlternatives.send`, `notifications.digests.send_email`, `notifications.service.send_email` | 1 each | fault injection ("flaky_transport_send") |
| `FieldFile.delete` / `FieldFile.open`, `jokes.models.default_storage.delete`, `MediaAsset.save`, `MediaAsset.quarantine`, `Joke.regenerate_share_image`, `Image.MAX_IMAGE_PIXELS`, `audit.models.AuditLog.objects.create`, `jokes.serializers.Appeal.objects.filter`, `jokes.views._mystery_pool_for_user` | 1–2 each | storage/ordering-trap/fault-injection cases |

`notifications/tests/test_engine.py` defines a `BoomBackend(BaseEmailBackend)` and injects it via `override_settings(EMAIL_BACKEND='notifications.tests.test_engine.BoomBackend')`.

### External-service isolation (why the suite is network-free)
- **Stripe**: dormant unless `STRIPE_SECRET_KEY` set (`settings.py:508`); tests use `@override_settings(STRIPE_SECRET_KEY='')` for the 503 dormant path (`billing/tests/test_checkout_portal.py:18-30`, `test_tips.py:123`) and patch `billing.stripe_gateway.stripe` for the active path. Webhook tests build events via `_make_stripe_event` and patch signature verification.
- **Google Vision / SafeSearch**: `SAFESEARCH_ENABLED` defaults off (`settings.py:284`); `jokes/media_screening.py:36` returns early when disabled; when enabled in tests, `jokes.media_screening._client` (line 27) is patched.
- **GCS**: `STORAGES['default']` is `FileSystemStorage` unless `GS_BUCKET_NAME` is set (`settings.py:241-281`). `jokes/tests_storage.py` only asserts the config dict returned by `build_default_storage('jokesfor-media-prod')` — it never instantiates `GoogleCloudStorage`. Media tests use `override_settings(MEDIA_ROOT=tempfile.mkdtemp())` and clean up in `tearDownClass`.
- **Email**: Django's runner forces `locmem` regardless of `.env`'s `EMAIL_BACKEND=anymail...resend`; many notification tests additionally `override_settings(EMAIL_BACKEND=locmem, EMAIL_VERIFICATION_REQUIRED=True)`.
- **Sentry**: no-op when `SENTRY_DSN` empty (`settings.py:631`); `test_observability.py` tests `scrub_event` as a pure function.
- **Google OAuth**: allauth adapters patched (above).
- **Net result: no test performs real network I/O.** The only network in the pipeline is CI's `pip install` and `pip-audit` (PyPI advisory DB), both outside the test run.

---

## 5. External binaries and system libraries

### ffmpeg (video/audio/GIF normalisation)
- Source: `jokes/media_processing.py:236` `subprocess.run([...], timeout=FFMPEG_TIMEOUT=240)`; `jokes/media_probe.py:37` (ffprobe). Only these two modules shell out.
- Tests: `jokes/tests_media_wave2.py:12 FFMPEG = shutil.which('ffmpeg')`; helper fixtures `make_clip`/`make_gif`/`make_audio`/`make_audio_with_cover` (lines 17-70) **invoke real ffmpeg** with `timeout=60` to synthesise inputs. **28 tests in 8 classes are `@unittest.skipUnless(FFMPEG, 'ffmpeg not installed')`** (`ProbeTests` 3, `FfmpegDiagnosticsLoggingTests` 2, `VideoPipelineTests` 8, `SpoolReuseTests` 2, `AudioPipelineTests` 2, `CoverArtProbeTests` 2, `MediaUploadWave2Tests` 8, `EncodeConcurrencyGuardTests` 1); the other 33 in that file run without ffmpeg. Without ffmpeg the suite still passes with 28 skips — **watch the "skipped=28" line, it silently drops pipeline coverage.**
- Locally: `/opt/homebrew/bin/ffmpeg` + `ffprobe` present (ffmpeg 8.1.2 per run-log). CI: `apt-get install ffmpeg`.

### cairo / pango (cairosvg share cards)
- `jokes/share_cards.py:6 import cairosvg` at module top; imported **lazily** from `Joke._generate_share_image` (`jokes/models.py:248`), so app import/`manage.py check` never touches cairo — only tests that let real card generation run do.
- Tests that **need libcairo** (no `skipUnless` guard, so they ERROR, not skip, if missing): `jokes/tests_share_cards.py` (25 tests; docstring lines 3-6: "Deliberately does NOT patch Joke._generate_share_image / cairosvg ... Requires a working libcairo"), and any path that calls `regenerate_share_image` unpatched (`jokes/tests_backfill_share_cards.py` patches it in 2 places; `jokes/tests_launch_blockers.py:61` and `jokes/tests_storage.py:116` explicitly avoid cairo).
- **macOS gotcha (verified on this machine)**: `.venv/bin/python -c "import cairosvg"` fails with `cannot load library 'libcairo-2.dll'` even though Homebrew has `/opt/homebrew/lib/libcairo*.dylib`. Fix: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` (documented as F-002 in `Docs/Testing/2026-08-25-e2e-verification/00-run-log.md:49`). Comments in `tests_launch_blockers.py:61` / `tests_storage.py:117` claiming libcairo is "not present in CI" are **stale**: CI now installs `libcairo2 libpango-1.0-0 libpangocairo-1.0-0` (`ci.yml` "Install system dependencies").
- Dockerfile runtime stage installs the same libs + ffmpeg, and `cloudbuild.yaml` runs `migrate` inside the built image precisely because cairosvg import would crash on a slim image (`Docs/2026-06-19-iteration-review.md:32`).

### Postgres
- Hard requirement: `ENGINE=django.db.backends.postgresql` only (`settings.py:145`), `pgtrigger` in `INSTALLED_APPS` (Postgres triggers), `DatabaseCache` table `jokesfor_cache` created by `notifications/migrations/0002_create_cache_table.py`. SQLite is not an option.
- The runner creates/destroys `test_<DB_NAME>` (`test_jokesfor` locally/CI, `test_neondb` against Neon) → **DB role needs `CREATEDB`** (CI comment in `ci.yml` "postgres user ... already has CREATEDB").
- Known hazard (docs): the Neon `test_neondb` was left half-migrated by an interrupted run and `--keepdb` then failed with a `content_type UniqueViolation` (`Docs/superpowers/2026-06-17-observability-design.md:54,67`). Use `--noinput` (recreates) or the local fallback.

---

## 6. Database selection: how to force local Postgres

`JokesForProject/settings.py:20-22` — `from dotenv import load_dotenv; load_dotenv()` (default `override=False`: **shell env vars beat `.env`**).

`settings.py:141-171 _build_default_db()`:
1. `url = os.getenv('DATABASE_URL', '').strip()` — if **non-empty**, parse it (`NAME` from path, `OPTIONS` from query string e.g. `sslmode`, `channel_binding`; `DISABLE_SERVER_SIDE_CURSORS=True` when hostname contains `-pooler`).
2. Else fall back to `DB_NAME` (default `jokesfor`), `DB_USER` (`postgres`), `DB_PASSWORD` (`''`), `DB_HOST` (`localhost`), `DB_PORT` (`5432`).

Local `.env` (values masked; keys only): sets `DATABASE_URL=postgresql://***@ep-round-brook-aq0p3j8j-pooler.c-8.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require` **and** `DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432` (lines 21-25), `DEBUG=True`, `EMAIL_VERIFICATION_REQUIRED=true`, `EMAIL_BACKEND=anymail.backends.resend.EmailBackend`, real `STRIPE_SECRET_KEY`/`RESEND_API_KEY` present, `GS_BUCKET_NAME` not set, `SAFESEARCH_ENABLED` not set.

**Therefore**: running `manage.py test` bare in this checkout hits **Neon** (and creates `test_neondb` there). To force local Postgres you must export an empty `DATABASE_URL=''` on the command line — because the variable then *exists* in the process env, `load_dotenv` will not overwrite it, `.strip()` yields `''`, and the `DB_*` branch is taken (the `DB_*` values already in `.env` are `postgres/6969@localhost:5432/jokesfor`, matching the project notes; passing them explicitly is belt-and-braces). CI does exactly this (`DATABASE_URL: ''` + `DB_*` in `ci.yml`).

Other `.env` effects on tests: `DEBUG=True` is required (with `DEBUG=False`, `SECURE_SSL_REDIRECT=True` 301s every test-client request — `ci.yml` comment, `settings.py:403-413`); `EMAIL_VERIFICATION_REQUIRED=true` only matters for tests that don't override it (all verification tests override explicitly); a live `STRIPE_SECRET_KEY` is neutralised by `override_settings`/patching in billing tests. CI runs with **no `.env` at all**, so local-vs-CI divergence is possible for any test that reads an env-derived setting without `override_settings` — none were found in a grep of `EMAIL_VERIFICATION_REQUIRED|STRIPE_SECRET_KEY|BILLING_ENABLED|SAFESEARCH_ENABLED|GS_BUCKET_NAME` in tests, but the risk is structural.

---

## 7. Exact commands

Prefix used everywhere below (run from the repo root; `.venv` has all deps):

```bash
cd /Users/narekmeloyan/PycharmProjects/JokesForProject
export DATABASE_URL='' DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 \
       DEBUG=True DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
```

| Goal | Command |
|---|---|
| Full suite (fresh test DB, non-interactive; recreates `test_jokesfor`) | `.venv/bin/python manage.py test --noinput` |
| Full suite, faster re-runs (reuse test DB; still applies new migrations) | `.venv/bin/python manage.py test --keepdb` |
| Verbose per-test names + stop at first failure | `.venv/bin/python manage.py test -v 2 --failfast` |
| One app | `.venv/bin/python manage.py test billing` (also `jokes`, `notifications`, `creator_insights`, `follows`, `audit`, `inbox`, `JokesForProject`) |
| One module | `.venv/bin/python manage.py test jokes.tests_media_wave2` / `billing.tests.test_webhook` |
| One class | `.venv/bin/python manage.py test jokes.tests_media_wave2.VideoPipelineTests` |
| One test | `.venv/bin/python manage.py test jokes.test_reset_roundtrip.PasswordResetRoundTripTest.test_email_link_actually_resets_the_password` |
| Substring filter (Django ≥4.1) | `.venv/bin/python manage.py test -k paywall` |
| Only ffmpeg-gated pipeline tests | `.venv/bin/python manage.py test jokes.tests_media_wave2.VideoPipelineTests jokes.tests_media_wave2.AudioPipelineTests jokes.tests_media_wave2.MediaUploadWave2Tests jokes.tests_media_wave2.ProbeTests` |
| Cairo-dependent tests | `.venv/bin/python manage.py test jokes.tests_share_cards` (must have `DYLD_FALLBACK_LIBRARY_PATH` on macOS) |
| Lint (blocking in CI) | `.venv/bin/ruff check .` (ruff 0.16.1 installed in `.venv`; CI pins 0.16.1) |
| Security scan (non-blocking in CI) | `.venv/bin/bandit -c pyproject.toml -r JokesForProject jokes notifications creator_insights follows audit billing inbox` |
| Dependency audit (non-blocking in CI; needs network) | `.venv/bin/pip-audit -r requirements.txt` |
| Django system check (blocking in CI) | `.venv/bin/python manage.py check` |
| Not in CI but documented manual gates | `.venv/bin/python manage.py makemigrations --check --dry-run`; `DEBUG=False SECRET_KEY=x ALLOWED_HOSTS=example.com .venv/bin/python manage.py check --deploy` (`Docs/superpowers/plans/2026-06-15-prod-integrity-fixes.md:148,532`) |

Same one-liner form used in project docs (`Docs/2026-06-19-iteration-review.md:90`, `Docs/superpowers/2026-06-19-monetization-design.md:315`):
`DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test --keepdb`

Notes:
- `--parallel` is not used anywhere (CI or docs) and is untested; with `DatabaseCache`, pgtrigger and `MEDIA_ROOT` tempdirs it may work, but treat as unverified.
- `--keepdb` after a crashed run can leave `test_jokesfor` inconsistent; `--noinput` drops and recreates.
- Verification results of `ruff check .` and `bandit` run today are in §9.

---

## 8. CI — `.github/workflows/ci.yml`

- Triggers: `pull_request` (any branch) and `push` to `main` only.
- Single job `test` on `ubuntu-latest`; service container `postgres:15` (`POSTGRES_USER/PASSWORD=postgres`, `POSTGRES_DB=jokesfor`, health-checked with `pg_isready`); job env `DATABASE_URL: ''`, `DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=postgres DB_HOST=localhost DB_PORT=5432`, `DEBUG: 'True'` (no `SECRET_KEY` → dev fallback because `DEBUG=True`).
- Steps in order: `actions/checkout@v4` → `actions/setup-python@v5` (3.11, pip cache) → `apt-get install ffmpeg libcairo2 libpango-1.0-0 libpangocairo-1.0-0` → `pip install -r requirements.txt` + `pip install ruff==0.16.1 bandit==1.9.4 pip-audit==2.10.1` → **`ruff check .` (hard gate)** → `bandit -c pyproject.toml -r <8 packages> || true` (**non-blocking**) → `pip-audit -r requirements.txt || true` (**non-blocking**) → **`python manage.py check` (hard gate)** → **`python manage.py test --noinput` (hard gate)**.
- Not present: coverage, `--parallel`, `makemigrations --check`, `check --deploy`, frontend build, Docker build, test-result artifacts, matrix.
- Trailing comment in the file: workflow "has not been run on actual GitHub Actions infrastructure yet — the first push may need a small tweak". Git log shows the commit (`1d955a8 ci: GitHub Actions test/lint gate + dependabot`) but nothing in the repo records a green run; verify on GitHub before trusting.
- `.github/dependabot.yml`: weekly `pip` (`/`) and `github-actions` updates.
- **Deploy pipeline runs no tests**: `cloudbuild.yaml` = Build → Push → `manage.py migrate --noinput` inside the image (Secret Manager `DATABASE_URL`, `DEBUG=True`) → `gcloud run services update`. A red CI does not block the Cloud Build trigger.

---

## 9. Static quality gates

### ruff (`pyproject.toml [tool.ruff]`)
- `target-version=py311`, `line-length=100`, excludes migrations/.venv/staticfiles/manage.py.
- `select = F, E, W, I, B, UP, C4, DJ`; repo-wide `ignore = E501, E402` (E402 because several test files append "Wave N" sections with their own imports mid-file, e.g. `jokes/tests_media_wave2.py:411,650`).
- Per-file ignores: `jokes/models.py` DJ012/DJ008; `jokes/serializers.py` E741/B904; `JokesForProject/adapters.py`, `jokes/media_probe.py`, `jokes/media_processing.py` B904; `seed_demo_creator.py` C408/B905/B007/E731; **all test files** (`**/tests.py`, `**/tests_*.py`, `**/test_*.py`) F841/B017; `jokes/tests_storage.py` UP031; `billing/webhooks.py` F841.
- isort `known-first-party` lists the 8 packages. `[tool.ruff.format]` (single quotes) is configured but **`ruff format` has never been applied repo-wide** (comment in file).
- **Run today: `ruff check .` → "All checks passed!" (exit 0).**

### bandit (`pyproject.toml [tool.bandit]`)
- `exclude_dirs = */migrations/*, */tests*, */test_*.py, .venv`.
- **Run today** (bandit 1.9.4, 12,202 LOC): 49 findings — 2 Medium/High-confidence (`B703` + `B308` `mark_safe` at `jokes/views.py:1348`), 47 Low (26× `B311` `random` for non-crypto use, 9× `B110` try/except/pass, 2× `B603`/`B404` subprocess (ffmpeg), 1× `B607` partial path (`ffmpeg` on PATH), 1× `B405` `xml.etree.Element`, 1× `B112`, 5× hardcoded-password false positives incl. `'django-insecure-dev-only-key'` and the seed `'DemoCreator!2026'`). Non-blocking in CI by design.

### pip-audit
- Non-blocking in CI; needs network so not run here. Last known result in git: `d380cf2 chore: security patch-bump vulnerable dependencies (pip-audit)`.

### Django system checks
- `manage.py check` in CI (blocking). `check --deploy` only appears in docs as a manual step. Security-settings behaviour is unit-tested in `JokesForProject/tests/test_security_settings.py` (5 tests) instead.

---

## 10. Skips, expected failures, flakiness

- **Conditional skips**: 28 tests via `@unittest.skipUnless(FFMPEG, ...)` in `jokes/tests_media_wave2.py` (lines 75,105,133,279,317,374,428,582); 1 class-level `cls.skipTest("Need at least 2 Tone objects in fixture")` at `creator_insights/tests/test_services.py:669` (raised from `setUpTestData`, so it skips the whole class if the Tone seed migration didn't run).
- **No** `@expectedFailure`, `xfail`, or `@skip` decorators. A former `expectedFailure` (history-window row-count bug) was converted into an enforced test: `jokes/test_time_progression.py:291-298`.
- **No flaky markers / retries.** Names like `flaky_quarantine` (`tests_appeals.py:444`), `flaky_delete` (`tests_share_cards.py:362`), `flaky_transport_send` (`test_digests.py:363`) are deliberate fault-injection stubs, not flaky tests.
- **Determinism risks worth watching**: (1) tests without freezegun that assert on "today" (paywall/streak files all freeze; others rely on `timezone.now()`); (2) ffmpeg-gated tests do real encoding with 60 s fixture timeouts and a 240 s pipeline timeout — slow CI runners could hit `subprocess.TimeoutExpired`; (3) `_MEDIA_ROOT = tempfile.mkdtemp()` at module import in `tests_media.py` is shared by every class in the file; (4) DRF throttles use the DB cache — isolated by transaction rollback, but `notifications/tests/test_throttling.py` also calls `cache.clear()` defensively.

---

## 11. Runtime

No document records the wall-clock time of the full suite (grep for "Ran N tests in" across `Docs/` and `.planning/` finds nothing; git commit bodies don't either). Historical facts: 362 tests ran with `--keepdb` in June; today's 834 include 28 real-ffmpeg encoding tests and 25 real-cairo renders, which dominate. Expect single-digit minutes on a laptop with `--keepdb`; first run adds test-DB creation + ~36 jokes migrations incl. the 158-joke demo seed. This is an estimate, not a measurement — the test pipeline should record it.

---

## 12. Docs vs code disagreements

| Claim | Where | Reality |
|---|---|---|
| "No tests currently exist", recommends pytest-django/factory_boy/coverage | `.planning/codebase/TESTING.md` (2026-01-11) | 834 tests, none of those tools adopted |
| "libcairo (not present in CI/local)" | `jokes/tests_launch_blockers.py:61`, `jokes/tests_storage.py:117` | CI installs libcairo2/pango; locally present via Homebrew but needs `DYLD_FALLBACK_LIBRARY_PATH` |
| CI workflow "has not been run on actual GitHub Actions infrastructure yet" | `.github/workflows/ci.yml` trailing NOTE | Still the only statement in-repo; unverified either way |
| Memory note "Local DB test fallback ... when Neon unreachable" | project notes | Correct, but the fallback must be forced with `DATABASE_URL=''` because `.env` hard-codes the Neon URL |

---

## Appendix A — helper/factory functions per file
`billing/tests/test_tips.py`: `make_user`, `make_joke`, `make_creator` · `billing/tests/test_webhook.py`: `_make_stripe_event` · `creator_insights/tests/{test_compliance,test_permissions,test_profile,test_services,test_views}.py`: `_make_joke`, `_make_published_submission` · `jokes/test_paywall.py`: `_make_joke`, `_setup_joke` · `jokes/test_streak_time_progression.py`, `jokes/test_time_progression.py`, `jokes/tests_creator_fk.py`, `jokes/tests_compliance.py`, `jokes/tests_moderation.py`: `_make_joke` · `jokes/tests_appeals.py`: `_make_joke`, `_make_submission` · `jokes/tests_feed_n1.py`: `_make_asset` · `jokes/tests_media.py`: `make_user`, `make_asset`, `make_image_bytes`, `make_image_joke`, `_taxonomy`, `locked_state` · `jokes/tests_media_wave2.py`: `make_clip`, `make_audio`, `make_gif`, `make_audio_with_cover`, `_make_watch_joke` · `jokes/tests_share_cards.py`: `make_image_asset`, `make_video_asset`, `make_audio_asset`, `make_joke` · `jokes/tests_sitemap.py`, `notifications/tests/test_digests.py`: `_make_user`, `_make_joke` · `jokes/tests_telemetry.py`: `_make_joke`, `_make_published_submission` · `jokes/tests_storage.py`: `_get_or_create_fixtures`.

## Appendix B — per-file usage matrix (ft=freeze_time, patch=mock/patch, ovr=override_settings, sutd=setUpTestData, ffm=ffmpeg/subprocess, stripe/vision/gcs = mentions)
```
JokesForProject/tests/test_healthz.py            ft=0  patch=3  ovr=0  sutd=0
JokesForProject/tests/test_observability.py      ft=0  patch=0  ovr=0  sutd=0
JokesForProject/tests/test_security_settings.py  ft=0  patch=4  ovr=0  sutd=0
audit/tests.py                                   ft=0  patch=1  ovr=0  sutd=0
billing/tests/test_checkout_portal.py            ft=0  patch=7  ovr=13 sutd=0  stripe=63
billing/tests/test_entitlements.py               ft=0  patch=0  ovr=0  sutd=0
billing/tests/test_gating.py                     ft=0  patch=4  ovr=2  sutd=0  stripe=6
billing/tests/test_quota_lazy_reset.py           ft=0  patch=3  ovr=0  sutd=0
billing/tests/test_quota_time_progression.py     ft=5  patch=0  ovr=0  sutd=0
billing/tests/test_tips.py                       ft=0  patch=4  ovr=11 sutd=0  stripe=32
billing/tests/test_webhook.py                    ft=0  patch=10 ovr=3  sutd=0  stripe=47
creator_insights/tests/test_compliance.py        ft=0  patch=2  ovr=0  sutd=3
creator_insights/tests/test_permissions.py       ft=0  patch=2  ovr=0  sutd=1
creator_insights/tests/test_profile.py           ft=0  patch=2  ovr=0  sutd=3
creator_insights/tests/test_services.py          ft=0  patch=2  ovr=2  sutd=10
creator_insights/tests/test_views.py             ft=0  patch=2  ovr=0  sutd=1
follows/tests.py                                 ft=0  patch=0  ovr=0  sutd=5
inbox/tests.py                                   ft=0  patch=0  ovr=0  sutd=4
jokes/test_paywall.py                            ft=5  patch=2  ovr=0  sutd=3
jokes/test_reset_roundtrip.py                    ft=0  patch=0  ovr=2  sutd=0
jokes/test_streak_time_progression.py            ft=11 patch=2  ovr=0  sutd=1
jokes/test_time_progression.py                   ft=15 patch=2  ovr=0  sutd=6
jokes/tests.py                                   ft=0  patch=7  ovr=0  sutd=5
jokes/tests_appeals.py                           ft=12 patch=5  ovr=14 sutd=0  gcs=1
jokes/tests_backfill_share_cards.py              ft=0  patch=2  ovr=2  sutd=0
jokes/tests_compliance.py                        ft=0  patch=6  ovr=2  sutd=6
jokes/tests_creator_fk.py                        ft=0  patch=3  ovr=0  sutd=3
jokes/tests_csrf.py                              ft=0  patch=3  ovr=0  sutd=0  stripe=3
jokes/tests_feed_n1.py                           ft=0  patch=1  ovr=0  sutd=1
jokes/tests_google_age_gate.py                   ft=0  patch=4  ovr=2  sutd=1
jokes/tests_identity.py                          ft=0  patch=4  ovr=0  sutd=1
jokes/tests_launch_blockers.py                   ft=0  patch=2  ovr=2  sutd=1  cairo=1
jokes/tests_media.py                             ft=6  patch=25 ovr=12 sutd=0  cairo=2 vision=5
jokes/tests_media_wave2.py                       ft=0  patch=16 ovr=6  sutd=1  ffm=35 vision=4
jokes/tests_moderation.py                        ft=0  patch=2  ovr=0  sutd=1
jokes/tests_share_cards.py                       ft=0  patch=6  ovr=10 sutd=0  cairo=5 vision=3 gcs=3
jokes/tests_share_page.py                        ft=0  patch=0  ovr=2  sutd=1
jokes/tests_sitemap.py                           ft=0  patch=2  ovr=2  sutd=1
jokes/tests_storage.py                           ft=0  patch=3  ovr=3  sutd=0  cairo=2 gcs=2
jokes/tests_telemetry.py                         ft=0  patch=2  ovr=0  sutd=2
notifications/tests/test_digest_trigger.py       ft=2  patch=9  ovr=11 sutd=0
notifications/tests/test_digests.py              ft=27 patch=4  ovr=12 sutd=0
notifications/tests/test_engine.py               ft=0  patch=0  ovr=3  sutd=0
notifications/tests/test_google_exemption.py     ft=0  patch=0  ovr=2  sutd=0
notifications/tests/test_models.py               ft=0  patch=0  ovr=0  sutd=1
notifications/tests/test_registration_flow.py    ft=0  patch=0  ovr=4  sutd=0
notifications/tests/test_templates.py            ft=0  patch=0  ovr=0  sutd=0
notifications/tests/test_throttle_cache.py       ft=0  patch=0  ovr=2  sutd=0
notifications/tests/test_throttling.py           ft=0  patch=0  ovr=3  sutd=0
notifications/tests/test_unsubscribe.py          ft=3  patch=0  ovr=0  sutd=0
notifications/tests/test_verification.py         ft=0  patch=0  ovr=2  sutd=0
notifications/tests/test_verify_resend.py        ft=0  patch=0  ovr=3  sutd=0
```
