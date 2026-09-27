"""Private creator organization and explicit taxonomy review requests."""
from django.conf import settings
from django.db import models


class CreatorWorkspaceNote(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='creator_notes')
    joke = models.ForeignKey('jokes.Joke', on_delete=models.CASCADE, related_name='+')
    private_note = models.TextField(blank=True, max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['owner', 'joke'], name='creator_note_owner_joke_uniq')]

    def __str__(self):
        return f'Private note {self.pk}'


class CreatorCollection(models.Model):
    class Kind(models.TextChoices):
        SERIES = 'series', 'Series'
        SET_LIST = 'set_list', 'Set list'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='creator_collections')
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    description = models.TextField(blank=True, max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-pk']

    def __str__(self):
        return f'Private collection {self.pk}'


class CreatorCollectionEntry(models.Model):
    collection = models.ForeignKey(CreatorCollection, on_delete=models.CASCADE, related_name='entries')
    joke = models.ForeignKey('jokes.Joke', on_delete=models.CASCADE, related_name='+')
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['position', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['collection', 'joke'], name='creator_collection_joke_uniq'),
            models.UniqueConstraint(fields=['collection', 'position'], name='creator_collection_pos_uniq'),
        ]

    def __str__(self):
        return f'Collection entry {self.pk}'


class CreatorMetadataRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending review'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='creator_metadata_requests')
    joke = models.ForeignKey('jokes.Joke', on_delete=models.CASCADE, related_name='+')
    changes = models.JSONField()
    before_metadata = models.JSONField()
    after_metadata = models.JSONField(default=dict)
    baseline_hash = models.CharField(max_length=64)
    reason = models.TextField(blank=True, max_length=1000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    decision_reason = models.TextField(blank=True, max_length=1000)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(
            fields=['owner', 'joke'], condition=models.Q(status='pending'),
            name='creator_metadata_pending_uniq',
        )]

    def __str__(self):
        return f'Metadata request {self.pk} ({self.status})'
