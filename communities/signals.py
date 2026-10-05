"""Keep communities in step with the catalog and the engagement ledger.

Engagement writes update the materialized signal table synchronously, in the
same transaction (``materialize.py``), and — like consent changes and re-tags —
invalidate the cached aggregate after commit, so a community that crosses its
threshold shows up on the next read.
"""
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from communities import materialize, services
from communities.models import Community
from communities.styles import style_for
from jokes.models import ContextTag, Joke, ShareEvent, UserProfile


@receiver(post_save, sender=ContextTag)
def ensure_community(sender, instance, created, raw=False, **kwargs):
    if raw or not created:
        return
    emoji, color = style_for(instance.slug)
    Community.objects.get_or_create(tag=instance, defaults={'emoji': emoji, 'color': color})


def _invalidate(sender, instance=None, raw=False, **kwargs):
    if raw:
        return
    # After commit: a read racing a consent withdrawal must not cache the old state.
    transaction.on_commit(services.invalidate)


def _engagement_saved(sender, instance, created=False, raw=False, **kwargs):
    if raw:
        return  # loaddata: run `manage.py rebuild_community_signals` afterwards
    if sender is ShareEvent and instance.user_id is None and created:
        return  # anonymous shares never count toward communities
    materialize.record(sender, instance, created=created)
    transaction.on_commit(services.invalidate)


def _engagement_deleted(sender, instance, **kwargs):
    if sender is ShareEvent and instance.user_id is None:
        return  # never mirrored
    materialize.discard(sender, instance)
    transaction.on_commit(services.invalidate)


def _themes_changed(sender, action, **kwargs):
    if action in ('post_add', 'post_remove', 'post_clear'):
        transaction.on_commit(services.invalidate)


for _model in materialize.SOURCES:
    post_save.connect(_engagement_saved, sender=_model, dispatch_uid=f'communities-signal-save-{_model.__name__}')
    post_delete.connect(_engagement_deleted, sender=_model, dispatch_uid=f'communities-signal-del-{_model.__name__}')
post_save.connect(_invalidate, sender=UserProfile, dispatch_uid='communities-invalidate-save-UserProfile')
post_delete.connect(_invalidate, sender=UserProfile, dispatch_uid='communities-invalidate-del-UserProfile')
m2m_changed.connect(_themes_changed, sender=Joke.context_tags.through, dispatch_uid='communities-joke-themes')
