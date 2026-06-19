"""Append-only audit log model.

Stores security-relevant events: login, registration, verification,
account deletion, data export, content reports, user blocks, and admin
moderation actions.

PII posture:
  - actor_email_hash: SHA-256 hex digest (64 chars), never plaintext email.
  - ip: last IPv4 octet zeroed / IPv6 truncated to /48 (mask_ip).
  - metadata: must not contain PII (caller responsibility).

Append-only enforcement:
  A pgtrigger Protect trigger blocks UPDATE and DELETE so rows are
  immutable evidence for DSA/COPPA/GDPR audits.
"""
from django.conf import settings
from django.db import models
import pgtrigger


class AuditLog(models.Model):
    OUTCOME_SUCCESS = 'success'
    OUTCOME_FAILURE = 'failure'
    OUTCOME_DENIED = 'denied'
    OUTCOME_CHOICES = [
        (OUTCOME_SUCCESS, 'Success'),
        (OUTCOME_FAILURE, 'Failure'),
        (OUTCOME_DENIED, 'Denied'),
    ]

    # Actor — NULL after account deletion (SET_NULL), or for system events.
    # actor_email_hash lets us correlate events even after the user row is gone.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='audit_events',
        db_index=True,
    )
    actor_email_hash = models.CharField(max_length=64, blank=True, db_index=True)

    # What happened
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)

    # Request context (from contextvars — may be blank for signal-only events)
    ip = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    user_agent = models.CharField(max_length=256, blank=True)

    # Outcome
    outcome = models.CharField(
        max_length=16,
        choices=OUTCOME_CHOICES,
        default=OUTCOME_SUCCESS,
        db_index=True,
    )

    # Non-PII supplementary data (reason, ids, etc.)
    metadata = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action', 'outcome']),
            models.Index(fields=['created_at']),
        ]
        triggers = [
            pgtrigger.Protect(
                name='append_only',
                operation=pgtrigger.Update | pgtrigger.Delete,
            ),
        ]

    def __str__(self):
        return f'{self.action} / {self.outcome} @ {self.created_at}'
