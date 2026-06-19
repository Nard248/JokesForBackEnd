"""Tests for the JokesForProject.observability package.

All tests here are DB-free (SimpleTestCase) so the observability suite
runs even when Neon/local Postgres is unreachable.
"""
import json
import logging
from django.test import SimpleTestCase, RequestFactory
from django.http import HttpResponse

from JokesForProject.observability import context as ctx


# ─────────────────────────────────────────────────────────────────────────────
# Task 1 — contextvars: bind / clear / DB stats
# ─────────────────────────────────────────────────────────────────────────────

class ContextTests(SimpleTestCase):

    def tearDown(self):
        # Ensure no contextvar leaks between tests
        ctx.clear_request_context(ctx.bind_request_context(
            request_id=None, trace=None, span=None, user_id=None, sampled=None,
        ))
        ctx.reset_db_stats()

    def test_bind_and_clear_no_leak(self):
        self.assertEqual(ctx.get_log_fields(), {})
        tokens = ctx.bind_request_context(request_id='r1', trace='abc', user_id=7)
        f = ctx.get_log_fields()
        self.assertEqual(f['request_id'], 'r1')
        self.assertEqual(f['user_id'], 7)
        ctx.clear_request_context(tokens)
        self.assertEqual(ctx.get_log_fields(), {})

    def test_db_stats_accumulate_and_reset(self):
        ctx.reset_db_stats()
        ctx.add_db_query(1.5)
        ctx.add_db_query(2.5)
        s = ctx.get_db_stats()
        self.assertEqual(s['db_query_count'], 2)
        self.assertAlmostEqual(s['db_time_ms'], 4.0, places=1)


# ─────────────────────────────────────────────────────────────────────────────
# Task 2 — redaction helpers
# ─────────────────────────────────────────────────────────────────────────────

class RedactionTests(SimpleTestCase):

    def setUp(self):
        from JokesForProject.observability import redaction as red
        self.red = red

    def test_mask_email(self):
        self.assertEqual(self.red.mask_email('alice@example.com'), 'a***@example.com')

    def test_hash_email_stable_12hex(self):
        h = self.red.hash_email('alice@example.com')
        self.assertEqual(len(h), 12)
        self.assertEqual(h, self.red.hash_email('alice@example.com'))
        # Must be lowercase hex
        self.assertTrue(all(c in '0123456789abcdef' for c in h))

    def test_mask_ip_v4(self):
        self.assertEqual(self.red.mask_ip('203.0.113.45'), '203.0.113.0')

    def test_mask_ip_v6(self):
        result = self.red.mask_ip('2001:db8:85a3::8a2e:370:7334')
        # Should keep first 3 hextets and truncate
        self.assertTrue(result.startswith('2001:db8:85a3'))

    def test_redact_denylist(self):
        out = self.red.redact_mapping({
            'password': 'x',
            'code': '123456',
            'authorization': 'Bearer y',
            'nested': {'token': 't', 'ok': 'keep'},
            'jokes-access-token': 'jwt',
        })
        self.assertEqual(out['password'], '[REDACTED]')
        self.assertEqual(out['code'], '[REDACTED]')
        self.assertEqual(out['authorization'], '[REDACTED]')
        self.assertEqual(out['nested']['token'], '[REDACTED]')
        self.assertEqual(out['nested']['ok'], 'keep')
        self.assertEqual(out['jokes-access-token'], '[REDACTED]')

    def test_redact_preserves_benign_keys(self):
        out = self.red.redact_mapping({'user_id': 42, 'status': 'ok'})
        self.assertEqual(out['user_id'], 42)
        self.assertEqual(out['status'], 'ok')

    def test_redact_in_list(self):
        out = self.red.redact_mapping({'items': [{'password': 'p', 'id': 1}]})
        self.assertEqual(out['items'][0]['password'], '[REDACTED]')
        self.assertEqual(out['items'][0]['id'], 1)


# ─────────────────────────────────────────────────────────────────────────────
# Task 3 — GoogleCloudJsonFormatter
# ─────────────────────────────────────────────────────────────────────────────

class FormatterTests(SimpleTestCase):

    def tearDown(self):
        ctx.clear_request_context(ctx.bind_request_context(
            request_id=None, trace=None, span=None, user_id=None, sampled=None,
        ))

    def _rec(self, level=logging.INFO, msg='hello', exc_info=None):
        return logging.LogRecord('test.logger', level, __file__, 10, msg, (), exc_info)

    def test_basic_shape(self):
        from JokesForProject.observability.formatters import GoogleCloudJsonFormatter
        line = GoogleCloudJsonFormatter().format(self._rec())
        d = json.loads(line)
        self.assertEqual(d['severity'], 'INFO')
        self.assertEqual(d['message'], 'hello')
        self.assertIn('timestamp', d)
        self.assertIn('sourceLocation', d)

    def test_trace_key_present_with_valid_32hex(self):
        from JokesForProject.observability.formatters import GoogleCloudJsonFormatter
        trace = 'a' * 32
        tok = ctx.bind_request_context(trace=trace, request_id='r1')
        try:
            d = json.loads(GoogleCloudJsonFormatter().format(self._rec()))
            self.assertIn('logging.googleapis.com/trace', d)
            self.assertTrue(d['logging.googleapis.com/trace'].endswith('/traces/' + trace))
            self.assertEqual(d['request_id'], 'r1')
        finally:
            ctx.clear_request_context(tok)

    def test_trace_key_absent_without_valid_trace(self):
        from JokesForProject.observability.formatters import GoogleCloudJsonFormatter
        # Short/invalid trace — must not appear in output (prevents log injection)
        tok = ctx.bind_request_context(trace='short')
        try:
            d = json.loads(GoogleCloudJsonFormatter().format(self._rec()))
            self.assertNotIn('logging.googleapis.com/trace', d)
        finally:
            ctx.clear_request_context(tok)

    def test_exception_field_included(self):
        from JokesForProject.observability.formatters import GoogleCloudJsonFormatter
        try:
            raise ValueError('boom')
        except ValueError:
            import sys
            exc = sys.exc_info()
        rec = self._rec(level=logging.ERROR, exc_info=exc)
        d = json.loads(GoogleCloudJsonFormatter().format(rec))
        self.assertIn('exception', d)
        self.assertIn('ValueError', d['exception'])

    def test_severity_mapping(self):
        from JokesForProject.observability.formatters import GoogleCloudJsonFormatter
        fmt = GoogleCloudJsonFormatter()
        for level, expected in [
            (logging.DEBUG, 'DEBUG'),
            (logging.WARNING, 'WARNING'),
            (logging.ERROR, 'ERROR'),
            (logging.CRITICAL, 'CRITICAL'),
        ]:
            d = json.loads(fmt.format(self._rec(level=level)))
            self.assertEqual(d['severity'], expected)


# ─────────────────────────────────────────────────────────────────────────────
# Task 4 — RequestContextMiddleware + AccessLogMiddleware
# ─────────────────────────────────────────────────────────────────────────────

class MiddlewareTests(SimpleTestCase):

    def setUp(self):
        self.rf = RequestFactory()

    def tearDown(self):
        # Belt-and-suspenders cleanup after each test
        ctx.clear_request_context(ctx.bind_request_context(
            request_id=None, trace=None, span=None, user_id=None, sampled=None,
        ))
        ctx.reset_db_stats()

    def test_generates_and_echoes_request_id_and_no_leak(self):
        from JokesForProject.observability.middleware import RequestContextMiddleware
        mw = RequestContextMiddleware(lambda r: HttpResponse('ok'))
        resp = mw(self.rf.get('/x'))
        self.assertTrue(resp['X-Request-ID'])
        # After the request contextvars must be cleared
        self.assertEqual(ctx.get_log_fields(), {})

    def test_propagates_incoming_request_id(self):
        from JokesForProject.observability.middleware import RequestContextMiddleware
        mw = RequestContextMiddleware(lambda r: HttpResponse('ok'))
        resp = mw(self.rf.get('/x', HTTP_X_REQUEST_ID='abc123'))
        self.assertEqual(resp['X-Request-ID'], 'abc123')

    def test_parses_cloud_trace_context(self):
        from JokesForProject.observability.middleware import RequestContextMiddleware
        trace_id = 'b' * 32
        captured = {}

        def inner(request):
            captured.update(ctx.get_log_fields())
            return HttpResponse('ok')

        mw = RequestContextMiddleware(inner)
        mw(self.rf.get('/x', HTTP_X_CLOUD_TRACE_CONTEXT=f'{trace_id}/456;o=1'))
        self.assertEqual(captured.get('trace'), trace_id)
        self.assertEqual(captured.get('span'), '456')
        self.assertEqual(captured.get('sampled'), True)

    def test_invalid_trace_header_rejected(self):
        from JokesForProject.observability.middleware import RequestContextMiddleware
        captured = {}

        def inner(request):
            captured.update(ctx.get_log_fields())
            return HttpResponse('ok')

        mw = RequestContextMiddleware(inner)
        # Not a 32-hex trace — must not bind trace
        mw(self.rf.get('/x', HTTP_X_CLOUD_TRACE_CONTEXT='INVALID/123;o=1'))
        self.assertNotIn('trace', captured)

    def test_no_contextvar_leak_across_requests(self):
        from JokesForProject.observability.middleware import RequestContextMiddleware
        mw = RequestContextMiddleware(lambda r: HttpResponse('ok'))
        mw(self.rf.get('/first'))
        # After first request, all vars should be cleared
        self.assertEqual(ctx.get_log_fields(), {})
        mw(self.rf.get('/second'))
        self.assertEqual(ctx.get_log_fields(), {})

    def test_access_log_one_line_and_severity_500(self):
        from JokesForProject.observability.middleware import AccessLogMiddleware
        mw = AccessLogMiddleware(lambda r: HttpResponse('boom', status=500))
        with self.assertLogs('jokesfor.access', level='INFO') as cm:
            mw(self.rf.get('/api/v1/jokes/'))
        self.assertEqual(len(cm.records), 1)
        self.assertEqual(cm.records[0].levelname, 'ERROR')

    def test_access_log_200_is_info(self):
        from JokesForProject.observability.middleware import AccessLogMiddleware
        mw = AccessLogMiddleware(lambda r: HttpResponse('ok', status=200))
        with self.assertLogs('jokesfor.access', level='INFO') as cm:
            mw(self.rf.get('/api/v1/jokes/'))
        self.assertEqual(cm.records[0].levelname, 'INFO')

    def test_access_log_400_is_warning(self):
        from JokesForProject.observability.middleware import AccessLogMiddleware
        mw = AccessLogMiddleware(lambda r: HttpResponse('bad', status=400))
        with self.assertLogs('jokesfor.access', level='INFO') as cm:
            mw(self.rf.get('/api/v1/jokes/'))
        self.assertEqual(cm.records[0].levelname, 'WARNING')

    def test_healthz_suppressed_at_info(self):
        from JokesForProject.observability.middleware import AccessLogMiddleware
        mw = AccessLogMiddleware(lambda r: HttpResponse('ok'))
        with self.assertNoLogs('jokesfor.access', level='INFO'):
            mw(self.rf.get('/healthz'))

    def test_readyz_suppressed_at_info(self):
        from JokesForProject.observability.middleware import AccessLogMiddleware
        mw = AccessLogMiddleware(lambda r: HttpResponse('ok'))
        with self.assertNoLogs('jokesfor.access', level='INFO'):
            mw(self.rf.get('/readyz'))


# ─────────────────────────────────────────────────────────────────────────────
# Task 5 — settings wiring
# ─────────────────────────────────────────────────────────────────────────────

class SettingsWiringTests(SimpleTestCase):

    def test_middleware_order(self):
        from django.conf import settings as s
        mw = s.MIDDLEWARE
        rc = 'JokesForProject.observability.middleware.RequestContextMiddleware'
        al = 'JokesForProject.observability.middleware.AccessLogMiddleware'
        self.assertIn(rc, mw)
        self.assertIn(al, mw)
        self.assertLess(mw.index(rc), mw.index(al))
        self.assertLess(mw.index('whitenoise.middleware.WhiteNoiseMiddleware'), mw.index(rc))

    def test_logging_and_project(self):
        from django.conf import settings as s
        self.assertIn('gcp_json', s.LOGGING['formatters'])
        self.assertIn('jokesfor.access', s.LOGGING['loggers'])
        self.assertIn('jokesfor.audit', s.LOGGING['loggers'])
        self.assertEqual(s.GOOGLE_CLOUD_PROJECT, '332865216810')


# ─────────────────────────────────────────────────────────────────────────────
# Task 9 — Sentry PII scrub
# ─────────────────────────────────────────────────────────────────────────────

class SentryScrubTests(SimpleTestCase):

    def test_scrub_headers_cookies_body(self):
        from JokesForProject.observability.sentry import scrub_event
        ev = {
            'request': {
                'headers': {'Authorization': 'Bearer x'},
                'cookies': {'jokes-access-token': 'jwt'},
                'data': {'password': 'p', 'code': '123456', 'ok': 'keep'},
            }
        }
        out = scrub_event(ev, None)
        r = out['request']
        self.assertEqual(r['headers']['Authorization'], '[REDACTED]')
        self.assertEqual(r['cookies']['jokes-access-token'], '[REDACTED]')
        self.assertEqual(r['data']['password'], '[REDACTED]')
        self.assertEqual(r['data']['code'], '[REDACTED]')
        self.assertEqual(r['data']['ok'], 'keep')

    def test_scrub_handles_missing_request(self):
        from JokesForProject.observability.sentry import scrub_event
        ev = {'message': 'test', 'extra': {'secret': 'abc'}}
        out = scrub_event(ev, None)
        # Should not raise; extra is also scrubbed
        self.assertEqual(out['extra']['secret'], '[REDACTED]')
