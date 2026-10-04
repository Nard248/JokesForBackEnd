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

## Event schema implemented in the second checkpoint

The second checkpoint implements schema-v2 event/session UUIDs, web/iOS platform,
server receipt time and bounded client occurrence time. Actor identity comes from
authentication. Normalized event storage and existing metric projections commit
atomically; matching retries do not count twice. Unknown modern schemas and
malformed partial envelopes are rejected. Unversioned clients remain supported
with clearly labeled legacy observations and no retry identity guarantee.

Consent transitions now have server timestamps, policy version and provenance.
Existing opt-ins are labeled observed legacy state; this does not reconstruct
past consent. Eligibility is verified at receipt, not proven at client occurrence.
Creator metrics still use current adult consent and documented receipt-time windows.
The raw optional analytics window is 90 days, with immediate exclusion from
analysis, bounded request-driven deletion and an explicit purge command. Quiet
sites and backlogs need operator cleanup; this is not a guaranteed deletion deadline.
Account export includes all physically retained own analytics and private work;
account deletion cascades through the new records.

Web sends the v2 envelope. iOS now measures sustained visible impressions,
foreground viewport dwell and explicit reveals with account-bound privacy controls.
Native media watch/completion, media asset identity, publication versions, cohort
reporting, immutable reaction/follow transitions and controlled experiments remain
future work. `content_version` is explicitly null; no historical version attribution
or complete cross-platform media coverage is claimed.

See [the event contract](../API/Versioned_Audience_Telemetry.md) and
[the creator library](../API/Creator_Library.md).

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
Private notes, ordered series/set lists, reviewed taxonomy changes, consent
provenance and stable telemetry IDs are now implemented. Next add immutable
publication versions and action history before returning-audience cohorts,
retention reporting and fair comparisons. Defer team
roles, automated social posting, paid AI enrichment and creator payouts until
demand and cost are measured. There is no useful business outcome in collecting
every possible attribute without a defined creator decision.
