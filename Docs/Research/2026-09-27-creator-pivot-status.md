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
| Web | `067694a` | Free audience access and creator-only sales presentation |
| Web | `7d1e7f9` | Consent/account-bound telemetry, preference races and lifecycle/watch fixes |
| Web | `e5fd0ea` | Creator content workspace, honest metric labels and browser verification |
| iOS | `08e389b` | Free reading, cached/widget compatibility and reader-copy changes |

Pre-existing `.gitignore` edits, agent configuration, business documents and
images were excluded from these commits. iOS pre-existing `.gitignore` and
`.claude` work was also preserved.

## Verification

- Backend full suite: **988 tests OK, one skipped**, 120.423 seconds. Six seed
  command tests added after that discovery passed separately; 994 tests were
  subsequently discovered, but a 994-test full-suite run is **not** claimed.
- Backend migration dry run: no model changes missing migrations. Ruff passed
  across changed Python files. Workbench coverage includes ownership, consent,
  paid/canceled access, maturity, UTC windows, export bounds and formula safety.
- Web: **825 tests across 114 files passed**; production build passed; lint had
  **zero errors and 26 existing warnings**. The final UI copy check passed its
  nine relevant tests.
- Real local browser/API tests: **4/4 free-viewing tests passed** in 14.5 seconds
  and **2/2 paid-workbench tests passed** in 8.2 seconds. Desktop/mobile screenshots
  were inspected; the workspace was legible with no horizontal overflow.
- iOS simulator: **150 passed, 20 skipped, zero failures**. No physical-device
  pass or native audience-telemetry completeness is claimed.

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
paid capabilities are the content explorer and CSV export. Annual billing,
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

Native iOS rich audience telemetry is not implemented. Anonymous reading remains
free without fingerprinted audience tracking. Current adult consent determines
creator metric inclusion; raw history does not encode event-time consent
provenance. Immutable publication versions, session/event IDs, retention policies,
complete account export, follow/unfollow history, retention cohorts and controlled
experiments require further work in the measurement roadmap. No claim of complete
cross-platform audience coverage, statistical lift or creator earnings is made.

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

## Related

- [Session record](2026-09-27-creator-pivot-session.md)
- [Design](../superpowers/specs/2026-09-27-creator-business-model-design.md)
- [Business research](../Business%20Docs/2026-09-27-creator-business-research.md)
- [Backend audit](2026-09-27-backend-creator-audit.md)
- [Client audit](2026-09-27-client-creator-audit.md)
- [Measurement roadmap](2026-09-27-creator-measurement-roadmap.md)
- [Creator workbench API](../API/Creator_Content_Workbench.md)
- [Stripe launch runbook](../STRIPE_GOLIVE.md)
