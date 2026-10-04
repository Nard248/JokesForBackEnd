---
title: "Creator pivot checkpoint ledger"
category: research
created: 2026-09-27
updated: 2026-09-27
verified: 2026-09-27
tags: [creators, business-model, verification]
status: active
repo: all
---

# Creator pivot checkpoint ledger

Scope: free viewers; creator software for independent comedians and humor
creators; US business entity. All three repositories are on
`codex/creator-business-model`, with implementation checkpoints pushed and
matching upstream. Nothing was merged to main or deployed. The September 13
production checkpoint remains a dated observation, not a fresh production audit.

## Pushed checkpoints

| Repository | Commit | Checkpoint |
|---|---|---|
| Backend | `96226e6` | Code audits, sourced business research and creator-model design |
| Backend | `7d2260c` | Free readers, anonymous compatibility, unlimited mystery/history and retirement of new Supporter sales |
| Backend | `c78b997` | Consent-aware analytics, matched exposure metrics, audience suppression and impression uniqueness |
| Backend | `8c670ba` | Maturity settings enforced in creator insight previews |
| Backend | `3e4fe28` | Durable checkout attempts, historical prices, current-state Stripe reconciliation and default-off sales/tips gates |
| Backend | `bf0fdd3` | Owner content explorer, metadata checklist and bounded CSV export |
| Backend | `4f246eb` | Isolated creator E2E fixture and seed-command regressions |
| Backend | `d45c8da` | Reviewed continuation plan for creator library and measurement |
| Backend | `0971e90` | Private library, reviewed taxonomy changes, versioned telemetry, consent provenance, retention and export |
| Web | `067694a` | Free audience access and creator-only sales presentation |
| Web | `7d1e7f9` | Consent/account-bound telemetry, preference races and lifecycle/watch fixes |
| Web | `e5fd0ea` | Creator content workspace, honest metric labels and browser verification |
| Web | `cabce62` | Creator working library, account-bound requests, v2 telemetry and durable privacy |
| iOS | `08e389b` | Free reading, cached/widget compatibility and reader-copy changes |
| iOS | `e9baec8` | Native audience exposure/dwell/reveal, privacy controls and identity race corrections |

Pre-existing `.gitignore` edits, agent configuration, business documents and
images were excluded from these commits. iOS pre-existing `.gitignore` and
`.claude` work was also preserved. Another task committed Community Lab changes
on the same backend/web branches during this continuation; those commits were
preserved and are not attributed to this checkpoint.

## Verification

- Backend continuation full suite: **1,046 executed, 1,044 passed and two skipped**,
  121.290 seconds. Focused creator-library concurrency/moderation regressions and
  telemetry/consent/export regressions passed before the full run.
- Backend migration dry run: no changes detected. Ruff passed across changed
  Python files. Independent backend measurement review found no new defects.
- Web final continuation suite: **872 tests across 120 files passed** in 10.01
  seconds; production build passed; lint had **zero errors and 26 existing
  warnings**. The existing large-bundle build warning remains. Account-switching,
  stale refresh tokens, durable withdrawal and newly unavailable material have
  dedicated regressions. A final independent library review found no serious
  issues after the reported corrections.
- Real local browser/API final continuation tests: **5/5 passed** in 26.7 seconds:
  free creator upgrade state, paid workbench, notes/order/review, v2 receipt/retry/
  withdrawal, and declined-consent silence. Desktop/mobile screenshots were
  inspected after the shorter picker and mobile tab fitting refinements. No
  horizontal overflow was observed at 390px.
- iOS full simulator suite before review corrections: **165 passed, 20 skipped,
  zero failures**. After two review corrections, all unit tests reran with
  **158 passed, seven skipped, zero failures**. The full UI suite was not rerun
  after those final corrections. No physical-device pass is claimed.

Backend and browser verification used local PostgreSQL with production
`DATABASE_URL` disabled. Stripe regression tests used mocked transport with real
SDK object shapes and PostgreSQL concurrency checks. These are not evidence of
a signed checkout/webhook exercise against the intended merchant account.

## Payment activation

A September 27 read-only `Account.retrieve` with the configured **test** key
reported country `US`, `details_submitted=false`, `charges_enabled=false`, and
`payouts_enabled=false`. This does not verify live merchant readiness. No external
Stripe products, prices, subscriptions or payments were created. The owner still
needs to confirm that this is the intended account and complete onboarding.

**$15/month Creator Pro is a price experiment, not approved launch pricing.**
The existing seeded amount was retained. Publishing/basic analytics remain free;
paid capabilities include the content explorer, CSV export, private-library writes
and metadata-review requests. Previously saved private work remains readable
and erasable after cancellation. Annual billing,
Studio/team seats, AI usage charges, tips/payouts and social integrations remain
separate proposals. They must not be advertised as delivered benefits.

The branch defaults `CREATOR_CHECKOUT_ENABLED=false` and `TIPS_ENABLED=false`.
After deployment, pause sales with the creator checkout flag while retaining
the Stripe key and webhook secret for reconciliation and portal access. Follow
the [launch runbook](../STRIPE_GOLIVE.md) before enabling sales. This rollback
flag is a branch change, not a claim about currently deployed configuration.

Before rollout, inventory any existing Supporter subscribers and decide their
communicated cancellation/refund/migration treatment. Preserving records and
portal access does not stop recurring charges. No customers were contacted and
no subscriptions were canceled in this session; September 13's zero-user/revenue
snapshot must not be assumed current.

## Remaining work

The second checkpoint now implements v2 event/session IDs, server-receipt consent
provenance, bounded optional analytics retention, retained-data export, and native
impression/dwell/reveal collection. Existing opt-ins remain labeled legacy observed
state; no past consent or client occurrence-time eligibility is invented. The new
private library supports rehearsal notes, ordered series/set lists and reviewed
taxonomy edits without republishing duplicate jokes.

Still outstanding: immutable publication versions and reaction/follow transitions,
returning-audience cohorts, retention reporting, evidence-backed behavioral
recommendations, controlled experiments, richer creator workflows, native media
watch/completion, and live payment onboarding/validation. Native system share-sheet
occlusion is not explicitly observed; dwell means foreground viewport exposure.
Generic legacy API retry ownership needs a separate audit; the new privacy and
private-library requests bind their originating account and avoid shared retries.
Anonymous reading remains free without fingerprinted audience tracking. No complete
cross-platform audience coverage, statistical lift or creator earnings is claimed.

A separate dependency audit found **47 advisory entries across 8 packages,
covering 27 distinct advisory IDs**. This is an unresolved launch blocker; these
counts are not 47 unique vulnerabilities. Dependency remediation was not bundled
into this implementation. Pinned runtime packages include `cryptography==46.0.7`,
`djangorestframework==3.16.1` and `sqlparse==0.5.5`. Local audit evidence is
`/private/tmp/jokesfor-payment-pip-audit.json` (not committed; rerun the audit
before planning upgrades).

The knowledge base records the new decision and branch contracts. The older
production snapshot is retained unchanged. Vault preservation used scoped local
Markdown writes because the configured REST TLS connection failed verification;
TLS verification was not disabled.

## Second-checkpoint deployment notes

Apply backend migrations `jokes.0038_versioned_audience_events` and
`creator_insights.0001_initial` before releasing the new clients. Verify v2
receipts and consent behavior in the target environment, and assign an operator
for retention backlog cleanup. These local migration tests do not show that
production migrations have run. Keep creator checkout and tips disabled until
the existing launch runbook is satisfied.

The web library is at `/create/library`, linked from the creator hub, workbench
and insights. Private writes use captured account tokens without automatic replay;
an expired token can require signing in again. The iOS privacy setting is under
You → Audience privacy. The public privacy-policy draft was updated to describe
the actual collection/retention model; its existing counsel-review status remains.

## Related

- [Session record](2026-09-27-creator-pivot-session.md)
- [Design](../superpowers/specs/2026-09-27-creator-business-model-design.md)
- [Business research](../Business%20Docs/2026-09-27-creator-business-research.md)
- [Backend audit](2026-09-27-backend-creator-audit.md)
- [Client audit](2026-09-27-client-creator-audit.md)
- [Measurement roadmap](2026-09-27-creator-measurement-roadmap.md)
- [Creator workbench API](../API/Creator_Content_Workbench.md)
- [Creator library API](../API/Creator_Library.md)
- [Versioned audience telemetry](../API/Versioned_Audience_Telemetry.md)
- [Stripe launch runbook](../STRIPE_GOLIVE.md)
