import uuid

from django.db import models
from django.utils import timezone


class Subject(models.Model):
    id = models.SlugField(primary_key=True, max_length=40)
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=280)
    color = models.CharField(max_length=7)
    emoji = models.CharField(max_length=8)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name


class Participant(models.Model):
    id = models.CharField(primary_key=True, max_length=40)
    name = models.CharField(max_length=80)

    def __str__(self):
        return self.name


class Content(models.Model):
    id = models.CharField(primary_key=True, max_length=60)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    title = models.CharField(max_length=240)
    punchline = models.CharField(max_length=400)
    format = models.CharField(max_length=20, default="text")
    creator = models.CharField(max_length=80)

    def __str__(self):
        return self.title


class Event(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(Participant, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    content = models.ForeignKey(Content, null=True, blank=True, on_delete=models.CASCADE)
    kind = models.CharField(max_length=12)
    occurred_at = models.DateTimeField(db_index=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    request_key = models.CharField(max_length=80, unique=True, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["subject", "occurred_at"])]

    def __str__(self):
        return f"{self.actor_id}: {self.kind} in {self.subject_id}"


class Membership(models.Model):
    actor = models.ForeignKey(Participant, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    state = models.CharField(max_length=8, choices=[("joined", "Joined"), ("left", "Left")])
    updated_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "subject"], name="lab_unique_membership")]

    def __str__(self):
        return f"{self.actor_id}: {self.state} {self.subject_id}"


class DemoState(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    simulated_at = models.DateTimeField(default=timezone.now)
    revision = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"Community demo revision {self.revision}"
