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


class CommunitySignal(models.Model):
    """Materialized positive engagement: one row per source ledger row.

    Maintained synchronously by ``communities.materialize`` whenever a reaction,
    favorite, save or signed-in share is written or deleted, so community
    aggregates read this one narrow table instead of four ledgers. Negative
    reactions and anonymous shares never get a row; shares that can no longer
    affect any number are pruned.

    Eligibility is deliberately *not* stored: consent, adulthood, joke tier,
    removal and themes are applied when reading, so a withdrawal, takedown or
    re-tag takes effect without touching this table. Rows go with the account
    or the joke (CASCADE).
    """

    KIND_LIKE = 'like'
    KIND_FAVORITE = 'favorite'
    KIND_SAVE = 'save'
    KIND_SHARE = 'share'
    KIND_CHOICES = [(KIND_LIKE, 'Laugh reaction'), (KIND_FAVORITE, 'Favorite'), (KIND_SAVE, 'Save'),
                    (KIND_SHARE, 'Signed-in share')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    joke = models.ForeignKey('jokes.Joke', on_delete=models.CASCADE, related_name='+')
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    source_id = models.BigIntegerField(help_text='Primary key of the ledger row this mirrors.')
    occurred_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['kind', 'source_id'], name='communities_unique_signal_source'),
        ]
        indexes = [
            models.Index(fields=['occurred_at'], name='communities_signal_at'),
            models.Index(fields=['user', 'joke', 'kind'], name='communities_signal_pair'),
        ]

    def __str__(self):
        return f'{self.user_id} {self.kind} {self.joke_id} @ {self.occurred_at:%Y-%m-%d}'


class CommunityState(models.Model):
    """The last status the aggregate observed for a community, for detecting formation.

    Every recompute diffs its statuses against these rows
    (``communities.formation.record_transitions``) and notifies once per
    activation. A community seen for the first time is recorded as a baseline
    without notifying, so a deploy or a reseed never announces communities that
    were already active.
    """

    community = models.OneToOneField(Community, on_delete=models.CASCADE, related_name='state')
    status = models.CharField(max_length=8, choices=[('forming', 'Forming'), ('active', 'Active'),
                                                     ('cooling', 'Cooling')])
    observed_at = models.DateTimeField(help_text='When the aggregate that set this status was computed.')
    active_since = models.DateTimeField(null=True, blank=True,
                                        help_text='Start of the current (or most recent) active period.')
    inactive_since = models.DateTimeField(null=True, blank=True,
                                          help_text='When it last stopped being active; null while active.')
    notified_at = models.DateTimeField(null=True, blank=True,
                                       help_text='When "community formed" notifications last went out.')

    def __str__(self):
        return f'{self.community_id}: {self.status}'
