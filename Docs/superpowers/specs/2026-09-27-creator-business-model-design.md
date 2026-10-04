# Creator business model: free audience, paid creator tools

Date: 2026-09-27. Owner decision: viewers do not need a subscription. The first
customer is an independent comedian or humor creator. The receiving business
entity is registered in the USA (confirmed in this session).

## Outcome and commercial boundary

JokesFor helps creators learn what lands, understand their consenting audience,
and decide what to publish next. Free discovery supplies the audience; recurring
creator software subscriptions supply the primary revenue. Buying creator tools
does not buy distribution, editorial approval, mature-content access, or a promise
of earnings. Reading, search, collections, and available joke history are free.
Account requirements, reasonable abuse throttles, moderation, and age restrictions
remain separate from billing.

Basic publishing, ownership, and existing creator insights remain free. The initial
paid offer is a single Creator Pro pilot; $15/month is a pricing hypothesis to
validate, not proven willingness to pay. Studio/team pricing, annual contracts,
AI consumption credits, payouts, and off-platform integrations follow only when
their costs and customer demand are measured. Do not silently migrate or cancel
existing paid subscriptions. Retire the reader Supporter plan from new sales;
retain its records and customer-portal access for existing subscribers.

## Current foundation and limitations

The backend already has `creator_insights`, content ownership, rich taxonomy,
submission review, follows, impressions, dwell and media-watch telemetry. The web
app already has a creator hub and insights page; iOS consumes the same insights API.
The latest backend commit deliberately removed a duplicate creator-stats API.
Reuse those modules and contracts. Detailed evidence lives in the companion
backend/client audit reports in `Docs/Research/`.

The existing Stripe integration implements checkout, portal and webhooks, but its
plan catalog and user experience still sell reader access. Several analytics
labels overstate what the data measures. Operational detail opens and optional
telemetry cannot form a trustworthy conversion funnel without matched populations.
Mutable reactions, saves and follows describe surviving edges, not immutable
historical conversions. Existing watch data must not be called actual attention.

## Architecture and data principles

Keep Django/DRF, PostgreSQL, React and the existing Swift client. One Cloud Run
service, synchronous bounded requests; no workers, Celery, Redis, or cron. Add
small domain modules rather than expanding monolithic views. Use additive API
fields and the existing `/api/v1/creators/me/insights/` surface for basic metrics.
Specialized content exploration/export may use subordinate owner-scoped routes;
do not duplicate the overview endpoint.

Every metric needs a documented event, numerator, denominator, population, time
window, timezone, deduplication rule, exclusions, and known coverage limits.
Unknown/unavailable is null or an explicit missing-data state, not invented zero.
All analytics windows use UTC. No device fingerprinting, precise location,
individual audience identities, sensitive traits, or inferred demographics.
Only voluntarily provided, appropriately consented data may support audience
segmentation. Aggregate audience preference segments must disclose their sample
size and suppress groups below a minimum audience size.

Operational records required for reading history and account functions are not
automatically permission to reuse them for creator analytics. The server enforces
the account's `share_analytics` preference and adult eligibility for analytics
ingestion; the browser also honors its analytics consent. Withdrawal stops new
events and removes the user from subsequent creator aggregation. Account deletion
continues to cascade event removal. Event retention and consent-version history
need explicit later implementation before claiming a comprehensive data platform.

## Delivery checkpoints

### 1. Evidence, economics, and decision record

Commit and push the three code/business reports and this design. Record the
verified baseline: backend billing + creator_insights = 183 tests, passing on
local PostgreSQL. Historical vault facts (2026-09-13) are clearly distinguished
from fresh code and test evidence. Preserve unrelated pre-existing working files.

### 2. Free audience contract

Remove the reader paywall at its backend choke point for anonymous and signed-in
readers, regardless of legacy plan JSON. Do not write anonymous read-limit cookies.
Reader limits (read cap, mystery-box purchase quotas, history window) must not be
sold via subscription. Preserve content tiers, removal/block filtering and auth.
Keep response compatibility fields such as `is_locked` with the free-access value
where existing clients need them. Web and iOS reading surfaces must not ask for a
subscription; pricing and account copy must describe creator tools. Legacy
subscription management remains accessible. Test stale plans and expired/canceled
subscriptions, plus anonymous and mature-content boundaries.

### 3. Trustworthy analytics collection

Bind web telemetry queues and impression deduplication to the active user and
consent state. Clear pending events when that identity/consent changes. Flush final
dwell in lifecycle-safe order. Do not count media seeking as time watched or resend
cumulative pause totals as independent samples. Distinguish share initiation from
confirmed downstream consumption. Validate server telemetry against current consent,
adult eligibility, visible content and known event sources. Prevent duplicate
impressions at the database boundary where feasible. Preserve partial-batch behavior
without accepting inaccessible or malformed events.

### 4. Creator decision tools

Extend the existing insights workspace with an owner-scoped content explorer:
filter by date window, format, language, theme/category and compare content using
real views, reactions, saves, share initiations and attention samples. Paginate and
allow bounded CSV export. Reuse existing taxonomy before adding tagging burden.
Provide daily views and distinct audience series with honest names, explain sample
coverage and empty states, and show recommendations with their evidence, minimum
sample rule and a concrete suggested action. Recommendations must be descriptive
hypotheses, never guarantees of growth or causal claims. Start with rule-based
recommendations; do not add an uncosted AI dependency.

Advanced analysis/export must use distinct creator entitlements rather than the
existing free `creator_analytics` feature. The UI must distinguish included tools,
paid tools and unavailable data. A failed payment affects paid creator tools only.
Do not advertise collaboration, scheduled publishing, external social analytics,
or A/B test lift until those systems exist.

### 5. Payment readiness for the US entity

Use Stripe Checkout and Customer Portal for the web creator subscription, subject
to actual account activation. Preserve server-controlled prices. Fix independently
verified payment-integrity defects before enabling purchases: subscription metadata
for event ordering, duplicate checkout defense, webhook state reconciliation and
safe price mapping, complete price identity comparison, and fail-closed missing
webhook configuration. Keep live purchases and production configuration out of a
local-code checkpoint; verify the integration in Stripe test mode before activation.
Add a separate explicit tips gate: enabling creator SaaS billing must not enable
collection of creator tips while no payout rail exists.

Native apps may consume free content and existing account capabilities. App Store
purchase/companion rules depend on the actual app and storefront; no blanket claim
that a creator subscription is exempt from in-app purchase. Web checkout launch
does not establish iOS distribution readiness.

## Expanded toolkit roadmap and metadata

| Creator job | Useful tool | Required evidence/data |
|---|---|---|
| Find what works | Content explorer, comparisons, format/theme breakdown | Comparable windows, sufficient exposure, attention definitions |
| Understand audience | Returning audience, followed/non-followed reach, preference overlap | Consent-qualified identifiers internally; aggregated outputs only |
| Plan next posts | Content inventory, gap and consistency suggestions | Existing format/theme/tone/language, optional series/intent |
| Improve a joke | Version notes and variant comparison | Immutable publication versions and fair assignment before A/B claims |
| Reuse content | Export, attribution/share assets, reusable drafts | Rights/provenance, license, media accessibility |
| Grow sustainably | Follow attribution, source mix, referral trends | Event attribution, share initiated vs resolved distinction |
| Operate professionally | Moderation status, content quality checklist, cost/usage visibility | Review workflow, metadata completeness, entitlement truth |
| Work with a team | Roles, approvals, multi-creator workspace | Separate workspace/seat model; not a renamed user subscription |

Prioritize existing metadata: format, language, themes, categories, age rating,
content tier, culture tags, creator and media kind. Candidate additions after the
initial explorer: creator-defined series, intended occasion, hook/punchline
structure, publication version, original/adapted/AI-assisted provenance, source and
license, captions/transcript, campaign and creator goals. Keep safety labels and
creator marketing labels separate. Optional tags require an explicit analytics or
workflow consumer; do not add speculative columns with no user benefit.

## Validation and release conditions

Meaningful backend tests cover free-reader access, consent/age/ownership, window
boundaries, zero-data math, filter validation, deterministic pagination, CSV safety,
and payment state changes. Frontend tests cover free copy, actual API contracts,
identity/consent changes and media lifecycle. Run lint, Django system/migration
checks and web build; run the existing suites after integrating behavior changes.
Use only local PostgreSQL with `DATABASE_URL=''`; local `.env` otherwise targets
production. Never include credentials or unrelated local files in commits.

Push checkpoints to `codex/creator-business-model`. Main deploys automatically;
feature-branch pushes provide reviewable work without silently deploying a new
business policy. Each checkpoint records actual test evidence and remaining work.
Paid launch additionally requires verified US merchant account, test checkout and
webhook exercise, customer-facing terms/refund/tax setup, and a price experiment
with recruited creators. A broad roadmap is not a claim that these tools shipped.
