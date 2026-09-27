"""Private library operations and human-reviewed taxonomy changes."""
import hashlib
import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from creator_insights.models import (
    CreatorCollection,
    CreatorCollectionEntry,
    CreatorMetadataRequest,
    CreatorWorkspaceNote,
)
from creator_insights.services import resolve_creator_jokes
from jokes.models import ContextTag, Joke, Tone
from jokes.serving import allowed_tiers

UNAVAILABLE = 'One or more jokes are unavailable.'


class PendingRequestConflict(APIException):
    status_code = 409
    default_detail = 'One or more jokes already have a pending metadata request.'


def visible_creator_jokes(request):
    return resolve_creator_jokes(request.user).filter(content_tier__in=allowed_tiers(request))


def lock_owner(owner):
    # All per-owner creation bounds and bulk edits share this durable lock.
    return get_user_model().objects.select_for_update().get(pk=owner.pk)


def require_jokes(request, joke_ids, *, lock=False):
    queryset = Joke.objects.filter(pk__in=visible_creator_jokes(request).values('pk')).filter(pk__in=joke_ids)
    if lock:
        queryset = queryset.select_for_update()
    jokes = list(queryset.order_by('pk'))
    if len(jokes) != len(joke_ids):
        raise NotFound(UNAVAILABLE)
    if lock and visible_creator_jokes(request).filter(pk__in=joke_ids).count() != len(joke_ids):
        # A SELECT may have waited for a concurrent attribution/tier update.
        # Re-evaluate ownership after acquiring row locks, with a fresh
        # READ COMMITTED snapshot; a previously computed IN subquery is stale.
        raise NotFound(UNAVAILABLE)
    return jokes


@transaction.atomic
def save_note(request, joke_id, note):
    lock_owner(request.user)
    require_jokes(request, [joke_id], lock=True)
    result, _ = CreatorWorkspaceNote.objects.update_or_create(
        owner=request.user, joke_id=joke_id, defaults={'private_note': note},
    )
    return result


def delete_note(owner, joke_id):
    # Erasure must still work after takedown, a maturity preference change, or
    # reassignment. Only the caller's stored private note can be deleted.
    deleted, _ = CreatorWorkspaceNote.objects.filter(owner=owner, joke_id=joke_id).delete()
    if not deleted and not Joke.all_objects.filter(
        Q(creator=owner) | Q(creator__isnull=True, submission__user=owner, submission__status='published'),
        pk=joke_id,
    ).exists():
        raise NotFound(UNAVAILABLE)


def collection_row(collection, visible_items):
    all_ids = [entry.joke_id for entry in collection.entries.all()]
    ids = [joke_id for joke_id in all_ids if joke_id in visible_items]
    return {
        'id': collection.pk, 'name': collection.name, 'kind': collection.kind,
        'description': collection.description, 'joke_ids': ids,
        'items': [{'joke_id': joke_id, 'display_text': visible_items[joke_id]} for joke_id in ids],
        'unavailable_count': len(all_ids) - len(ids), 'updated_at': collection.updated_at,
    }


@transaction.atomic
def save_collection(request, data, collection_id=None):
    lock_owner(request.user)
    if collection_id is None:
        if CreatorCollection.objects.filter(owner=request.user).count() >= 100:
            raise ValidationError('At most 100 creator collections are supported.')
        collection = CreatorCollection(owner=request.user)
    else:
        try:
            collection = CreatorCollection.objects.select_for_update().get(pk=collection_id, owner=request.user)
        except CreatorCollection.DoesNotExist:
            raise NotFound('Collection not found.') from None
    if 'joke_ids' in data:
        require_jokes(request, data['joke_ids'], lock=True)
    for key in ['name', 'kind', 'description']:
        if key in data:
            setattr(collection, key, data[key])
    collection.save()
    if 'joke_ids' in data:
        collection.entries.all().delete()
        CreatorCollectionEntry.objects.bulk_create([
            CreatorCollectionEntry(collection=collection, joke_id=joke_id, position=position)
            for position, joke_id in enumerate(data['joke_ids'])
        ])
    return collection


def taxonomy_snapshot(joke):
    return {
        'themes': sorted(joke.context_tags.values_list('slug', flat=True)),
        'categories': sorted(joke.tones.values_list('slug', flat=True)),
        'culture_tags': sorted(joke.culture_tags.values_list('slug', flat=True)),
    }


def taxonomy_hash(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


@transaction.atomic
def create_metadata_requests(request, data):
    lock_owner(request.user)
    jokes = require_jokes(request, data['joke_ids'], lock=True)
    if CreatorMetadataRequest.objects.filter(
        owner=request.user, joke_id__in=data['joke_ids'], status=CreatorMetadataRequest.Status.PENDING,
    ).exists():
        raise PendingRequestConflict()
    changes = {key: sorted(data[key]) for key in ['themes', 'categories'] if key in data}
    created = []
    for joke in jokes:
        before = taxonomy_snapshot(joke)
        created.append(CreatorMetadataRequest.objects.create(
            owner=request.user, joke=joke, changes=changes, before_metadata=before,
            baseline_hash=taxonomy_hash(before), reason=data.get('reason', ''),
        ))
    return created


@transaction.atomic
def review_metadata_request(request, request_id, *, approve, reason=''):
    """Only a moderator can apply the exact immutable proposal, once.

    Before/after taxonomy captures describe this decision, not a complete
    publication-version history. No public text, media, attribution or age
    classifications are copied or changed by this service.
    """
    if not request.user.is_staff or not request.user.has_perm('creator_insights.change_creatormetadatarequest'):
        raise PermissionDenied('Moderator permission is required.')
    if len(reason) > 1000:
        raise ValidationError('Decision reasons are limited to 1000 characters.')
    review = CreatorMetadataRequest.objects.select_for_update().select_related('owner').get(pk=request_id)
    if review.status != CreatorMetadataRequest.Status.PENDING:
        return review
    joke = Joke.all_objects.select_for_update().get(pk=review.joke_id)
    rejection = '' if approve else (reason or 'A moderator declined this metadata request.')
    if approve:
        if not resolve_creator_jokes(review.owner).filter(pk=joke.pk).exists():
            rejection = 'The joke is unavailable or no longer belongs to the requester.'
        elif taxonomy_hash(taxonomy_snapshot(joke)) != review.baseline_hash:
            rejection = 'Metadata changed after this request. Submit a new request against the current version.'
        else:
            resolved = {}
            for key, model in [('themes', ContextTag), ('categories', Tone)]:
                if key in review.changes:
                    values = review.changes[key]
                    resolved[key] = list(model.objects.filter(slug__in=values))
                    if len(resolved[key]) != len(values):
                        rejection = 'A requested tag is no longer available. Submit a new request.'
            if not rejection:
                if 'themes' in resolved:
                    joke.context_tags.set(resolved['themes'])
                if 'categories' in resolved:
                    joke.tones.set(resolved['categories'])
                Joke.objects.filter(pk=joke.pk).update(updated_at=timezone.now())
                review.after_metadata = taxonomy_snapshot(joke)
    review.status = CreatorMetadataRequest.Status.APPROVED if approve and not rejection else CreatorMetadataRequest.Status.REJECTED
    review.decision_reason = rejection if review.status == CreatorMetadataRequest.Status.REJECTED else ''
    review.reviewed_at = timezone.now()
    review.reviewed_by = request.user
    review.save(update_fields=['status', 'decision_reason', 'reviewed_at', 'reviewed_by', 'after_metadata'])
    from audit.services import record_audit
    record_audit(
        request, 'creator_metadata_review', actor=request.user, target_type='creator_metadata_request',
        target_id=str(review.pk), outcome=review.status, metadata={'joke_id': joke.pk},
    )
    return review


def export_creator_library(user):
    """All caller-owned private records, without paid or public-content gates."""
    return {
        'notes': list(CreatorWorkspaceNote.objects.filter(owner=user).values('joke_id', 'private_note', 'created_at', 'updated_at')),
        'collections': [
            {
                'id': collection.pk, 'name': collection.name, 'kind': collection.kind,
                'description': collection.description,
                'joke_ids': [entry.joke_id for entry in collection.entries.all()],
                'created_at': collection.created_at, 'updated_at': collection.updated_at,
            }
            for collection in CreatorCollection.objects.filter(owner=user).prefetch_related('entries')
        ],
        'metadata_requests': list(CreatorMetadataRequest.objects.filter(owner=user).values(
            'id', 'joke_id', 'changes', 'before_metadata', 'after_metadata', 'reason', 'status',
            'decision_reason', 'created_at', 'reviewed_at',
        )),
    }
