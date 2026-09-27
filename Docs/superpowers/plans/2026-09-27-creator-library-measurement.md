# Creator library and measurement continuation

The owner asked to continue the free-audience/paid-creator roadmap, retaining
checkpoint commits and parallel implementation. This checkpoint makes the
library actionable and records reliable, versioned audience observations.

## Scope and constraints

Use the existing Django/PostgreSQL API, React creator workspace and SwiftUI
reader. Keep the single request-driven service. Preserve free viewing, content
tiers, consent, moderation and ownership. Do not touch the unrelated Community
Lab work, deploy main, create Stripe resources or enable sales.

Versioned observations are not immutable publication versions. The new event
contract records an explicitly unknown content version until the content delivery
and publishing paths can supply a verified version. Existing metrics continue
using their documented receipt-time and operational-history semantics.

## Checkpoint 1: event identity and consent provenance

- [x] Add a per-event version-2 envelope on the existing telemetry route:
  `schema_version=2`, UUID `event_id` and `session_id`, `platform=web|ios`,
  timezone-aware `occurred_at`, plus existing joke/type/source/measurement fields.
- [x] Accept occurrence timestamps only from the last 24 hours through five
  minutes ahead. Reject malformed modern envelopes, including partial envelopes;
  never silently treat them as legacy events.
- [x] Atomically record a normalized event and project existing metrics. Enforce
  uniqueness on user/event ID. Matching retries do not count twice; conflicting
  retries are rejected. Actor and receipt timestamp are server-controlled.
- [x] Record real account-preference transitions under the same profile lock as
  ingestion. Label previously existing opt-ins as observed state, not historical
  consent evidence. Strictly validate privacy booleans.
- [x] Export retained telemetry and consent history through the existing account
  export. Cover account-deletion cascades. Bound retention cleanup for analytics
  ledger, impressions, dwell and watch; retain operational reading history.
- [x] Keep old clients compatible. Document both the legacy and versioned paths.
- [x] Verify duplicate/concurrent delivery, malformed payloads, clock bounds,
  consent changes, minors, removed/blocked content, retention and data export.

## Checkpoint 2: native and web collection

- [x] Web attaches event IDs at capture, session IDs within an eligible account
  session, platform and capture time. Identity/consent changes clear queued data
  and rotate sessions. A token refresh alone does not change the session.
- [x] iOS exposes account audience-consent controls, reads adult DOB, and binds
  transport to the originating authentication session. A failed opt-out keeps
  local collection stopped until a successful explicit opt-in.
- [x] iOS records impressions only after at least 50% visibility for one second,
  matching web; dwell measures visible foreground intervals and actual reveal
  actions are separate events. Background flushing is best-effort.
- [x] Keep queues bounded and memory-only. Native media-watch measurement remains
  separate until the player lifecycle supports honest playback observation.
- [x] Test capture time/session rotation, consent/account switches, stale network
  completions, foreground visibility, and the existing reader flows.

## Checkpoint 3: private creator library and reviewed metadata

- [x] Add owner-scoped private notes, series and ordered set lists. Notes are
  limited to 5,000 characters; collections to 100 per creator and 100 jokes each.
  Name/description limits are 100/1,000 characters.
- [x] Read/delete private work remains available after subscription cancellation;
  writes use the existing creator-content entitlement. User data export remains
  independent of payment. Private notes never enter public joke serializers.
- [x] Add a theme/category change request for 1–50 owned jokes. Omitted fields
  remain unchanged; an empty array explicitly clears the field. Reject unknown
  fields, foreign IDs and inaccessible content atomically.
- [x] Review requests in Django admin. Approval locks records, verifies ownership
  and current availability, and rejects stale taxonomy baselines. It changes
  taxonomy only and records an audit entry. It cannot publish a new joke, change
  safety labels, expose private notes, or bypass moderation.
- [x] Web adds a private-library page and per-joke note editor, collection ordering
  and metadata-review form/history. Connect it to the existing creator navigation.
  Prevent accidental replacement of unavailable collection members.
- [x] Test ownership, paid/canceled boundaries, collection order/concurrency,
  private-data isolation, admin permissions, stale reviews, erasure and export.

## API contract

All creator routes are beneath `/api/v1/creators/me/`:

| Route | Purpose |
|---|---|
| `content/{id}/workspace/` GET/PATCH/DELETE | Own private note |
| `content/workspace-notes/` GET | Find existing accessible private notes |
| `collections/` GET/POST | Paginated private series/set lists |
| `collections/{id}/` GET/PATCH/DELETE | Collection metadata and ordered joke IDs |
| `content/metadata-requests/` GET/POST | Own request history and bounded batch request |

Collections return `unavailable_count` alongside visible ordered `joke_ids`.
Private responses use `Cache-Control: private, no-store`. Public text editing,
AI enrichment, teams, social integrations and full publication versioning are
not implied by these endpoints.

## Integration and release evidence

- [x] Run focused regressions before broad suites; inspect actual failures.
- [x] Review code across ownership boundaries, especially privacy and admin paths.
- [x] Run full backend/web suites, migration consistency, changed-file lint and
  production web build; run the native simulator suite.
- [x] Exercise notes, ordering and metadata review against the real local API.
- [x] Commit/push each verified checkpoint on `codex/creator-business-model`.
- [x] Update the checkpoint ledger and durable business/technical notes with
  implemented behavior, actual evidence and remaining coverage limits.

Tests must explicitly clear `DATABASE_URL`, use isolated local PostgreSQL, and
disable external services. No production migration or payment activation is part
of this work.

## Completion evidence

Backend checkpoint `0971e90`, web `cabce62`, native `e9baec8`; all are on
`codex/creator-business-model`. The full backend suite executed 1,046 tests with
two skips and no failures. The final web suite passed 872 tests; five real local
browser/API tests passed. Native full-suite and post-review unit evidence is
qualified in the checkpoint ledger rather than presented as one final full run.

Review also corrected delayed native authentication completions, native report
sheet measurement, cross-account web preference/private-library transport,
durable web withdrawal and stale editor visibility. No production deployment or
Stripe activation occurred. See the [checkpoint ledger](../../Research/2026-09-27-creator-pivot-status.md)
for exact verification, limits and next work.
