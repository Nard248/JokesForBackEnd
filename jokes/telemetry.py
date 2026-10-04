"""Versioned, optional audience measurement; no background worker required."""
import hashlib
import json
import uuid
from datetime import UTC, timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from jokes.models import (
    AnalyticsConsentRecord,
    AudienceEvent,
    Joke,
    JokeDwell,
    JokeImpression,
    JokeMedia,
    JokeView,
    JokeWatch,
    UserProfile,
)
from jokes.moderation import visible_jokes
from jokes.serving import allowed_tiers

POLICY_VERSION = 'creator-analytics-2026-09-27'
RETENTION_DAYS = 90
RETENTION_BATCH = 500
MAX_BATCH = 50
ENVELOPE_FIELDS = frozenset({
    'schema_version', 'event_id', 'session_id', 'platform', 'occurred_at', 'content_version',
})
SOURCES = set(dict(JokeImpression.SOURCE_CHOICES)) | set(dict(JokeView.SOURCE_CHOICES))


def observe_consent(profile):
    """Call under the profile row lock; do not invent earlier consent evidence."""
    latest = AnalyticsConsentRecord.objects.filter(user_id=profile.user_id).order_by('-pk').first()
    if latest is None or latest.enabled != profile.share_analytics:
        latest = AnalyticsConsentRecord.objects.create(
            user_id=profile.user_id, enabled=profile.share_analytics,
            policy_version=POLICY_VERSION, provenance='legacy_observed',
        )
    return latest


def change_analytics_consent(profile, enabled):
    """Record an explicit transition under the same lock used by ingestion."""
    observe_consent(profile)
    if profile.share_analytics != enabled:
        AnalyticsConsentRecord.objects.create(
            user_id=profile.user_id, enabled=enabled,
            policy_version=POLICY_VERSION, provenance='preference',
        )
        profile.share_analytics = enabled


def _normalize(event, now):
    if not isinstance(event, dict):
        return None
    joke_id = event.get('joke')
    source = event.get('source', 'other')
    event_type = event.get('type')
    if (type(joke_id) is not int or not 0 < joke_id <= 9223372036854775807
            or event_type not in ('impression', 'reveal', 'dwell', 'watch')
            or not isinstance(source, str) or source not in SOURCES):
        return None
    normalized = {
        'joke_id': joke_id, 'event_type': event_type, 'source': source,
        'schema_version': 1, 'session_id': None, 'platform': 'legacy',
        'occurred_at': None, 'content_version': None,
        'duration_ms': None, 'percentage': None,
    }
    if ENVELOPE_FIELDS.intersection(event):
        if type(event.get('schema_version')) is not int or event['schema_version'] != 2:
            return None
        if event.get('platform') not in ('web', 'ios') or event.get('content_version') is not None:
            return None
        try:
            if not all(isinstance(event.get(key), str) for key in ('event_id', 'session_id', 'occurred_at')):
                return None
            event_id = uuid.UUID(event['event_id'])
            session_id = uuid.UUID(event['session_id'])
            occurred_at = parse_datetime(event['occurred_at'])
        except (ValueError, TypeError, OverflowError):
            return None
        if (occurred_at is None or timezone.is_naive(occurred_at)
                or occurred_at < now - timedelta(hours=24)
                or occurred_at > now + timedelta(minutes=5)):
            return None
        normalized.update(
            schema_version=2, session_id=session_id, platform=event['platform'],
            occurred_at=occurred_at,
        )
    else:
        event_id = uuid.uuid4()
    if event_type in ('dwell', 'watch'):
        duration = event.get('value' if event_type == 'dwell' else 'watch_ms')
        if type(duration) is not int or duration < 500:
            return None
        normalized['duration_ms'] = min(duration, 600000)
        percentage = event.get('scroll_pct' if event_type == 'dwell' else 'watch_pct')
        if type(percentage) is int:
            normalized['percentage'] = max(0, min(percentage, 100))
    # Hash only normalized, allowlisted fields. Untrusted email/IP/freeform
    # properties and client-selected actors are never persisted.
    fingerprint_data = {
        **normalized,
        'occurred_at': (
            normalized['occurred_at'].astimezone(UTC).isoformat()
            if normalized['occurred_at'] else None
        ),
    }
    fingerprint = hashlib.sha256(json.dumps(
        fingerprint_data, sort_keys=True, separators=(',', ':'), default=str,
    ).encode()).hexdigest()
    return {**normalized, 'event_id': event_id, 'payload_fingerprint': fingerprint}


def _project(event, user, today):
    """Keep existing dashboards compatible; projection dates mean receipt date."""
    common = {'user': user, 'joke_id': event['joke_id'], 'source': event['source']}
    kind = event['event_type']
    if kind == 'dwell':
        JokeDwell.objects.create(**common, dwell_ms=event['duration_ms'],
                                 scroll_pct=event['percentage'], created_date=today)
    elif kind == 'watch':
        JokeWatch.objects.create(**common, watch_ms=event['duration_ms'], watch_pct=event['percentage'])
    elif kind == 'impression':
        JokeImpression.objects.get_or_create(
            user=user, joke_id=event['joke_id'], created_date=today,
            defaults={'source': event['source']},
        )
    else:
        view = JokeView.objects.filter(
            user=user, joke_id=event['joke_id'], viewed_date=today,
        ).order_by('-viewed_at').first()
        if view is None:
            JokeView.objects.create(**common, viewed_date=today, revealed_punchline=True)
        elif not view.revealed_punchline:
            view.revealed_punchline = True
            view.save(update_fields=['revealed_punchline'])


def ingest_events(request):
    maybe_purge_expired_analytics()
    payload = request.data if isinstance(request.data, dict) else {}
    events = payload.get('events')
    events = events[:MAX_BATCH] if isinstance(events, list) else []
    result = {'accepted': 0, 'duplicates': 0, 'rejected': 0}
    now = timezone.now()
    with transaction.atomic():
        profile = UserProfile.objects.select_for_update().get(user=request.user)
        if not profile.share_analytics or not profile.is_adult:
            result['rejected'] = len(events)
            return result
        consent = observe_consent(profile)
        normalized = [_normalize(event, now) for event in events]
        result['rejected'] = sum(event is None for event in normalized)
        normalized = [event for event in normalized if event is not None]
        visible_ids = set(visible_jokes(Joke.objects.filter(
            pk__in={event['joke_id'] for event in normalized},
            content_tier__in=allowed_tiers(request),
        ), request).values_list('pk', flat=True))
        media_ids = set(JokeMedia.objects.filter(
            joke_id__in=visible_ids, asset__kind__in=('audio', 'video'),
        ).values_list('joke_id', flat=True))
        for event in normalized:
            if (event['joke_id'] not in visible_ids
                    or (event['event_type'] == 'watch' and event['joke_id'] not in media_ids)):
                result['rejected'] += 1
                continue
            existing = AudienceEvent.objects.filter(user=request.user, event_id=event['event_id']).first()
            if existing:
                result['duplicates' if existing.payload_fingerprint == event['payload_fingerprint']
                       else 'rejected'] += 1
                continue
            AudienceEvent.objects.create(
                user=request.user, consent=consent, received_at=now, **event,
            )
            _project(event, request.user, now.date())
            result['accepted'] += 1
    return result


def purge_expired_analytics(*, batch_size=RETENTION_BATCH, now=None):
    """Delete at most batch_size expired raw rows, excluding reading history.

    Consent history remains until account deletion. This is bounded physical
    cleanup, not an exact deletion deadline: idle sites require an operator to
    invoke the management command. Account exports include pending cleanup rows.
    """
    if type(batch_size) is not int or not 1 <= batch_size <= 5000:
        raise ValueError('batch_size must be between 1 and 5000')
    cutoff = (now or timezone.now()) - timedelta(days=RETENTION_DAYS)
    remaining = batch_size
    deleted = {}
    models = (
        (AudienceEvent, 'received_at'), (JokeImpression, 'created_at'),
        (JokeDwell, 'created_at'), (JokeWatch, 'watched_at'),
    )
    for index, (model, date_field) in enumerate(models):
        # Share each opportunity across tables so a large ledger backlog cannot
        # indefinitely starve cleanup of playback/impression projections.
        allowance = max(1, remaining // (len(models) - index)) if remaining else 0
        ids = list(model.objects.filter(**{f'{date_field}__lt': cutoff})
                   .order_by(date_field, 'pk').values_list('pk', flat=True)[:allowance]) if allowance else []
        count, _ = model.objects.filter(pk__in=ids).delete() if ids else (0, {})
        deleted[model._meta.model_name] = count
        remaining -= count
    return deleted


def maybe_purge_expired_analytics():
    # DatabaseCache is shared across instances. The expiring add is an
    # opportunity throttle, not a correctness lock; concurrent cleanup is safe.
    if cache.add('analytics-retention-v1', True, timeout=3600):
        purge_expired_analytics()


def export_analytics(user):
    """All physically retained own telemetry, including pending cleanup rows."""
    cutoff = timezone.now() - timedelta(days=RETENTION_DAYS)
    return {
        'analytics_retention': {
            'raw_window_days': RETENTION_DAYS, 'cutoff': cutoff,
            'pending_cleanup_included': True,
            'eligibility': 'Consent and adult eligibility are observed at server receipt, not client occurrence.',
        },
        'audience_events': list(AudienceEvent.objects.filter(user=user).values(
            'event_id', 'schema_version', 'session_id', 'platform', 'joke_id', 'event_type',
            'source', 'occurred_at', 'received_at', 'content_version', 'duration_ms', 'percentage',
            'eligibility', 'consent_id',
        )),
        'analytics_consent': list(AnalyticsConsentRecord.objects.filter(user=user).values(
            'id', 'enabled', 'policy_version', 'provenance', 'recorded_at',
        )),
        'impressions': list(JokeImpression.objects.filter(user=user).values(
            'joke_id', 'source', 'created_at', 'created_date',
        )),
        'dwell_samples': list(JokeDwell.objects.filter(user=user).values(
            'joke_id', 'source', 'dwell_ms', 'scroll_pct', 'created_at', 'created_date',
        )),
        'watch_samples': list(JokeWatch.objects.filter(user=user).values(
            'joke_id', 'source', 'watch_ms', 'watch_pct', 'watched_at',
        )),
    }
