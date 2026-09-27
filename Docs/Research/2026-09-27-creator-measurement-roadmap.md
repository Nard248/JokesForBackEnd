# Creator measurement: coverage and next data contracts

This complements the code audit and creator-business design. It distinguishes
the initial implementation from a comprehensive future analytics platform.

## Decisions a creator should be able to make

| Decision | Measure | Minimum trustworthy contract | Current limitation / next work |
|---|---|---|---|
| Which content attracts attention? | Eligible impressions, opened exposures | Same user/content/date population, denominator shown | Detail opens and optional telemetry have different coverage; never divide unmatched populations |
| Is the joke being read? | Visible time, scroll depth, reveals | Foreground visibility only; explicit sample/session identity | Existing dwell samples are append-only; session-level completion is a later contract |
| Is media being watched? | Actual played time and completion | Exclude seeks/background time; identify asset and session | Legacy data measures positions; do not retroactively relabel it as actual attention |
| What resonates? | Reactions, saves, share initiations | Defined observation window, unique actor rules and sample size | Current edges disappear on undo; immutable action history is needed for historical charts |
| Is audience growing? | New/returning eligible viewers, follows/unfollows | Stable privacy-preserving internal identity; immutable follow transitions | Surviving Follow rows cannot reconstruct churn or lifetime follower growth |
| How does content spread? | Share initiation → resolved link → qualified visit | Separate events and attribution window | No downstream recipient/read attribution exists; sharing is not distribution proof |
| Who finds it useful? | Voluntary preference segments | Opt-in adults; minimum cohort size; no identities | Content-tag frequencies are not audience preferences or inferred demographics |
| When should I publish? | Exposure-normalized performance by publish hour | Publication time, local timezone choice, sufficient balanced observations | Reader activity hour alone cannot establish the best publication time |
| Which version is better? | Variant outcomes and confidence | Immutable versions and randomized exposure assignment | Comparing two organic posts is descriptive; no experiment or causal lift claim |
| What should I make next? | Evidence-linked suggestions | Sample size, uncertainty, comparable cohort/window | Metadata checklist works without traffic; behavioral recommendations require enough evidence |

## Event schema to add before scaling detailed analytics

Use a versioned event envelope: UUID event ID, schema version, event name,
server-received timestamp, bounded client-occurrence timestamp, source surface,
content ID and publication version, optional media asset/session ID, and collection
eligibility/provenance. Actor identity is assigned server-side; the client must
never choose another user. Use database uniqueness for retries and validate content
visibility at ingestion. Unknown event names and dimensions do not silently become
arbitrary columns or PII storage.

Store raw operational history separately from permission to use it for creator
analytics. Record opt-in/withdrawal timestamps and policy version before claiming
event-time consent provenance. Define retention by purpose and a request-driven
bounded purge process that fits the no-worker architecture. Extend account export
to include retained telemetry and consent history; deletion must remove or
irreversibly aggregate subject data. Verify those paths rather than treating
existing GDPR endpoints as evidence of complete telemetry coverage.

Impressions need database-backed user/content/date deduplication. Dwell/watch need
event/session identity before retries, repeated pauses, resumed playback and
completion percentages can be combined reliably. Mixed legacy and corrected
samples need a version boundary; do not pretend older samples can be repaired
without their original timelines.

## Additional joke attributes with an actual consumer

Keep format, tone/category, context/theme, culture, language, age rating, content
tier, source, creator and media relationships. Add attributes in the workflow
that uses them, with optional values and an honest unknown state:

| Attribute | User benefit | Boundary |
|---|---|---|
| Series / repertoire / occasion | Organize a set and find reusable material | Creator-controlled labels, separate from safety classification |
| Publication timestamp + immutable version | Compare versions/windows correctly | Do not overwrite past measurement meaning |
| Original/adapted/AI-assisted provenance + source/license | Reuse with clear attribution | Creator declaration is not proof of ownership |
| Intended use / creator goal | Recommendations tied to a real job | Never infer audience-sensitive traits |
| Captions, transcript, alt text | Accessible content and usable search | Review generated suggestions; preserve creator control |
| Variant/experiment assignment | Fair comparison | Implement randomization and guardrails before selling A/B lift |

## Order of investment

First make free viewing and current collection/metrics reliable. Then ship an
inventory, metadata recommendations and export that work with sparse traffic.
Next add publication versions, consent provenance and stable telemetry IDs; only
then sell returning-audience cohorts, retention and fair comparisons. Defer team
roles, automated social posting, paid AI enrichment and creator payouts until
demand and cost are measured. There is no useful business outcome in collecting
every possible attribute without a defined creator decision.
