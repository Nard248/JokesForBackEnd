"""Synthetic-data seeds must never reach a non-local database.

``seed_demo_creator`` once wrote 140 fake accounts into production because it
had no guard; every command that creates fake users, jokes or engagement now
calls ``require_local_database`` first.
"""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test import SimpleTestCase, override_settings

from jokes.management.local_only import require_local_database

SYNTHETIC_SEEDS = ['seed_demo_creator', 'seed_media_dev', 'seed_e2e', 'seed_showcase']


class LocalOnlySeedTests(SimpleTestCase):
    def test_every_synthetic_seed_refuses_outside_debug(self):
        for command in SYNTHETIC_SEEDS:
            with self.subTest(command=command), override_settings(DEBUG=False):
                with self.assertRaisesMessage(CommandError, f'{command} is local-only'):
                    call_command(command, stdout=StringIO())

    def test_a_remote_host_is_refused_even_in_debug(self):
        remote = {**connections['default'].settings_dict, 'HOST': 'ep-prod.us-east-1.aws.neon.tech'}
        with override_settings(DEBUG=True), mock.patch.dict(connections['default'].settings_dict, remote):
            for command in SYNTHETIC_SEEDS:
                with self.subTest(command=command):
                    with self.assertRaisesMessage(CommandError, f'{command} is local-only'):
                        call_command(command, stdout=StringIO())

    def test_loopback_debug_filesystem_is_allowed(self):
        with override_settings(DEBUG=True), mock.patch.dict(connections['default'].settings_dict, {'HOST': 'localhost'}):
            require_local_database('anything')  # does not raise
