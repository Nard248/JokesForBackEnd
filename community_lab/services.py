"""Small, atomic synthetic event mutations; never use real user identity."""
import random
import re
from datetime import timedelta

from community_lab.engine import affinities
from community_lab.models import Content, Event, Membership, Participant, Subject
from community_lab.snapshot import VIEWER_ID


class InputError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def require_subject(value):
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value)
            or not Subject.objects.filter(pk=value).exists()):
        raise InputError("Choose an existing community subject.")
    return value


def integer(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise InputError(f"{name} must be an integer between 1 and {maximum}.")
    return value


def cascade(state, content, sender_id, request_key=None):
    """Three independently reacting synthetic friends, each discovering two jokes."""
    sender = Event.objects.create(actor_id=sender_id, subject_id=content.subject_id,
        content=content, kind="share", occurred_at=state.simulated_at, request_key=request_key)
    events = list(Event.objects.filter(subject_id=content.subject_id).values(
        "actor_id", "subject_id", "content_id", "kind", "occurred_at"))
    overrides = list(Membership.objects.filter(subject_id=content.subject_id).values("actor_id", "subject_id", "state"))
    scores = affinities(events, state.simulated_at, overrides)
    candidates = list(Participant.objects.exclude(pk__in=[sender_id, VIEWER_ID]).order_by("id").values_list("id", flat=True))
    # Rotate selections across repeated batches; prefer people yet to engage.
    rng = random.Random(f"{state.revision}:{content.id}:{Event.objects.count()}")
    rng.shuffle(candidates)
    candidates.sort(key=lambda person: scores.get((person, content.subject_id), {}).get("inferred", False))
    companion = Content.objects.filter(subject_id=content.subject_id).exclude(pk=content.pk).order_by("id").first()
    reactions = []
    for person in candidates[:3]:
        for kind, item in (("view", content), ("like", content), ("save", companion)):
            if item is not None:
                reactions.append(Event(actor_id=person, subject_id=content.subject_id, content=item, kind=kind,
                    occurred_at=state.simulated_at, parent=sender))
    Event.objects.bulk_create(reactions)
    return sender


def share(state, data):
    if set(data) != {"content_id", "event_id"}:
        raise InputError("Provide content_id and event_id only.")
    key = data["event_id"]
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key):
        raise InputError("event_id must contain 1–80 letters, digits, dashes or underscores.")
    if not isinstance(data["content_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", data["content_id"]):
        raise InputError("content_id must identify a demo joke.")
    content = Content.objects.filter(pk=data["content_id"]).first()
    if content is None:
        raise InputError("Choose an existing demo joke.")
    existing = Event.objects.filter(request_key=key).first()
    if existing:
        if existing.content_id != content.id:
            raise InputError("This event_id was already used for a different joke.", 409)
        return False
    cascade(state, content, VIEWER_ID, key)
    return True


def simulate(state, data):
    if set(data) - {"subject_id", "steps"}:
        raise InputError("Provide only subject_id and steps.")
    steps = integer(data.get("steps", 1), "steps", 100)
    subject_id = require_subject(data["subject_id"]) if "subject_id" in data else None
    contents = list(Content.objects.filter(**({"subject_id": subject_id} if subject_id else {})).order_by("id"))
    actors = list(Participant.objects.exclude(pk=VIEWER_ID).order_by("id").values_list("id", flat=True))
    if not contents or not actors:
        raise InputError("Seed the demo before simulating.")
    rng = random.Random(state.revision)
    for _ in range(steps):
        state.simulated_at += timedelta(minutes=1)
        cascade(state, rng.choice(contents), rng.choice(actors))
    return True


def membership(state, data):
    if set(data) != {"subject_id", "action"}:
        raise InputError("Provide subject_id and action only.")
    subject_id = require_subject(data["subject_id"])
    action = data["action"]
    if action not in ("join", "leave"):
        raise InputError("action must be join or leave.")
    desired = "joined" if action == "join" else "left"
    existing = Membership.objects.filter(actor_id=VIEWER_ID, subject_id=subject_id).first()
    if existing and existing.state == desired:
        return False
    # Distinct timestamps preserve join/leave ordering when reconstructing history.
    state.simulated_at += timedelta(microseconds=1)
    Membership.objects.update_or_create(actor_id=VIEWER_ID, subject_id=subject_id,
        defaults={"state": desired, "updated_at": state.simulated_at})
    Event.objects.create(actor_id=VIEWER_ID, subject_id=subject_id, kind=action, occurred_at=state.simulated_at)
    return True


def advance(state, data):
    if set(data) != {"days"}:
        raise InputError("Provide days only.")
    state.simulated_at += timedelta(days=integer(data["days"], "days", 30))
    return True
