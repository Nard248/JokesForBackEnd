"""Keep communities in step with the catalog and the engagement ledger.

Engagement writes and consent changes invalidate the cached aggregate, so a
community that crosses its threshold shows up on the next read.
"""
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from communities import services
from communities.models import Community
from communities.styles import style_for
from jokes.models import ContextTag, Favorite, JokeReaction, SavedJoke, ShareEvent, UserProfile


@receiver(post_save, sender=ContextTag)
def ensure_community(sender, instance, created, raw=False, **kwargs):
    if raw or not created:
        return
    emoji, color = style_for(instance.slug)
    Community.objects.get_or_create(tag=instance, defaults={'emoji': emoji, 'color': color})


def _invalidate(sender, instance=None, raw=False, **kwargs):
    if raw:
        return
    if sender is ShareEvent and instance is not None and instance.user_id is None:
        return  # anonymous shares never count toward communities
    # After commit: a read racing a consent withdrawal must not cache the old state.
    transaction.on_commit(services.invalidate)


for _model in (JokeReaction, Favorite, SavedJoke, ShareEvent, UserProfile):
    post_save.connect(_invalidate, sender=_model, dispatch_uid=f'communities-invalidate-save-{_model.__name__}')
    post_delete.connect(_invalidate, sender=_model, dispatch_uid=f'communities-invalidate-del-{_model.__name__}')
