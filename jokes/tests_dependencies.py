"""Guards for deliberate omissions in requirements.txt.

oauthlib was dropped (PYSEC-2026-4114) because nothing the project loads
needs it. The shared dev venv may still have it installed, so an import that
reintroduced the dependency would pass locally and fail only in a fresh
install (the Docker image or CI). These tests load the app in a subprocess
where ``import oauthlib`` is forced to fail, whatever is installed.
"""

import os
import subprocess
import sys
import textwrap

from django.conf import settings
from django.test import SimpleTestCase

_BLOCK_OAUTHLIB = textwrap.dedent(
    """
    import importlib.abc
    import sys


    class _BlockOauthlib(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == "oauthlib" or name.startswith("oauthlib."):
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)
            return None


    sys.meta_path.insert(0, _BlockOauthlib())
    for _mod in [m for m in sys.modules if m == "oauthlib" or m.startswith("oauthlib.")]:
        del sys.modules[_mod]

    import django

    django.setup()
    """
)


def _run_without_oauthlib(body):
    env = dict(os.environ)
    env.setdefault("DJANGO_SETTINGS_MODULE", "JokesForProject.settings")
    return subprocess.run(  # noqa: S603 - fixed interpreter, script built in this file
        [sys.executable, "-c", _BLOCK_OAUTHLIB + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        env=env,
        cwd=settings.BASE_DIR,
        timeout=120,
    )


class OauthlibNotRequiredTests(SimpleTestCase):
    def test_blocker_actually_blocks_oauthlib(self):
        # Sanity check: the OAuth1 client that dj_rest_auth.social_serializers
        # pulls in must fail under the blocker, or the next test proves nothing.
        result = _run_without_oauthlib(
            """
            try:
                import allauth.socialaccount.providers.oauth.client  # noqa: F401
            except ModuleNotFoundError as exc:
                assert exc.name.startswith("oauthlib"), exc.name
                print("BLOCKED")
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BLOCKED", result.stdout)

    def test_app_and_google_login_load_without_oauthlib(self):
        result = _run_without_oauthlib(
            f"""
            import importlib

            from django.urls import get_resolver

            # Every installed app's models/admin/apps, then the full URLconf,
            # which imports every view module.
            from django.contrib import admin

            admin.autodiscover()
            get_resolver().url_patterns
            importlib.import_module({settings.ROOT_URLCONF!r})
            importlib.import_module("allauth.socialaccount.providers.google.views")
            importlib.import_module("dj_rest_auth.registration.views")
            print("LOADED")
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LOADED", result.stdout)
