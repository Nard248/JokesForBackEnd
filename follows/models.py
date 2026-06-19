from django.conf import settings
from django.db import models


class Follow(models.Model):
    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='following',
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='followers',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['follower', 'creator']]
        indexes = [
            models.Index(fields=['creator', 'created_at']),
            models.Index(fields=['follower', 'created_at']),
        ]

    def __str__(self):
        return f'{self.follower_id} follows {self.creator_id}'
