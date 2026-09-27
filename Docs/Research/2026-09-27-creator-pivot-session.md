---
title: "Session: creator business model pivot"
category: session
created: 2026-09-27
updated: 2026-09-27
verified: 2026-09-27
tags: [session, creators, business, billing]
status: complete
repo: all
---

# Creator business model session

The owner confirmed free viewing, creator tools as the primary monetization
channel, a US receiving entity and independent comedians/humor creators as the
first paying segment. Research recommends testing $15/month Creator Pro on the
web; that remains a hypothesis, not approved launch pricing.

## Delivered

Backend, web and iOS checkpoints remove reader subscription allowances while
preserving age/moderation restrictions and legacy subscription management.
The existing creator-insights service now enforces current adult consent,
excludes creator self-activity, matches exposure/open populations, suppresses
small audience groups and explains measurement limits. Web telemetry is bound
to the active account and consent, including lifecycle and playback corrections.

The initial paid toolkit adds an owner content explorer, format/language/theme/
category filters, UTC activity windows, metadata recommendations and bounded CSV
export. Basic publishing and insights remain free. Payment work adds durable
checkout identities, historical price mapping, current Stripe state reconciliation,
separate default-off creator-sales/tips gates and a read-only readiness command.

All implementation checkpoints are pushed on `codex/creator-business-model` in
the three repositories. Nothing was merged or deployed. Commit IDs and exact
test results are in the [checkpoint ledger](2026-09-27-creator-pivot-status.md).
Pre-existing unrelated changes were preserved. Local tests explicitly disabled
the production database URL; no live payment resources were created.

## Next work

Confirm the intended Stripe account and complete onboarding, catalog/portal setup,
signed test flows and customer-facing legal/tax decisions before enabling sales.
The configured test-key account is US with incomplete details and disabled
charges/payouts. Validate creator willingness to pay. Inventory any current
Supporter subscribers and define communicated cancellation/refund/migration
handling before rollout: retained records do not stop their recurring charges.
No customers were contacted or subscriptions canceled. Address the separate
dependency launch blocker recorded in the ledger.

The toolkit is an initial foundation. Rich iOS telemetry, versioned events and
publications, consent provenance, retention and account-export coverage, cohorts
and controlled comparisons remain data work. AI enrichment, teams, external
social integrations and creator payouts are not implemented. See the
[measurement roadmap](2026-09-27-creator-measurement-roadmap.md).

## Durable preservation

The source-of-truth vault records this work at
`JokesFor/Sessions/2026-09-27-creator-business-model-session.md` and the accepted
direction at `JokesFor/Decisions/2026-09-27-free-audience-creator-tools.md`.
Existing business, creator, billing, telemetry and launch notes distinguish
branch changes from the unchanged September 13 production snapshot. The old
reader-paywall decision is archived as superseded, not described as removed
from production. Both repository memory indices link to the new session.

## Related

- [Checkpoint ledger](2026-09-27-creator-pivot-status.md)
- [Business research](../Business%20Docs/2026-09-27-creator-business-research.md)
- [Design](../superpowers/specs/2026-09-27-creator-business-model-design.md)
- [Creator workbench API](../API/Creator_Content_Workbench.md)
- [Stripe launch runbook](../STRIPE_GOLIVE.md)
