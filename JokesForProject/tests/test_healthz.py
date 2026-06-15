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
