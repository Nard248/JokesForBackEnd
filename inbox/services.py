"""Notification creation — call synchronously from the event site. No workers."""
from inbox.models import Notification


def notify(recipient, verb, actor=None, joke=None):
    """Create a notification for `recipient`. No-op when the recipient is the
    actor (don't notify yourself) or recipient is missing."""
    if recipient is None:
        return None
    if actor is not None and getattr(actor, 'pk', None) == recipient.pk:
        return None
    return Notification.objects.create(recipient=recipient, actor=actor, verb=verb, joke=joke)
