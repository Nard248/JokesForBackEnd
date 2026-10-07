"""Guard for management commands that write synthetic or test data.

The repo's ``.env`` points ``DATABASE_URL`` at production, so an unguarded
seed command run from a developer machine writes fake accounts into the live
database (this happened with ``seed_demo_creator`` on 2026-07-05). Every
command that creates fake users, jokes or engagement calls
``require_local_database`` before its first write. Reference-data seeds that
are meant for production (``seed_achievements``, ``seed_jokes``) do not.
"""
import os

from django.conf import settings
from django.core.management.base import CommandError
from django.db import connections

LOOPBACK_HOSTS = {'localhost', '127.0.0.1', '::1'}


def require_local_database(command):
    """Refuse unless DEBUG, loopback PostgreSQL and local file storage.

    Inspects connection settings without opening a connection, so it is safe to
    call before any transaction (even a destructive ``--fresh`` never reaches a
    remote database).
    """
    config = connections['default'].settings_dict
    routing = config.get('OPTIONS') or {}
    if (
        not settings.DEBUG
        or config.get('ENGINE') != 'django.db.backends.postgresql'
        or str(config.get('HOST', '')).lower() not in LOOPBACK_HOSTS
        or any(routing.get(key) or os.environ.get('PG' + key.upper()) for key in ('hostaddr', 'service'))
        or settings.STORAGES['default']['BACKEND'] != 'django.core.files.storage.FileSystemStorage'
    ):
        raise CommandError(
            f'{command} is local-only: requires DEBUG=True, explicit loopback PostgreSQL, '
            'no hostaddr/service overrides, and local filesystem storage. '
            "Clear DATABASE_URL (DATABASE_URL='') and GS_BUCKET_NAME before running it."
        )
