from unittest import mock

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

    def test_healthz_dependency_free(self):
        """healthz must return 200 even when the DB is completely unreachable."""
        with mock.patch('django.db.connection.cursor', side_effect=Exception('db down')):
            resp = self.client.get('/healthz')
        self.assertEqual(resp.status_code, 200)


class ReadyzTests(TestCase):
    def test_readyz_returns_200_when_healthy(self):
        resp = self.client.get('/readyz')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json().get('status'), 'ready')

    def test_readyz_is_not_throttled(self):
        for _ in range(20):
            resp = self.client.get('/readyz')
            self.assertEqual(resp.status_code, 200)

    def test_readyz_reports_version(self):
        resp = self.client.get('/readyz')
        self.assertIn('version', resp.json())

    def test_readyz_503_when_db_down(self):
        with mock.patch(
            'django.db.connection.cursor',
            side_effect=Exception('db down'),
        ):
            resp = self.client.get('/readyz')
        self.assertEqual(resp.status_code, 503)
        body = resp.json()
        self.assertEqual(body['status'], 'not_ready')
        self.assertEqual(body['checks']['db']['status'], 'error')

    def test_readyz_503_when_cache_down(self):
        with mock.patch(
            'django.core.cache.cache.set',
            side_effect=Exception('cache down'),
        ):
            resp = self.client.get('/readyz')
        self.assertEqual(resp.status_code, 503)
        body = resp.json()
        self.assertEqual(body['status'], 'not_ready')
        self.assertEqual(body['checks']['cache']['status'], 'error')


class LivezAliasTests(TestCase):
    """`/healthz` is unreachable through the public Cloud Run URL.

    Verified in production: GET /healthz returns a Google-edge HTML 404 with
    none of Django's security headers, while /healthzz and /healthz/ return
    Django 404s and /readyz returns 200 — i.e. the edge intercepts that exact
    reserved path before it reaches the container. The view is fine (it answers
    200 locally); it just cannot be reached from outside, so any external uptime
    check pointed at it is dead. /livez is the same probe on a path the edge
    does not claim.
    """

    def test_livez_is_an_unauthenticated_liveness_probe(self):
        resp = self.client.get('/livez')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'status': 'ok'})

    def test_livez_matches_healthz_exactly(self):
        self.assertEqual(
            self.client.get('/livez').json(),
            self.client.get('/healthz').json(),
        )
