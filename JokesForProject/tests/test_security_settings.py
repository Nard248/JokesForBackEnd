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

    def test_missing_secret_key_in_prod_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        import importlib
        import JokesForProject.settings as s
        # Set SECRET_KEY to empty string: load_dotenv() re-runs on reload but
        # won't override an already-set (even empty) env var (override=False).
        with mock.patch.dict(os.environ, {'DEBUG': 'False', 'SECRET_KEY': ''}, clear=False):
            with self.assertRaises(ImproperlyConfigured):
                importlib.reload(s)

    def test_dev_fallback_secret_key_when_debug(self):
        # pop SECRET_KEY then reload to confirm the dev fallback path
        import importlib
        import JokesForProject.settings as s
        with mock.patch.dict(os.environ, {'DEBUG': 'True', 'SECRET_KEY': ''}, clear=False):
            s = importlib.reload(s)
        self.assertTrue(s.SECRET_KEY)

    @classmethod
    def tearDownClass(cls):
        # Restore the real settings module after reloads.
        import importlib
        import JokesForProject.settings as s
        importlib.reload(s)
        super().tearDownClass()
