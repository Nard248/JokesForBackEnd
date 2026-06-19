"""Tests for the audit app: AuditLog model, record_audit(), signal hooks."""
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

from audit.models import AuditLog
from audit.services import record_audit

User = get_user_model()


class AuditServiceTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.u = User.objects.create_user(
            username='audituser', email='audit@example.com', password='testpass'
        )

    def test_writes_row_and_logs(self):
        with self.assertLogs('jokesfor.audit', level='INFO'):
            record_audit(self.rf.get('/'), 'login', outcome='success', actor=self.u)
        row = AuditLog.objects.get(action='login')
        self.assertEqual(row.outcome, 'success')
        # 64-hex SHA-256 digest stored, no @ or plaintext email
        self.assertEqual(len(row.actor_email_hash), 64)
        self.assertNotIn('@', row.actor_email_hash)

    def test_db_failure_still_logs(self):
        from unittest import mock
        with mock.patch('audit.models.AuditLog.objects.create', side_effect=Exception('neon down')):
            with self.assertLogs('jokesfor.audit', level='INFO'):
                record_audit(self.rf.get('/'), 'login', outcome='success', actor=self.u)

    def test_no_actor_stores_empty_hash(self):
        with self.assertLogs('jokesfor.audit', level='INFO'):
            record_audit(self.rf.get('/'), 'anonymous_event')
        row = AuditLog.objects.get(action='anonymous_event')
        self.assertEqual(row.actor_email_hash, '')
        self.assertIsNone(row.actor)

    def test_metadata_stored(self):
        with self.assertLogs('jokesfor.audit', level='INFO'):
            record_audit(
                self.rf.get('/'), 'data_export',
                actor=self.u, metadata={'format': 'json', 'size_bytes': 1024}
            )
        row = AuditLog.objects.get(action='data_export')
        self.assertEqual(row.metadata['format'], 'json')


class AppendOnlyTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(
            username='appenduser', email='append@example.com', password='x'
        )
        rf = RequestFactory()
        with self.assertLogs('jokesfor.audit', level='INFO'):
            record_audit(rf.get('/'), 'test_action', actor=self.u)
        self.row = AuditLog.objects.get(action='test_action')

    def test_update_blocked_by_trigger(self):
        import pgtrigger
        with self.assertRaises(Exception):
            with pgtrigger.ignore('audit.AuditLog:append_only'):
                pass
            self.row.outcome = 'failure'
            self.row.save()

    def test_delete_blocked_by_trigger(self):
        with self.assertRaises(Exception):
            self.row.delete()


class AuthSignalTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.u = User.objects.create_user(
            username='signaluser', email='signal@example.com', password='x'
        )

    def test_login_success_audited(self):
        from django.contrib.auth.signals import user_logged_in
        with self.assertLogs('jokesfor.audit', level='INFO'):
            user_logged_in.send(
                sender=self.u.__class__,
                request=self.rf.post('/login'),
                user=self.u,
            )
        self.assertTrue(
            AuditLog.objects.filter(action='login', outcome='success').exists()
        )

    def test_login_failed_no_request_no_enumeration(self):
        from django.contrib.auth.signals import user_login_failed
        with self.assertLogs('jokesfor.audit', level='INFO'):
            user_login_failed.send(
                sender=None,
                credentials={'email': 'ghost@x.com'},
                request=None,
            )
        row = AuditLog.objects.filter(action='login', outcome='failure').first()
        self.assertIsNotNone(row)
        # No actor FK (no user lookup)
        self.assertIsNone(row.actor)
        # No 'user_exists' flag in metadata (anti-enumeration)
        self.assertNotIn('user_exists', row.metadata or {})

    def test_logout_audited(self):
        from django.contrib.auth.signals import user_logged_out
        with self.assertLogs('jokesfor.audit', level='INFO'):
            user_logged_out.send(
                sender=self.u.__class__,
                request=self.rf.post('/logout'),
                user=self.u,
            )
        self.assertTrue(
            AuditLog.objects.filter(action='logout', outcome='success').exists()
        )
