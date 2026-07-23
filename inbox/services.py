"""Notification creation — call synchronously from the event site. No workers."""
from inbox.models import Notification


def notify(recipient, verb, actor=None, joke=None, **extra):
    """Create a notification for `recipient`. No-op when the recipient is the
    actor (don't notify yourself) or recipient is missing. Any extra kwargs
    become the verb-specific `data` payload (must be JSON-serializable)."""
    if recipient is None:
        return None
    if actor is not None and getattr(actor, 'pk', None) == recipient.pk:
        return None
    return Notification.objects.create(
        recipient=recipient, actor=actor, verb=verb, joke=joke, data=extra,
    )
