# Observability & Logging — Implementation Plan (2026-06-17)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Deliver "very detailed observability" for the single gunicorn/Cloud Run app entirely request-driven (NO Celery/workers/cron) by adding: (1) a self-contained JokesForProject/observability/ package with request-scoped contextvars, a Cloud Logging JSON formatter, PII/secret redaction, and two middlewares (request-id/trace correlation + structured access log); (2) a LOGGING dict and middleware/env wiring in settings.py; (3) Sentry enrichment (release + trace tags + PII-scrub before_send); (4) an append-only audit log (dual-sink: DB row + structured stdout) hooked at compliance choke-points; (5) domain-metric log lines at existing choke-points; (6) a richer readyz/version signal. Everything emits one-line JSON to stdout that Cloud Run auto-ingests, with logs clickable through to Cloud Trace via the magic 'logging.googleapis.com/trace' key. All Cloud Monitoring alerts, log-based metrics, dashboards, uptime checks, sinks/retention are DEFERRED to the GCP console. Built TDD with Django's runner (no pytest) on local Postgres, DB-free SimpleTestCase where possible.

**Architecture:** SYNTHESIS OF THE 4 PILLARS into one coherent design. The four pillar designs strongly converge; the only conflict (whether to use OpenTelemetry) is resolved in favor of the lightweight manual approach.

PILLAR RECONCILIATION:
- Pillar 1 (structured logging) and Pillar 2 (tracing/metrics) both propose a JokesForProject/observability/ package with contextvars + a GoogleCloudJsonFormatter + a trace/request-id middleware + a structured access log. These are MERGED into one package. Pillar 2's "skip OpenTelemetry, parse X-Cloud-Trace-Context manually" decision is ADOPTED as the binding tracing decision — OTel's BatchSpanProcessor needs a background thread Cloud Run's between-request CPU throttling breaks, and SimpleSpanProcessor adds a blocking Trace API call per request; both violate the no-worker / minimal-overhead constraints. So tracing = parse the header Cloud Run already sets, propagate trace_id into logs + Sentry; Cloud Run/Cloud Logging builds the trace timeline for free. ZERO new runtime deps.
- Pillar 2's per-request DB stats (db_query_count / db_time_ms via connection.execute_wrapper, which works with DEBUG=False) and domain-metric log lines at choke-points are folded into the access middleware + a 'jokesfor.metrics' logger.
- Pillar 3 (Sentry + audit) contributes the AuditLog model + record_audit() dual-sink helper, the auth-signal hooks, the Sentry before_send PII scrub + release + ignore_errors, and the anti-enumeration constraint on resend/password-reset audit lines.
- Pillar 4 (readiness/alerts) is ALREADY DONE in code (healthz/readyz split exists, 7 tests green); its remaining items are alerts/uptime checks => all DEFERRED. We only add a tiny version/build field + structured deploy log to readyz, and the throttle-hit + content_report structured logs it depends on (which the logging pillar provides anyway).

FINAL CODE ARCHITECTURE — single request flow:
  request -> SecurityMiddleware -> WhiteNoise -> RequestContextMiddleware (generate/propagate X-Request-ID; parse X-Cloud-Trace-Context 'TRACE/SPAN;o=1'; bind request_id/trace/span/sampled into contextvars; install a DB execute_wrapper counter; tag Sentry) -> AccessLogMiddleware (start monotonic timer) -> ...rest of stack... -> view -> (back up) AccessLogMiddleware emits ONE 'jokesfor.access' JSON line (method, route, status, latency_ms, db_query_count, db_time_ms, masked client_ip, request_id, user_id, severity-by-status; /healthz+/readyz dropped to DEBUG) -> RequestContextMiddleware binds user_id lazily post-view, echoes X-Request-ID header, resets contextvars in finally (CRITICAL for gthread thread reuse). The GoogleCloudJsonFormatter merges get_log_fields() from contextvars into EVERY log line, so even logs emitted deep in a view carry request_id + the 'logging.googleapis.com/trace' = 'projects/<PROJECT>/traces/<id>' key that makes Cloud Logging entries click through to Cloud Trace.

AUDIT SUBSYSTEM (dual-sink, no worker): new audit/ Django app with an append-only AuditLog model (actor FK SET_NULL, actor_email_hash sha256, action, target_type/id, outcome, request_id, masked ip, ua, metadata JSON — NO plaintext PII) plus a pgtrigger Protect trigger (django-pgtrigger already installed) blocking UPDATE/DELETE. record_audit(request, action, ...) writes the row inside try/except (a Neon hiccup never breaks the request) AND emits a 'jokesfor.audit' JSON line as the always-on fallback. Hooked at: auth signals (user_logged_in / user_login_failed[request may be None] / user_logged_out), CookieRegisterView.create (registration outcome), verify_code result, resend-verification (anti-enumeration: never record whether the email matched), account delete (capture actor id+email-hash BEFORE user.delete() at line 1713, record AFTER with actor=None), content report create, user block/unblock, data export. Read-only Django admin for AuditLog + EmailMessageLog/EmailVerification already exist per memory.

OBSERVABILITY VS COMPLIANCE: keeps the existing send_default_pii=False posture — access/metric logs carry integer user_id (not PII) and masked IP; audit stores email HASH not plaintext; the redaction denylist covers the JWT cookies (jokes-access-token/jokes-refresh-token), Authorization, password*, and the 6-digit verification 'code'. Query strings are never logged (request.path / resolver_match.route only).

DEPLOYMENT: Dockerfile drops gunicorn's '--access-logfile -' (keeps '--error-logfile -') so the Django AccessLogMiddleware is the single source of structured access lines (no duplicate unparsed plain-text line). ZERO new dependencies across the whole PR.

---

**Files:**

| Action | Path | Responsibility |
|---|---|---|
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/observability/__init__.py` | Package marker; optionally re-export get_log_fields/bind_request_context/record-free public helpers. Keep import-light (no Django app loading) so settings.py and the formatter can import it at config time. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/observability/context.py` | Module-level contextvars request_id_var/trace_var/span_var/user_id_var/sampled_var (default None). bind_request_context(...) returns reset tokens; clear_request_context(tokens) resets via ContextVar.reset (called in finally so values never leak across reused gthread threads). get_log_fields() returns dict of currently-bound non-None values for the formatter. Also holds the per-request DB counter (db_query_count/db_time_ms) contextvars + helpers reset_db_stats()/add_db_query(duration)/get_db_stats(). |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/observability/redaction.py` | mask_email() -> 'a***@example.com'; hash_email() -> sha256 hex[:12] (reuses notifications/verification.py SHA-256 convention); mask_ip() -> zero last IPv4 octet / truncate IPv6 to /48; redact_mapping() -> recursively replace denylisted keys {password,password1,password2,token,access,refresh,authorization,secret,api_key,resend_api_key,code,code_hash,set-cookie,cookie,jokes-access-token,jokes-refresh-token} with '[REDACTED]'. Used by access middleware + Sentry before_send. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/observability/formatters.py` | GoogleCloudJsonFormatter(logging.Formatter): one-line json.dumps with magic keys severity (level->Cloud severity), message, timestamp (ISO8601 UTC), logging.googleapis.com/trace = 'projects/<PROJECT>/traces/<32hex>' when a VALID trace bound, logging.googleapis.com/spanId, logging.googleapis.com/sourceLocation, plus merged get_log_fields() (request_id,user_id) at top level (Cloud Run lifts unknown top-level keys into jsonPayload) AND record.extra fields. Includes exception traceback via formatException when exc_info set (so Error Reporting groups). Reads PROJECT_ID from settings.GOOGLE_CLOUD_PROJECT. Also a PlainFormatter alias for local dev readability. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/observability/middleware.py` | RequestContextMiddleware (request-id gen/propagate, X-Cloud-Trace-Context parse with 32-hex validation to prevent log injection, bind contextvars in try/finally, install DB execute_wrapper, echo X-Request-ID, lazy user_id bind post-view, Sentry set_tag guarded by import). AccessLogMiddleware (monotonic latency timer, one 'jokesfor.access' record with method/route/status/latency_ms/db stats/masked client_ip from XFF first hop/user_id; severity by status >=500 ERROR / >=400 WARNING / else INFO; /healthz+/readyz dropped to DEBUG). Module comment documents the no-OTel decision to prevent regression. |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py` | Add GOOGLE_CLOUD_PROJECT/LOG_LEVEL/LOG_FORMAT/LOG_SQL env settings near Sentry block; add declarative LOGGING dict (disable_existing_loggers=False; gcp_json vs plain by LOG_FORMAT; loggers django/django.request/django.server/django.db.backends/jokesfor/jokesfor.access/jokesfor.metrics/jokesfor.audit/jokesfor.health); insert RequestContextMiddleware + AccessLogMiddleware right after WhiteNoise; enrich Sentry init (release=K_REVISION, before_send=redact, ignore_errors). Keep LOGGING declarative (no dictConfig() side-effect) so test_security_settings.py importlib.reload stays safe. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/__init__.py` | New Django app package marker. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/apps.py` | AuditConfig; ready() connects auth signal receivers (user_logged_in/user_login_failed/user_logged_out) with function-local imports so migrations/spectacular don't break on a fresh DB. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/models.py` | AuditLog: actor FK(SET_NULL,null), actor_email_hash(64char), action(indexed), target_type, target_id, ip, request_id(indexed), user_agent(256), outcome(success/failure/denied indexed), metadata(JSON non-PII), created_at(auto, indexed). Meta with pgtrigger.Protect on UPDATE/DELETE for append-only. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/services.py` | record_audit(request, action, *, outcome='success', actor=..., target_type='', target_id='', metadata=None) — derives request_id/ip/ua from contextvars+request, hashes actor email, writes AuditLog row in try/except, ALWAYS emits a 'jokesfor.audit' structured log line as fallback. Imports kept function-local / import-safe. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/signals.py` | Receivers for user_logged_in/user_logged_out/user_login_failed (handle request=None). login_failed must NOT leak whether the email existed (anti-enumeration) — record action=login outcome=failure with hashed attempted email only. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/admin.py` | Read-only ModelAdmin for AuditLog (list_display, filters on action/outcome/created_at; has_add/change/delete = False). |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/migrations/0001_initial.py` | Generated by makemigrations — AuditLog table + pgtrigger Protect trigger. |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/serving.py` | Emit 'jokesfor.metrics' event=content_tier_decision (tiers_granted + reason anon/no_profile/minor/adult_no_mature/adult_mature) and event=age_gate_block when an authenticated adult is denied tier_2. 1-3 line log calls; trace id rides along via the formatter. |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/views.py` | CookieRegisterView.create: record_audit + 'jokesfor.metrics' event=registration (mode gated/legacy, outcome created/email_send_failed). ContentReportView.perform_create: record_audit event=content_report (reason, joke_id, reporter_id). UserBlockView post/delete: record_audit. UserAccountDeleteView.delete: capture actor id+email-hash BEFORE user.delete(), record_audit actor=None AFTER. DataExportView.get: record_audit data_export. |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/notifications/verification.py` | verify_code(): emit 'jokesfor.metrics' event=verification_attempt result=ok/no_active_code/expired/too_many_attempts/incorrect (result strings are non-PII). |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/health.py` | Add build/version (K_REVISION or GIT_SHA) to readyz payload and emit a structured 'jokesfor.health' info line carrying version so deploys are visible in the log stream. Keep healthz dependency-free. |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/Dockerfile` | Drop '--access-logfile -' from the gunicorn CMD (keep '--error-logfile -') so AccessLogMiddleware is the single structured access-line source and Cloud Logging shows one parsed entry per request. |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/.env.example` | Append LOG_LEVEL=INFO, LOG_FORMAT (json\|plain auto from DEBUG), LOG_SQL=false, GOOGLE_CLOUD_PROJECT= (Cloud Run injects). Document that none are required on Cloud Run. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_observability.py` | SimpleTestCase: formatter JSON shape + trace key format + exception inclusion; RequestContextMiddleware id gen/propagate/header-echo + X-Cloud-Trace-Context parse + 32-hex validation + contextvar non-leak across two requests; redaction never emits password/token/code/cookie; AccessLogMiddleware exactly one record + severity-by-status + /healthz at DEBUG. Use assertLogs('jokesfor.access'). |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/tests.py` | TestCase: record_audit writes a row + emits 'jokesfor.audit' line; DB failure still emits the log fallback; append-only trigger blocks UPDATE/DELETE; login_failed receiver records outcome=failure without leaking email existence; account-delete captures actor email-hash before delete. |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py` | Register 'audit' in INSTALLED_APPS (separate edit from the LOGGING/MIDDLEWARE edit, listed here as the app-registration responsibility). |

### Task 1: Task 1 — observability package skeleton + contextvars (foundation, DB-free)

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/observability/__init__.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/observability/context.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_observability.py`

- [ ] **Step 1 (test): Create test_observability.py with a ContextTests(SimpleTestCase). Assert get_log_fields() is {} when nothing bound; after bind_request_context(request_id='r1', trace='abc', user_id=7) it returns those keys; after clear_request_context(tokens) it is {} again (proves reset). Add a DB-stats test: reset_db_stats(); add_db_query(1.5); add_db_query(2.5); get_db_stats() == {'db_query_count':2,'db_time_ms': ~4.0}.**

```
# JokesForProject/tests/test_observability.py
from django.test import SimpleTestCase
from JokesForProject.observability import context as ctx

class ContextTests(SimpleTestCase):
    def test_bind_and_clear_no_leak(self):
        self.assertEqual(ctx.get_log_fields(), {})
        tokens = ctx.bind_request_context(request_id='r1', trace='abc', user_id=7)
        f = ctx.get_log_fields()
        self.assertEqual(f['request_id'], 'r1'); self.assertEqual(f['user_id'], 7)
        ctx.clear_request_context(tokens)
        self.assertEqual(ctx.get_log_fields(), {})
    def test_db_stats_accumulate_and_reset(self):
        ctx.reset_db_stats(); ctx.add_db_query(1.5); ctx.add_db_query(2.5)
        s = ctx.get_db_stats()
        self.assertEqual(s['db_query_count'], 2); self.assertAlmostEqual(s['db_time_ms'], 4.0, places=1)
```

  - Expected: FAILS — JokesForProject.observability does not exist yet (ImportError).

- [ ] **Step 2 (code): Create the package: empty __init__.py; context.py with contextvars request_id_var/trace_var/span_var/user_id_var/sampled_var/db_count_var/db_time_var (all default None or 0), bind_request_context returning a dict of tokens, clear_request_context resetting each via ContextVar.reset, get_log_fields() returning bound non-None values (request_id/trace/span/user_id/sampled), and reset_db_stats/add_db_query(duration_ms)/get_db_stats helpers.**

```
# JokesForProject/observability/context.py (essentials)
import contextvars
request_id_var = contextvars.ContextVar('request_id', default=None)
trace_var = contextvars.ContextVar('trace', default=None)
span_var = contextvars.ContextVar('span', default=None)
user_id_var = contextvars.ContextVar('user_id', default=None)
sampled_var = contextvars.ContextVar('sampled', default=None)
db_count_var = contextvars.ContextVar('db_count', default=0)
db_time_var = contextvars.ContextVar('db_time', default=0.0)
_VARS = {'request_id': request_id_var, 'trace': trace_var, 'span': span_var, 'user_id': user_id_var, 'sampled': sampled_var}
def bind_request_context(**kw):
    return {k: _VARS[k].set(v) for k, v in kw.items() if k in _VARS}
def clear_request_context(tokens):
    for k, tok in (tokens or {}).items():
        try: _VARS[k].reset(tok)
        except (LookupError, ValueError): pass
def get_log_fields():
    return {k: v.get() for k, v in _VARS.items() if v.get() is not None}
def reset_db_stats():
    db_count_var.set(0); db_time_var.set(0.0)
def add_db_query(ms):
    db_count_var.set(db_count_var.get() + 1); db_time_var.set(db_time_var.get() + ms)
def get_db_stats():
    return {'db_query_count': db_count_var.get(), 'db_time_ms': round(db_time_var.get(), 2)}
```

  - Expected: Test added in this step passes (the others come later).

- [ ] **Step 3 (command): Run the context tests only.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test JokesForProject.tests.test_observability.ContextTests --keepdb
```

  - Expected: 2 tests pass.

- [ ] **Step 4 (command): Commit the foundation.**

```
git checkout -b feat/observability && git add JokesForProject/observability JokesForProject/tests/test_observability.py && git commit -m 'Add observability package with request-scoped contextvars'
```

  - Expected: Commit created on a new branch (not main).

### Task 2: Task 2 — redaction helpers (PII/secret masking, DB-free)

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/observability/redaction.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_observability.py`

- [ ] **Step 1 (test): Add RedactionTests(SimpleTestCase): mask_email('alice@example.com')=='a***@example.com'; hash_email returns 12 lowercase hex chars and is stable; mask_ip('203.0.113.45')=='203.0.113.0'; mask_ip for IPv6 truncates to /48; redact_mapping over a dict containing password/token/code/authorization/cookie/jokes-access-token replaces each with '[REDACTED]' (recursively into nested dicts/lists) and leaves benign keys intact.**

```
from JokesForProject.observability import redaction as red
class RedactionTests(SimpleTestCase):
    def test_mask_email(self): self.assertEqual(red.mask_email('alice@example.com'),'a***@example.com')
    def test_hash_email_stable_12hex(self):
        h=red.hash_email('alice@example.com'); self.assertEqual(len(h),12); self.assertEqual(h, red.hash_email('alice@example.com'))
    def test_mask_ip_v4(self): self.assertEqual(red.mask_ip('203.0.113.45'),'203.0.113.0')
    def test_redact_denylist(self):
        out=red.redact_mapping({'password':'x','code':'123456','authorization':'Bearer y','nested':{'token':'t','ok':'keep'},'jokes-access-token':'jwt'})
        self.assertEqual(out['password'],'[REDACTED]'); self.assertEqual(out['code'],'[REDACTED]')
        self.assertEqual(out['nested']['token'],'[REDACTED]'); self.assertEqual(out['nested']['ok'],'keep')
        self.assertEqual(out['jokes-access-token'],'[REDACTED]')
```

  - Expected: FAILS — redaction module missing.

- [ ] **Step 2 (code): Implement redaction.py: mask_email (first char + *** + @domain), hash_email (hashlib.sha256(...).hexdigest()[:12]), mask_ip (split on '.' zero last octet for v4; for v6 keep first 3 hextets + '::'), redact_mapping (case-insensitive denylist set, recurse dict/list, return new structure).**

  - Expected: Use the exact denylist from the design (includes cookie names + 'code').

- [ ] **Step 3 (command): Run redaction tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test JokesForProject.tests.test_observability.RedactionTests --keepdb
```

  - Expected: All redaction tests pass.

- [ ] **Step 4 (command): Commit.**

```
git add JokesForProject/observability/redaction.py JokesForProject/tests/test_observability.py && git commit -m 'Add PII/secret redaction helpers for logs and Sentry'
```

  - Expected: Commit created.

### Task 3: Task 3 — GoogleCloudJsonFormatter (DB-free)

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/observability/formatters.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_observability.py`

- [ ] **Step 1 (test): Add FormatterTests(SimpleTestCase): build a LogRecord at INFO with message 'hello', format it, json.loads the line and assert severity=='INFO', message=='hello', a 'timestamp' present, and sourceLocation present. With a 32-hex trace bound via contextvars, assert the line contains key 'logging.googleapis.com/trace' == 'projects/<PROJECT>/traces/<id>'. With exc_info from a raised ValueError, assert an 'exception' field with traceback text. Clear contextvars in tearDown.**

```
import json, logging
from JokesForProject.observability.formatters import GoogleCloudJsonFormatter
from JokesForProject.observability import context as ctx
class FormatterTests(SimpleTestCase):
    def tearDown(self): ctx.clear_request_context(ctx.bind_request_context())  # no-op safety
    def _rec(self, **kw):
        return logging.LogRecord('n', logging.INFO, __file__, 10, 'hello', None, kw.get('exc_info'))
    def test_basic_shape(self):
        line = GoogleCloudJsonFormatter().format(self._rec())
        d = json.loads(line); self.assertEqual(d['severity'],'INFO'); self.assertEqual(d['message'],'hello'); self.assertIn('timestamp', d)
    def test_trace_key(self):
        tok = ctx.bind_request_context(trace='a'*32, request_id='r1')
        try:
            d = json.loads(GoogleCloudJsonFormatter().format(self._rec()))
            self.assertTrue(d['logging.googleapis.com/trace'].endswith('/traces/'+'a'*32))
            self.assertEqual(d['request_id'],'r1')
        finally: ctx.clear_request_context(tok)
```

  - Expected: FAILS — formatters module missing.

- [ ] **Step 2 (code): Implement GoogleCloudJsonFormatter: map levelno->severity; build dict with severity/message/timestamp(ISO8601 UTC from record.created)/sourceLocation{file,line,function}; merge get_log_fields() at top level; if a bound trace matches ^[0-9a-fA-F]{32}$ add 'logging.googleapis.com/trace' using settings.GOOGLE_CLOUD_PROJECT (lazy import django.conf.settings inside format to avoid import-time settings access) and span if present; merge record extras (skip standard LogRecord attrs); if record.exc_info add 'exception': self.formatException(record.exc_info); json.dumps(default=str) on one line. Also export a PlainFormatter for dev.**

  - Expected: Trace id is validated 32-hex before building the resource name (prevents log injection).

- [ ] **Step 3 (command): Run formatter tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test JokesForProject.tests.test_observability.FormatterTests --keepdb
```

  - Expected: Formatter tests pass.

- [ ] **Step 4 (command): Commit.**

```
git add JokesForProject/observability/formatters.py JokesForProject/tests/test_observability.py && git commit -m 'Add Cloud Logging JSON formatter with trace correlation'
```

  - Expected: Commit created.

### Task 4: Task 4 — RequestContextMiddleware + AccessLogMiddleware

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/observability/middleware.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_observability.py`

- [ ] **Step 1 (test): Add MiddlewareTests(SimpleTestCase) using a fake get_response returning HttpResponse(status configurable) and RequestFactory. Assert: (1) absent X-Request-ID -> a uuid hex is generated and echoed on response 'X-Request-ID'; (2) present 'HTTP_X_REQUEST_ID' is propagated unchanged; (3) 'HTTP_X_CLOUD_TRACE_CONTEXT'='<32hex>/123;o=1' parses trace==32hex, span=='123', sampled True (assert by capturing the formatted log or by checking request attributes set); (4) after __call__ returns, ctx.get_log_fields()=={} (no leak); (5) a non-32-hex trace header is rejected (no trace key). For AccessLogMiddleware use self.assertLogs('jokesfor.access', level='INFO'): exactly one record, with method/path/status/latency_ms; a 500 response logs at ERROR; path '/healthz' produces no INFO record (DEBUG-suppressed).**

```
from django.test import RequestFactory
from django.http import HttpResponse
from JokesForProject.observability.middleware import RequestContextMiddleware, AccessLogMiddleware
from JokesForProject.observability import context as ctx
class MiddlewareTests(SimpleTestCase):
    def setUp(self): self.rf = RequestFactory()
    def test_generates_and_echoes_request_id_and_no_leak(self):
        mw = RequestContextMiddleware(lambda r: HttpResponse('ok'))
        resp = mw(self.rf.get('/x'))
        self.assertTrue(resp['X-Request-ID']); self.assertEqual(ctx.get_log_fields(), {})
    def test_propagates_incoming_request_id(self):
        mw = RequestContextMiddleware(lambda r: HttpResponse('ok'))
        resp = mw(self.rf.get('/x', HTTP_X_REQUEST_ID='abc123')); self.assertEqual(resp['X-Request-ID'],'abc123')
    def test_access_log_one_line_and_severity(self):
        mw = AccessLogMiddleware(lambda r: HttpResponse('boom', status=500))
        with self.assertLogs('jokesfor.access', level='INFO') as cm:
            mw(self.rf.get('/api/v1/jokes/'))
        self.assertEqual(len(cm.records),1); self.assertEqual(cm.records[0].levelname,'ERROR')
    def test_healthz_suppressed_at_info(self):
        mw = AccessLogMiddleware(lambda r: HttpResponse('ok'))
        with self.assertNoLogs('jokesfor.access', level='INFO'):
            mw(self.rf.get('/healthz'))
```

  - Expected: FAILS — middleware module missing.

- [ ] **Step 2 (code): Implement RequestContextMiddleware: read HTTP_X_REQUEST_ID or uuid4().hex; parse HTTP_X_CLOUD_TRACE_CONTEXT (split '/' then ';o='), validate trace 32-hex; bind contextvars in a dict; set request.request_id; install connection.execute_wrapper(counter) via execute_wrapper context manager wrapping get_response; after get_response read request.user.pk if authenticated and rebind user_id; set response['X-Request-ID']; in finally clear_request_context + reset_db_stats. Guard Sentry: try import sentry_sdk; if get_client().is_active set_tag('request_id'/'trace'). Implement AccessLogMiddleware: start=time.monotonic(); resp=get_response(request); latency_ms=round((monotonic-start)*1000,2); route=getattr(request.resolver_match,'route',request.path); client_ip=mask_ip(first XFF hop); pick level by status; if path in ('/healthz','/readyz') level=DEBUG; logger.log(level,'request', extra={...}). Add the no-OTel decision comment at top.**

  - Expected: execute_wrapper increments add_db_query with perf_counter delta; works with DEBUG=False.

- [ ] **Step 3 (command): Run the full observability suite.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test JokesForProject.tests.test_observability --keepdb
```

  - Expected: All observability tests pass (context, redaction, formatter, middleware).

- [ ] **Step 4 (command): Commit.**

```
git add JokesForProject/observability/middleware.py JokesForProject/tests/test_observability.py && git commit -m 'Add request-context and structured access-log middleware'
```

  - Expected: Commit created.

### Task 5: Task 5 — wire LOGGING dict + middleware + env settings in settings.py

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_observability.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/.env.example`

- [ ] **Step 1 (test): Add SettingsWiringTests(SimpleTestCase): from django.conf import settings — assert 'JokesForProject.observability.middleware.RequestContextMiddleware' precedes 'AccessLogMiddleware' and both appear right after WhiteNoise and BEFORE AuthenticationMiddleware-dependent reads (but RequestContextMiddleware before the bulk); assert settings.LOGGING has formatter 'gcp_json' and loggers 'jokesfor.access'/'jokesfor.audit'; assert settings.GOOGLE_CLOUD_PROJECT defaults to '332865216810'. Also assert the existing test_security_settings importlib.reload still works by running it (regression guard).**

```
class SettingsWiringTests(SimpleTestCase):
    def test_middleware_order(self):
        from django.conf import settings as s
        mw = s.MIDDLEWARE
        rc='JokesForProject.observability.middleware.RequestContextMiddleware'
        al='JokesForProject.observability.middleware.AccessLogMiddleware'
        self.assertLess(mw.index(rc), mw.index(al))
        self.assertLess(mw.index('whitenoise.middleware.WhiteNoiseMiddleware'), mw.index(rc))
    def test_logging_and_project(self):
        from django.conf import settings as s
        self.assertIn('gcp_json', s.LOGGING['formatters'])
        self.assertIn('jokesfor.access', s.LOGGING['loggers'])
        self.assertEqual(s.GOOGLE_CLOUD_PROJECT, '332865216810')
```

  - Expected: FAILS — settings not yet wired.

- [ ] **Step 2 (code): Edit settings.py: add GOOGLE_CLOUD_PROJECT/LOG_LEVEL/LOG_FORMAT/LOG_SQL near the Sentry block; insert RequestContextMiddleware + AccessLogMiddleware in MIDDLEWARE right after the WhiteNoise entry (line 83); add a declarative LOGGING dict (disable_existing_loggers=False) with formatters gcp_json+plain, a stdout StreamHandler choosing formatter by LOG_FORMAT, root->stdout at LOG_LEVEL, and named loggers django/django.request(ERROR,propagate False)/django.server/django.db.backends(WARNING or DEBUG if LOG_SQL)/jokesfor/jokesfor.access/jokesfor.metrics/jokesfor.audit/jokesfor.health (INFO, propagate False). Do NOT call dictConfig() in the module — leave it declarative so importlib.reload in test_security_settings stays side-effect-free.**

  - Expected: Keep edits minimal and declarative.

- [ ] **Step 3 (code): Append the new knobs to .env.example near the Sentry block.**

  - Expected: LOG_LEVEL/LOG_FORMAT/LOG_SQL/GOOGLE_CLOUD_PROJECT documented as Cloud-Run-optional.

- [ ] **Step 4 (command): Run wiring + security regression tests together.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test JokesForProject.tests.test_observability JokesForProject.tests.test_security_settings --keepdb
```

  - Expected: All pass; test_security_settings reload still green (no double-config error).

- [ ] **Step 5 (command): Sanity: manage.py check + a live request echoes X-Request-ID.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py check
```

  - Expected: System check identifies no issues.

- [ ] **Step 6 (command): Commit.**

```
git add JokesForProject/settings.py JokesForProject/tests/test_observability.py .env.example && git commit -m 'Wire structured logging, middleware ordering, and env knobs'
```

  - Expected: Commit created.

### Task 6: Task 6 — audit app: AuditLog model + record_audit dual-sink + append-only trigger

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/__init__.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/apps.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/models.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/services.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/admin.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/tests.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/migrations/0001_initial.py`

- [ ] **Step 1 (test): Create audit/tests.py with AuditServiceTests(TestCase): record_audit(request, 'login', outcome='success', actor=user) creates exactly one AuditLog row with action='login', outcome='success', actor_email_hash set (64 hex, not plaintext email), and emits a 'jokesfor.audit' log line (assertLogs). A second test: when AuditLog.objects.create raises (mock), record_audit still emits the 'jokesfor.audit' fallback line and does NOT propagate. A third: AppendOnlyTests asserts updating/deleting an existing AuditLog raises (pgtrigger Protect).**

```
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from audit.models import AuditLog
from audit.services import record_audit
class AuditServiceTests(TestCase):
    def setUp(self):
        self.rf=RequestFactory(); self.u=get_user_model().objects.create_user(username='a',email='a@b.com',password='x')
    def test_writes_row_and_logs(self):
        with self.assertLogs('jokesfor.audit', level='INFO'):
            record_audit(self.rf.get('/'),'login',outcome='success',actor=self.u)
        row=AuditLog.objects.get(action='login')
        self.assertEqual(row.outcome,'success'); self.assertEqual(len(row.actor_email_hash),64)
        self.assertNotIn('@', row.actor_email_hash)
    def test_db_failure_still_logs(self):
        from unittest import mock
        with mock.patch('audit.models.AuditLog.objects.create', side_effect=Exception('neon down')):
            with self.assertLogs('jokesfor.audit', level='INFO'):
                record_audit(self.rf.get('/'),'login',outcome='success',actor=self.u)
```

  - Expected: FAILS — audit app does not exist.

- [ ] **Step 2 (code): Create the audit app: __init__.py; apps.py (AuditConfig, default_auto_field); models.py (AuditLog with fields per design + Meta.triggers=[pgtrigger.Protect(name='append_only', operation=pgtrigger.Update|pgtrigger.Delete)] and indexes on action/outcome/request_id/created_at); services.py record_audit() (hash actor email via hashlib.sha256 full hexdigest, pull request_id from contextvars/request, mask ip, truncate ua to 256, try AuditLog.objects.create in try/except logging exceptions, ALWAYS logger.getLogger('jokesfor.audit').info('audit', extra={...})); admin.py read-only ModelAdmin. Register 'audit' in INSTALLED_APPS (after 'notifications').**

  - Expected: All imports in services.py are import-safe (function-local model import is fine; module-level is OK since app is installed).

- [ ] **Step 3 (command): Make + run migrations against local Postgres test DB, then run audit tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py makemigrations audit && DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test audit --keepdb
```

  - Expected: Migration 0001_initial created (table + trigger); audit tests pass.

- [ ] **Step 4 (command): Commit.**

```
git add audit JokesForProject/settings.py && git commit -m 'Add append-only audit log with dual-sink record_audit helper'
```

  - Expected: Commit created.

### Task 7: Task 7 — audit signal hooks (auth) + anti-enumeration

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/signals.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/apps.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/tests.py`

- [ ] **Step 1 (test): Add AuthSignalTests(TestCase): firing user_logged_in (via signal.send with request+user) creates an AuditLog action='login' outcome='success'; firing user_login_failed with request=None and credentials does NOT raise and records action='login' outcome='failure' WITHOUT storing whether the email exists (assert no actor FK set, only a hashed attempted-identifier and no 'user_exists' flag in metadata).**

```
from django.contrib.auth.signals import user_logged_in, user_login_failed
class AuthSignalTests(TestCase):
    def test_login_success_audited(self):
        u=get_user_model().objects.create_user(username='c',email='c@d.com',password='x')
        user_logged_in.send(sender=u.__class__, request=RequestFactory().post('/login'), user=u)
        self.assertTrue(AuditLog.objects.filter(action='login', outcome='success').exists())
    def test_login_failed_no_request_no_enumeration(self):
        user_login_failed.send(sender=None, credentials={'email':'ghost@x.com'}, request=None)
        row=AuditLog.objects.filter(action='login', outcome='failure').first()
        self.assertIsNotNone(row); self.assertIsNone(row.actor)
        self.assertNotIn('user_exists', row.metadata or {})
```

  - Expected: FAILS — signal receivers not connected.

- [ ] **Step 2 (code): Create audit/signals.py with receivers for user_logged_in/user_logged_out (request+user present) and user_login_failed (request may be None; credentials may carry email — store only hash, never whether matched). Connect them in AuditConfig.ready() with function-local imports.**

  - Expected: login_failed must not query the user table to decide existence (anti-enumeration).

- [ ] **Step 3 (command): Run audit tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test audit --keepdb
```

  - Expected: All audit tests pass.

- [ ] **Step 4 (command): Commit.**

```
git add audit && git commit -m 'Hook auth signals into audit log with anti-enumeration on login failures'
```

  - Expected: Commit created.

### Task 8: Task 8 — audit hooks + domain-metric logs at view/serving/verification choke-points

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/views.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/serving.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/notifications/verification.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/audit/tests.py`

- [ ] **Step 1 (test): Add ChokePointTests(TestCase): verify_code on a user with no active code emits a 'jokesfor.metrics' line event=verification_attempt result=no_active_code (assertLogs); allowed_tiers for an anonymous request emits content_tier_decision reason=anon; ContentReportView create (via APIClient authenticated) writes an AuditLog action='content_report' with metadata reason+joke_id; UserAccountDeleteView delete records an AuditLog action='account_delete' whose actor_email_hash was captured (row exists AFTER the user is gone, actor is None but hash present).**

```
from notifications import verification
class ChokePointTests(TestCase):
    def test_verify_emits_metric(self):
        u=get_user_model().objects.create_user(username='v',email='v@x.com',password='x')
        with self.assertLogs('jokesfor.metrics', level='INFO') as cm:
            verification.verify_code(u,'000000')
        self.assertTrue(any('verification_attempt' in r.getMessage() or getattr(r,'event',None)=='verification_attempt' for r in cm.records))
```

  - Expected: FAILS — no metric/audit emission at choke-points yet.

- [ ] **Step 2 (code): Edit serving.py allowed_tiers to emit content_tier_decision/age_gate_block on the 'jokesfor.metrics' logger (compute reason from the branch taken). Edit verification.verify_code to emit event=verification_attempt result=<the returned error or 'ok'> before each return. Edit jokes/views.py: CookieRegisterView.create (record_audit + metrics registration mode/outcome incl. the EmailSendError branch), ContentReportView.perform_create (record_audit content_report), UserBlockView post/delete (record_audit block/unblock), UserAccountDeleteView.delete (capture actor.pk + hash_email(user.email) BEFORE user.delete() at line 1713, record_audit account_delete actor=None AFTER the atomic block), DataExportView.get (record_audit data_export). Use function-local imports of record_audit to keep import-safety.**

  - Expected: No PII in metric lines (user_id int only, no email/DOB/code).

- [ ] **Step 3 (command): Run audit + a representative jokes test module to ensure no regressions in the touched views.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test audit jokes notifications --keepdb
```

  - Expected: Audit/metric tests pass; existing jokes/notifications suites stay green.

- [ ] **Step 4 (command): Commit.**

```
git add jokes/views.py jokes/serving.py notifications/verification.py audit/tests.py && git commit -m 'Emit audit + domain-metric logs at compliance and serving choke-points'
```

  - Expected: Commit created.

### Task 9: Task 9 — Sentry enrichment (release + before_send PII scrub + ignore_errors)

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/settings.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_observability.py`

- [ ] **Step 1 (test): Add SentryScrubTests(SimpleTestCase): import the before_send hook (factor it into JokesForProject/observability/sentry.py as scrub_event(event, hint) so it's unit-testable without a DSN). Assert scrub_event over an event with request.headers Authorization + cookies jokes-access-token + data password/code returns those values as '[REDACTED]'. Also assert the existing 'sentry not initialized without DSN' test still passes (regression).**

```
from JokesForProject.observability.sentry import scrub_event
class SentryScrubTests(SimpleTestCase):
    def test_scrub_headers_cookies_body(self):
        ev={'request':{'headers':{'Authorization':'Bearer x'},'cookies':{'jokes-access-token':'jwt'},'data':{'password':'p','code':'123456','ok':'keep'}}}
        out=scrub_event(ev, None); r=out['request']
        self.assertEqual(r['headers']['Authorization'],'[REDACTED]')
        self.assertEqual(r['cookies']['jokes-access-token'],'[REDACTED]')
        self.assertEqual(r['data']['password'],'[REDACTED]'); self.assertEqual(r['data']['ok'],'keep')
```

  - Expected: FAILS — sentry.scrub_event missing.

- [ ] **Step 2 (code): Create JokesForProject/observability/sentry.py with scrub_event(event, hint) applying redact_mapping to request.headers/cookies/data + extra. Edit the existing `if SENTRY_DSN:` block in settings.py to add release=os.getenv('K_REVISION') or None, before_send=scrub_event, and ignore_errors=[Throttled, NotAuthenticated, PermissionDenied, AuthenticationFailed, Http404, ValidationError, EmailSendError] (import the DRF/Django/notifications exceptions lazily inside the guard). Keep send_default_pii=False and traces_sample_rate env-gated default 0.**

  - Expected: All Sentry changes stay inside the DSN guard (local/test remain no-op).

- [ ] **Step 3 (command): Run Sentry + security settings tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test JokesForProject.tests.test_observability.SentryScrubTests JokesForProject.tests.test_security_settings --keepdb
```

  - Expected: Scrub tests pass; Sentry-no-DSN regression test still green.

- [ ] **Step 4 (command): Commit.**

```
git add JokesForProject/observability/sentry.py JokesForProject/settings.py JokesForProject/tests/test_observability.py && git commit -m 'Enrich Sentry init with release, PII scrub, and noise filtering'
```

  - Expected: Commit created.

### Task 10: Task 10 — readyz version/deploy signal + Dockerfile access-log dedupe

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/health.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/tests/test_healthz.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/Dockerfile`

- [ ] **Step 1 (test): Extend test_healthz.py: readyz 200 payload now includes a 'version' key (K_REVISION or 'unknown'); healthz remains dependency-free and unchanged. (Keep the existing 7 tests intact.)**

```
def test_readyz_reports_version(self):
    resp=self.client.get('/readyz'); self.assertIn('version', resp.json())
```

  - Expected: FAILS — readyz has no version field yet.

- [ ] **Step 2 (code): Edit health.py readyz to add version = os.getenv('K_REVISION') or os.getenv('GIT_SHA') or 'unknown' into the payload and emit a 'jokesfor.health' info line with the version on the success path (deploy visibility). Keep healthz untouched. Edit Dockerfile CMD: remove the '--access-logfile -' line (keep '--error-logfile -').**

  - Expected: Single structured access line per request after this; readyz exposes the running revision.

- [ ] **Step 3 (command): Run health tests + full suite to confirm nothing regressed.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test --keepdb
```

  - Expected: Entire suite green (observability + audit + health + existing).

- [ ] **Step 4 (command): Commit.**

```
git add JokesForProject/health.py JokesForProject/tests/test_healthz.py Dockerfile && git commit -m 'Add deploy version to readyz and drop duplicate gunicorn access log'
```

  - Expected: Commit created. Branch ready for PR (do not push/PR unless asked).

## Deferred — console/IaC (you set up in GCP)

- LOG-BASED METRIC (counter) — 5xx rate: gcloud logging metrics create http_5xx --project=332865216810 with filter `resource.type=cloud_run_revision AND resource.labels.service_name=jokesforbackend AND jsonPayload.status>=500` (or severity>=ERROR on jsonPayload from the jokesfor.access logger). Label-extract jsonPayload.route to break down by route.
- LOG-BASED METRIC (distribution) — request latency: distribution metric on jsonPayload.latency_ms from the jokesfor.access logger, value extractor EXTRACT(jsonPayload.latency_ms), filtered to cloud_run_revision/jokesforbackend, grouped by jsonPayload.route. Drives p50/p95/p99 per route.
- LOG-BASED METRIC (distribution + counter) — DB pressure: distribution on jsonPayload.db_time_ms and counter sum of jsonPayload.db_query_count, per route. Surfaces query-heavy endpoints (search/serving).
- LOG-BASED METRICS (counters by label) — domain events: counters on jsonPayload.event for the jokesfor.metrics logger — throttle_hit (label scope), registration (label outcome), age_gate_block, content_tier_decision (label tiers_granted), verification_attempt (label result). And on the jokesfor.audit logger: content_report (label reason), account_delete, login (label outcome).
- ALERT — readiness/uptime: Cloud Monitoring Uptime Check on https://<service-url>/readyz every 60s from >=3 regions expecting HTTP 200; alert CRITICAL when check_passed=false for >=2 consecutive runs (~2-3 min) from a majority of regions. Do NOT point Cloud Run's liveness probe at /readyz — keep liveness on /healthz so a Neon blip never mass-recycles instances.
- ALERT — high 5xx rate: on the http_5xx log-based metric (or run.googleapis.com/request_count response_code_class=5xx). Fire HIGH when 5xx/total > 2% over 5-min rolling AND absolute 5xx > 5/min (absolute floor prevents low-traffic flapping); separate WARNING at >0.5% for trend.
- ALERT — latency p95/p99: on run.googleapis.com/request_latencies (or the latency_ms log-based distribution). WARNING p95 > 1500ms for 10min; HIGH p99 > 3000ms for 5min; near-timeout canary on any single request_latency >= 55s (gunicorn --timeout is 60s).
- ALERT — throttle/abuse spike (429s): on jsonPayload.event=throttle_hit grouped by scope (or request_count response_code=429). HIGH when >50/min sustained 10min; tighter threshold on scope=verification_resend (email-bomb signal).
- ALERT — content moderation / abuse: on the content_report log-based metric. Volume alert when content_report rate > ~20/h vs baseline (possible brigading). NOTE for compliance owner: jokes.ContentReport has NO CSAM-specific reason category today — a CSAM-specific CRITICAL page cannot distinguish CSAM from 'harassment'/'inappropriate' until the model choices are extended; flag to the moderation/compliance pillar.
- ALERT — Error Reporting / Sentry exception spike: confirm GCP Error Reporting auto-groups the JSON exception+severity=ERROR lines the formatter emits; enable new-error-type + count-spike notifications. Set SENTRY_DSN (currently empty) and SENTRY_ENVIRONMENT as Cloud Run env vars to activate the now-enriched Sentry (release=K_REVISION + trace tags + PII scrub); optionally set SENTRY_TRACES_SAMPLE_RATE=0.1. Recommend Sentry primary, Error Reporting backstop to avoid double-paging.
- ALERT — infra: TLS cert status != ACTIVE (or 14d to expiry); Cloud Run instance count approaching max-instances; Neon connection/compute saturation (pooled host exhaustion surfaces as readyz DB failures); Cloud Run container restart-count spikes and OOM/'Container terminated' events.
- CLOUD RUN CONFIG — env + probes: ensure Cloud Run injects GOOGLE_CLOUD_PROJECT and K_REVISION (default behavior — verify); startup+liveness probe = HTTP GET /healthz; do NOT set 'CPU always allocated' for observability (the manual trace approach needs no background flush, unlike OTel BatchSpanProcessor). Set LOG_LEVEL/LOG_FORMAT only if overriding defaults (json auto in prod).
- TRACE — no IAM/API change required for the manual approach (we never call the Cloud Trace API; Cloud Run builds trace entries from request logs and the formatter's logging.googleapis.com/trace key makes log lines click through). For the record: if a future dev ever adds direct trace export, the runtime service account needs roles/cloudtrace.agent — but do NOT reintroduce OTel BatchSpanProcessor (its background flush silently drops spans under Cloud Run CPU throttling).
- LOG ROUTER / RETENTION — optionally create a log sink to BigQuery for long-term analytics and set the _Default log bucket retention per compliance needs (default 30d); the audit AuditLog DB table is the authoritative compliance evidence store, the jokesfor.audit stdout mirror is the fallback.
- DASHBOARD — build a Cloud Monitoring dashboard combining the RED signals (request_count, request_latencies, 5xx ratio), the DB-pressure distributions, and the domain-event counters (registration/verification/age_gate/content_report) keyed on service jokesforbackend; correlate deploys via the readyz version line / K_REVISION.