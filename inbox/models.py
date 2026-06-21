from django.conf import settings
from django.db import models


class Notification(models.Model):
    """In-app notification. Created synchronously when an event happens (new
    follower, joke published, joke removed) — no workers, no cron."""

    VERB_CHOICES = [
        ('followed_you', 'Followed you'),
        ('joke_published', 'Your joke was published'),
        ('joke_removed', 'Your joke was removed'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications'
    )
    # Who triggered it (e.g. the follower). Null for system events (moderation).
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    verb = models.CharField(max_length=32, choices=VERB_CHOICES)
    # Optional related joke (publish/removal). SET_NULL so a deleted joke doesn't
    # cascade away the notification.
    joke = models.ForeignKey(
        'jokes.Joke', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'read', 'created_at']),
        ]

    def __str__(self):
        return f'{self.verb} -> user {self.recipient_id}'
