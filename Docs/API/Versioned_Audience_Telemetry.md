# Versioned audience telemetry

`POST /api/v1/telemetry/events` requires authentication. A batch contains at most
50 processed events. Only a currently consenting adult may contribute, and each
joke must be visible to that reader. There is no anonymous audience identifier.

```json
{
  "events": [{
    "schema_version": 2,
    "event_id": "7c9507c7-7173-47aa-9034-fa47c812246e",
    "session_id": "a01fbe32-1d50-4494-94fc-117a2bc5d88c",
    "platform": "web",
    "occurred_at": "2026-09-27T12:00:00Z",
    "joke": 123,
    "type": "dwell",
    "source": "feed",
    "value": 2400
  }]
}
```

The timestamp above is illustrative; send the actual occurrence time. All five
envelope fields are required for version 2. `platform` is `web` or `ios`.
`occurred_at` must include a timezone and fall within 24 hours before receipt or
five minutes afterward. Reuse the same event ID and unchanged envelope when
retrying. Session IDs are client-generated UUIDs, renewed when authentication or
analytics eligibility changes. They must not encode email, identity, device IDs,
URLs, or other personal attributes.

Event types remain `impression`, `reveal`, `dwell`, and `watch`. Dwell uses `value`
in milliseconds, optionally `scroll_pct`; watch uses `watch_ms`, optionally
`watch_pct`, and requires audio/video media. Durations below 500 ms are discarded;
durations above 600,000 ms are capped. Integer percentages are capped to 0–100;
missing or malformed percentages remain unknown. Allowed sources are the union
of the existing impression and view source enums. Unknown event types/sources are
rejected. Extra arbitrary properties are never stored. Client-supplied actor
identity is ignored; authenticated identity is authoritative.

`content_version` must be absent or null. Immutable publication versions are not
implemented, so the backend does not manufacture a version from current content.

The response is HTTP 202:

```json
{"accepted": 1, "duplicates": 0, "rejected": 0}
```

Counts cover the first 50 entries only. Accepted means a new event receipt and
its existing metric projection committed together. Uniqueness is per account
and event UUID. A repeated normalized payload increments `duplicates`; reusing an
ID with different normalized content increments `rejected`. Retried dwell/watch
events therefore cannot append duplicate duration samples. An impression still
contributes at most one daily user/joke projection even when distinct event IDs
describe repeated exposures. This is a receipt ledger, not a replacement for the
existing daily exposure definition.

## Legacy compatibility and metric meaning

Events without any version-envelope fields retain the prior API behavior. The
server records them as schema version 1, platform `legacy`, with a generated
receipt UUID and unknown session/occurrence time. Legacy dwell/watch retries
cannot be deduplicated reliably. Unknown schema versions and partial version-2
envelopes are rejected rather than silently downgraded.

Existing dashboard projections use **server receipt dates**. The ledger retains
client occurrence separately for future analysis. Existing operational opens,
reactions, saves, shares, and follows do not yet have this versioned contract.
Session UUIDs alone do not establish complete sessions, unique attention, or
completion rates. Versioned transport alone does not establish iOS event coverage.

## Consent provenance

Preferences and ingestion lock the same profile row. The preferences API accepts
strict JSON booleans for privacy fields and appends actual analytics preference
transitions. A previously existing preference is recorded with provenance
`legacy_observed` when first encountered; its record time is not the time the
person originally opted in. Subsequent API transitions use `preference`.

Every stored event references the preference record observed while processing
the request and carries `adult_opt_in_at_receipt`. The policy version identifies
the server collection policy; it does not prove which disclosure a legacy client
displayed. This establishes **receipt-time eligibility**, not event-time consent.
Withdrawal stops new collection and excludes the account from creator aggregate
queries on the next request. Previously retained events remain in the person's
account export until retention or account deletion removes them.

## Retention and account lifecycle

Optional event receipts, impressions, dwell, and watch samples have a 90-day
analysis window. Expired samples are excluded immediately from creator
queries, even if physical deletion is catching up. The account export includes
all physically retained own rows, including expired rows awaiting cleanup, and
marks this explicitly with `pending_cleanup_included`. Consent
history remains for the account lifetime. Operational `JokeView` reading history
and surviving engagement edges have separate purposes and are not deleted by
this analytics cleanup.

An authenticated ingestion request can trigger one bounded cleanup opportunity
per hour through the shared database cache. Each opportunity deletes at most 500
expired rows across the four tables, sharing the budget so one backlog cannot
starve another. There are no workers or scheduled jobs. On an idle site, or to
clear a backlog, an operator must invoke:

```sh
python manage.py purge_analytics --batch-size 500
```

The maximum explicit batch is 5,000; each invocation remains bounded. This is
not a guarantee of deletion at exactly day 90. Repeat bounded invocations until
the command reports zero remaining deletions, using the intended deployment's
normal management-command environment.

The existing account ZIP export now includes `audience_events`,
`analytics_consent`, `impressions`, `dwell_samples`, `watch_samples`, and retention
metadata, without other people's telemetry or joke text/media URLs in those
sections. Export responses use `private, no-store`. Account deletion cascades
through these records. Consent history and
event-time provenance are not retroactively reconstructed for older data.
