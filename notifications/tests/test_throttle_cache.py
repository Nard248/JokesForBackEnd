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
