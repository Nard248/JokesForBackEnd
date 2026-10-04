"""Self-forming communities on real JokesFor data.

A community is the audience that forms around one theme (ContextTag). The
theme vocabulary is canonical, which prevents duplicate groups about the same
topic. Membership is *inferred* from engagement (see ``engine.py``) and kept
separate from an *explicit* join/leave choice, which this module persists.
"""
from django.conf import settings
from django.db import models

from jokes.models import ContextTag


class Community(models.Model):
    """Presentation and listing metadata for the community around one theme."""

    tag = models.OneToOneField(ContextTag, on_delete=models.CASCADE, related_name='community')
    emoji = models.CharField(max_length=8, default='✨')
    color = models.CharField(max_length=7, default='#6A1CF6')
    tagline = models.CharField(max_length=160, blank=True)
    is_listed = models.BooleanField(
        default=True, help_text='Unlisted communities are hidden from the directory and creator tools.',
    )

    class Meta:
        verbose_name_plural = 'communities'
        ordering = ['tag__name']

    def __str__(self):
        return f'{self.emoji} {self.tag.name}'

    @property
    def slug(self):
        return self.tag.slug


class CommunityMembership(models.Model):
    """An explicit choice. ``left`` overrides inference until the person rejoins."""

    STATE_JOINED = 'joined'
    STATE_LEFT = 'left'
    STATE_CHOICES = [(STATE_JOINED, 'Joined'), (STATE_LEFT, 'Left')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='community_memberships')
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='memberships')
    state = models.CharField(max_length=8, choices=STATE_CHOICES)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'community'], name='communities_unique_membership'),
        ]

    def __str__(self):
        return f'{self.user_id}: {self.state} {self.community_id}'
