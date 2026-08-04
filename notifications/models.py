from django.conf import settings
from django.db import models
from django.utils import timezone


class EmailMessageLog(models.Model):
    """Outbox + audit trail for every email the system attempts to send."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    to_email = models.EmailField(db_index=True)
    template_name = models.CharField(max_length=80)
    subject = models.CharField(max_length=255)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='pending', db_index=True
    )
    provider_message_id = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='email_logs',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['to_email', '-created_at'])]

    def __str__(self):
        return f'{self.template_name} -> {self.to_email} ({self.status})'


class EmailVerification(models.Model):
    """6-digit code lifecycle for registration email verification."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='email_verifications',
    )
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', '-created_at'])]

    def __str__(self):
        return f'verification for {self.user_id} (expires {self.expires_at:%Y-%m-%d %H:%M})'

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_consumed(self):
        return self.consumed_at is not None


class DigestRun(models.Model):
    """One row per calendar date the digest engine (notifications.digests)
    has run for. This is observability + a per-day anchor, NOT the
    idempotency ledger — that's EmailMessageLog (queried per-user/per-creator
    for "did we already send template=X today"). A date can be touched by
    several calls (retries, cap-bounded continuations); counts accumulate.
    """

    date = models.DateField(unique=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    digests_sent = models.PositiveIntegerField(default=0)
    milestones_sent = models.PositiveIntegerField(default=0)
    # Pooling-safe run claim (replaces a session-scoped pg advisory lock,
    # which is unsafe under Neon's `-pooler` PgBouncer transaction-pooling
    # mode -- see notifications.digests.run_daily_digests). NULL/in-the-past
    # means unclaimed; a single conditional UPDATE flips it forward for the
    # claim window, and a `finally` clears it back to NULL when the run
    # finishes. The window itself is only a crash/SIGKILL self-heal
    # fallback, not the normal release path.
    claimed_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return (
            f'DigestRun {self.date} '
            f'(digests={self.digests_sent}, milestones={self.milestones_sent})'
        )
