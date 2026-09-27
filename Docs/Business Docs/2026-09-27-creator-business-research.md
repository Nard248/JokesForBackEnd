# JokesFor creator toolkit: business decision memo

Date: 2026-09-27. Status: research and recommended experiment, not approved production pricing. External sources were accessed on 2026-09-27. Owner decisions supplied during this research: viewers remain free; creators pay for useful tools; the business entity is in the USA; independent comedians and humor creators are the first paying segment.

## Decision

Test **Creator Pro at $15/month on the web**, with a useful free creator tier and free viewing. Use the existing **Stripe Checkout + Billing + Customer Portal** integration, subject to account activation and verification for the confirmed US entity. Keep Studio as a later **$49/month hypothesis**, not a second launch product. Sell a toolkit subscription, not audience access, guaranteed distribution, creator earnings, or a share of subscription revenue.

The first paid workflow should help a comedian organize, describe, evaluate, and reuse their own material even when JokesFor supplies little audience traffic. Audience and content analytics belong in the longer-term package, but empty dashboards cannot carry the initial willingness-to-pay test. Put incremental premium functions above useful basic analytics instead of merely charging for the currently free dashboard.

This follows the tenet order **Child Safety > Content Quality > Search Utility > Retention > Creator Value > Revenue**. Better metadata and stronger submissions can improve search utility and **Weekly Active Searchers**, while a paid creator workflow tests a separate business hypothesis. Do not replace the search North Star with subscription conversion or dashboard visits.

## Situation and evidence boundaries

The 2026-09-13 vault checkpoint records 173 jokes, one language, zero users and revenue, Stripe test mode, and public $5 Supporter/$15 Creator Pro placeholders. These are dated observations, **not a new production measurement**. The same notes describe human approval as the publishing bottleneck, no AI generation/enrichment pipeline, and no creator payout ledger or Stripe Connect. The September Business Position identifies untested demand and catalog/curation supply as the constraint. Sources: `JokesFor/Context/current-state`; `JokesFor/Context/open-gaps`, especially §§2, 4, 7; `JokesFor/Business/document-register`, document 11.

Repository evidence inspected today confirms `creator_analytics=True` in `billing/entitlements.py` and the seeded free plan; the read-cap default remains 10 in the entitlement registry. The existing monetization design separates business entitlements from Stripe's payment mechanics. The runbook documents Checkout, Portal, subscription webhooks, and placeholder prices. These facts make a creator subscription feasible but do not establish customer demand or validate production payment readiness. Sources: `billing/entitlements.py`; `billing/migrations/0002_seed_plans.py`; `billing/migrations/0003_free_joke_read_cap.py`; `Docs/superpowers/2026-06-19-monetization-design.md`, §§1–3; `Docs/STRIPE_GOLIVE.md`.

The earlier creator-intelligence design already covers views/reach, punchline reveal rate, saves, shares, source mix, content comparisons, audience tastes and recommendation cards. It is a design document with stale implementation assumptions, not a claim that every feature is ready to sell. Its own-content analytics are the starting point for a focused audit, not justification for a second analytics subsystem. Source: `Docs/superpowers/2026-06-17-mvp02-creator-intelligence-design.md`, §§3–4.

The obs-recall skill was read. Its REST credential path was unavailable in this environment, so the locally accessible vault notes above were read as a fallback; all carry a 2026-09-13 verification date. No vault notes or external payment state were changed by this research.

## Options

| Option | Benefit | Problem | Decision |
| --- | --- | --- | --- |
| Charge viewers for more reveals | Existing gate and placeholder plans | Conflicts with the owner's free-viewer direction and reduces discovery | Retire this offer from current packaging |
| Put the existing creator dashboard behind $15 | Smallest implementation | Audience data has little value before real traffic; removes useful free feedback | Keep basic feedback free |
| $15 creator toolkit with bounded enrichment | Recurring value from a comedian's own workflow; scope fits one-person creators | Must prove time saved and quality; enrichment is not implemented | Recommended experiment |
| Usage-only credits | Aligns variable processing cost with spend | Does not price persistent dashboards, organization or recurring workflow clearly | Defer as the primary model |
| Full Studio/agency suite immediately | Higher nominal contract value | Team permissions, collaboration and multiple workspaces are unvalidated scope | Research after Pro demand |

## Competitive facts and implications

Prices below are competitors' advertised terms, not evidence that JokesFor can charge the same amount.

| Product | Observed first-party offer | What it means for JokesFor |
| --- | --- | --- |
| Buffer | Free supports three channels. Essentials is $5/channel/month **billed annually at $60**; Team is $10/channel/month **billed annually at $120**. Advanced analytics sit in paid plans; free includes AI assistance and basic insights. [Pricing](https://buffer.com/pricing) | Generic analytics and an AI text box are weak differentiation. A $15 specialist product must save a comedian meaningful work. |
| Metricool | USD monthly Starter begins at $25 for five brands; Advanced begins at $67 for 15 brands. Free includes one brand and 30 days of analytics. Paid offers extend history/reporting, and Advanced adds team/client controls. [Pricing](https://metricool.com/pricing/) | History, reporting and collaboration are intelligible upgrade dimensions. JokesFor should not reproduce a cross-network scheduling suite. |
| vidIQ | The public plan page advertises Free with 150 AI credits/month, Boost with 2,000 and Max with 6,000, alongside research, recommendations and optimization. Numeric paid prices did not render reliably in the retrieved page, so none are quoted. [Plans](https://vidiq.com/plans/) | A recurring toolkit with a visible processing allowance is an established packaging pattern; its credit quantities do not determine JokesFor's cost envelope. |

**Inference:** JokesFor's differentiating wedge is a comedian's structured repertoire: occasion, format, tone, audience suitability, provenance, variants and observed response. Cross-platform audience imports, generic content calendars and broad AI generation would place it against larger products before the humor-specific workflow is proven.

## Recommended packaging hypotheses

| Capability | Viewer / Creator Starter — free | Creator Pro — $15/month experiment | Studio — $49/month hypothesis, deferred |
| --- | --- | --- | --- |
| Reading and search | Free viewing, search and punchline access, subject to safety/access and ordinary abuse controls | Same viewer experience | Same viewer experience |
| Creator participation | Profile, submission, manual metadata, publishing review, basic own-content performance | Same participation rights | Same participation rights |
| Analytics | Useful summary and per-item feedback; retain the existing basic baseline | Saved comparisons, longer history where lawfully retained, filters, exports, supported recommendations | Shared reports and multi-creator views after permissions exist |
| Content workflow | Personal library and manual organization as available | Batch organization, metadata suggestions, reusable variants/notes, export | Team library, review/approval workflow and three seats only after demand |
| Enrichment allowance | Five trial analyses/month once implemented | Initial hypothesis: 100 short-text item analyses/month | Initial hypothesis: 300 pooled analyses/month |
| Publishing | Moderated under the same rules | No guarantee of approval, extra distribution or better safety treatment | Same |
| Earnings | No earnings promise | Toolkit purchase; no payout entitlement | Toolkit purchase; no payout entitlement |

All new capabilities and allowances in this table are **proposals**, not shipped facts. Do not advertise them until delivered. “One analysis” should mean a named operation on one bounded short-text item, with a visible length limit; repeat identical successful requests use cached results. Failed provider calls do not consume allowance. Expose the remaining allowance and reset date. Begin with a hard cap; offer no automatic overage or obscure credit exchange rate.

Why $15: it is a single coherent creator price, fits the existing `creator_pro` amount, sits below broad multi-brand tools, and is large enough to test real purchase intent. This is an informed hypothesis, not a demand finding. Retire the $2.99/$4.99/$5 consumer-premium narrative and public Supporter purchase path from this model. Do not promise “ad-free” as a paid benefit when the product has no ads. Do not promise AI generation, three languages, 5,000 jokes, or payouts. Source: `JokesFor/Business/pitch-vs-system-drift`, items 1–6 and 13.

Launch monthly only. Consider $150/year after retention and support costs are understood; that is a 16.7% discount against 12 monthly payments and must not become a way to hide weak recurring use. A 14-day no-card preview can start when the creator imports or submits usable material, rather than spending the trial on an empty account. These are recommendations, not currently configured billing behavior.

Subscriptions cover persistent workflow and analytics; bounded usage covers the variable enrichment cost. Add optional prepaid analysis packs only if real subscribers repeatedly reach the allowance, unit cost is measured, and customers understand what is consumed. Usage metering, credit balances, refund semantics and prepaid packs are separate implementation work; the existing quota counter does not automatically provide a payment-grade credit ledger.

## Tool order and measurable value

| Priority / gap | Narrowest useful version | Tenet and metric | Data / compliance constraint | Defer |
| --- | --- | --- | --- | --- |
| 1. Unstructured or incomplete material | Suggest missing format, topic, occasion and tone on one submitted text; creator accepts edits; record provenance | Content Quality, Search Utility; metadata completeness, acceptance rate, search success, time to prepare a submission | No automatic safety-rating override; suggestions cannot bypass moderation; keep private drafts private | Autonomous publishing; generated catalog at scale |
| 2. Creator cannot identify useful material | Own-content overview plus comparison of two items or periods; show numerator, denominator, date window and source | Creator Value, Retention; weekly creator workflow use and decisions taken | Owner scope; separate formats; a reveal is a completion proxy, not proof of laughter | Cross-network analytics and benchmarking |
| 3. Analytics do not lead to an action | One explainable suggestion tied to sufficient observed evidence; for sparse data suggest completing metadata or gathering feedback | Content Quality; accepted recommendation followed by edit/publication, qualified saves/shares | Avoid demographics and individual audience identities; suppress small sensitive groups | Universal “virality score,” income forecasts, black-box growth promises |
| 4. Work cannot leave the product | Own-library CSV/Markdown export and clearly attributed share assets | Creator Value; exported/reused material and retained subscribers | Preserve rights/provenance; exports do not transfer rights to third-party jokes | Automated publishing integrations and social account credential storage |
| 5. Team demand | Three-seat workspace with roles and report sharing | Creator Value, Revenue; paid team requests, activated seats | Strict workspace isolation and audit trail | Build only after at least three teams commit to a concrete paid pilot |

For a pilot, use an explicit provisional minimum such as **100 qualified observations** before presenting a comparative performance recommendation, and at least **20 distinct eligible viewers** before showing an audience breakdown. These are conservative product heuristics, not statutory thresholds or a statistical significance claim. Validate them with the actual distributions, retain uncertainty labels, and avoid comparing unlike event definitions. Show raw denominators when present; show “not enough data” rather than fabricated trends.

Keep the recorded adult-and-consent analytics restrictions and age/content-serving rules intact. Avoid marketing demographic or cross-user targeting features. Small-cohort suppression, ownership checks and retention limits should be tested independently of plan status. The vault compliance note establishes current design constraints; it is not relied on here as a new legal opinion. Source: `JokesFor/Business/compliance-framework`, Age & tiers; `JokesFor/Context/open-gaps`.

## Payment providers and channel policy

The owner confirmed a **US entity** during the task. Use Stripe unless account eligibility, underwriting, product restrictions or operating/tax requirements make it unsuitable. US incorporation alone does not mean activation has completed. Merchant identity, beneficial owners, bank account, product and operating locations must be represented accurately. User timezone or personal residence alone would not have established merchant country.

| Provider | Verified commercial facts | Recommendation |
| --- | --- | --- |
| Stripe Payments + Billing | Published US domestic-card fee is 2.9% + $0.30; international cards add 1.5%, and conversion adds 1% when required. Billing pay-as-you-go adds 0.7% of billing volume. These are not an all-in tax/compliance service quote. [Payments pricing](https://stripe.com/pricing), [Billing pricing](https://stripe.com/billing/pricing) | Preferred for the confirmed US entity: preserve the existing integration. Establish tax registrations/collection and customer refund terms before live sales; price the relevant extra services separately. |
| Paddle | Advertises merchant-of-record billing at 5% + $0.50 per checkout transaction, including sales-tax handling. Its supplier policy excludes specified countries; Armenia is not listed among exclusions. Country policy is not account approval. [Pricing](https://www.paddle.com/pricing), [Supplier country policy](https://www.paddle.com/help/legal/sanctions/which-countries-are-supported-by-paddle) | Fallback if merchant-of-record tax administration is worth migration cost. Confirm product and payout acceptance; no need to integrate in parallel. |
| Lemon Squeezy | Advertises 5% + $0.50; its fee documentation adds 0.5% for subscriptions, 1.5% for international transactions, 1.5% for PayPal, and 1% for non-US bank payouts. Armenia appears on the bank-payout list. [Pricing](https://www.lemonsqueezy.com/pricing), [Fees](https://docs.lemonsqueezy.com/help/getting-started/fees), [Supported countries](https://docs.lemonsqueezy.com/help/getting-started/supported-countries) | Additional merchant-of-record fallback; compare actual payment/payout mix and onboarding acceptance. Do not model only the headline fee. |

Had the entity been solely Armenian, standard direct Stripe processing would not have been assumed available: Armenia does not appear on Stripe's supported-business-country list. A US entity is a different eligibility case. [Stripe availability](https://stripe.com/global). No new entity, bank account, payment product or provider account should be created by this research.

A merchant of record can simplify transaction-tax administration; it does not supply JokesFor's creator payout ledger, content moderation or own corporate tax obligations. Alternative providers require new checkout/webhook/entitlement integration and operational verification. The existing code is Stripe-specific, not a drop-in abstraction for all providers.

### iOS

Keep the paid toolkit web-only for the first experiment and the iOS viewer experience free. Remove obsolete paid-viewer messaging consistently. If premium creator features are later accessible inside iOS, assess the actual design before release: Apple's §3.1.3(f) permits some free companions to paid web tools without in-app purchasing or purchase calls to action; §3.1.3(b) governs multiplatform paid features; §3.1.3(c) does not automatically exempt a single-user creator SaaS. US-storefront external-purchase links have separate treatment; that does not establish one global policy. These are review conditions, not a guaranteed exemption. [App Review Guidelines, §§3.1.1–3.1.3](https://developer.apple.com/app-store/review/guidelines/).

If IAP is chosen later, model the applicable storefront/program: Apple's standard public summary lists 30%, qualifying subscriptions 15%, and Small Business Program eligibility/enrollment may provide 15%. Special regional terms exist, so these are scenario rates. [Membership terms summary](https://developer.apple.com/programs/whats-included/), [Small Business Program](https://developer.apple.com/app-store/small-business-program/). A second payment provider also requires coherent cancellation, receipt validation and entitlement precedence; there is no StoreKit integration in the dated current-state notes.

## Unit economics: explicit scenarios, not a forecast

For a **$15 tax-exclusive monthly charge**, the following arithmetic assumes a domestic US card, no FX, refunds or disputes. Variable delivery cost of **$2 per paying creator/month is a planning assumption**, not measured expenditure. It must include enrichment, attributable compute/storage/egress and support. Figures below exclude shared/free-viewer costs, human curation, acquisition, corporate tax and labor unless explicitly assigned to that $2 assumption.

| Scenario | Payment/billing cost | Net before delivery | Contribution after assumed $2 | Contribution / $15 |
| --- | ---: | ---: | ---: | ---: |
| Stripe US domestic + Billing | $0.84 | $14.16 | $12.16 | 81.1% |
| Paddle published base | $1.25 | $13.75 | $11.75 | 78.3% |
| Lemon Squeezy US subscription, US bank | $1.33 rounded | $13.68 rounded | $11.68 rounded | 77.8% |
| Apple IAP 15% scenario | $2.25 | $12.75 | $10.75 | 71.7% |
| Apple IAP 30% scenario | $4.50 | $10.50 | $8.50 | 56.7% |

Calculations: Stripe `15 × (0.029 + 0.007) + 0.30`; Paddle `15 × 0.05 + 0.50`; Lemon Squeezy `15 × (0.05 + 0.005) + 0.50`. Fee sources are linked above. No extra Stripe processing fee is layered onto Apple IAP. Taxes can reduce net proceeds when prices are tax-inclusive; Lemon Squeezy explicitly assesses its platform fee on total order value, so the table must not be reused unchanged for VAT-inclusive/international transactions.

At $49 the domestic Stripe + Billing net would be $46.94 before delivery; this does not justify Studio without higher willingness to pay. At $15, a target of 75% contribution leaves a **$2.91** delivery allowance under the Stripe base case (`15 − 0.84 − 11.25`). If the plan includes 100 analyses and reserves $1 for non-model delivery, each successful analysis must average at most **$0.0191** all-in across the full allowance to meet that target. This is a cost ceiling to test, not a model-provider quote; do not advertise an allowance until measured.

Human review can dominate those economics. Illustrative only: two minutes per submitted item at a $15/hour labor cost is $0.50/item; twenty submissions cost $10. Paying for Pro must not imply unlimited human review. Measure actual review minutes, accepted items and backlog. Set operational submission limits around curation capacity, separately from paid analysis allowances. A 100-analysis quota is not a promise to publish 100 items.

Bottoms-up revenue scenarios: 100 activated creators × 10% paying × $15 = $150 MRR; 500 × 10% × $15 = $750; 1,000 × 15% × $15 = $2,250. Every conversion rate here is an assumption. At $15, $5,000 MRR requires 334 paying creators. Under the $12.16 contribution case, covering $1,000/month of shared operations/free-viewer costs requires 83 payers; $5,000 requires 412. These break-even counts exclude costs not included in the budget and ignore churn/acquisition. Avoid unsupported TAM or LTV claims.

Track free-viewer cost and paid-creator coverage explicitly. The viewer base is valuable to the product but is not free to serve. Use paid contribution payback for acquisition planning; with the assumed $12.16 contribution, a three-month payback ceiling would be $36.48 CAC before churn. This is a budgeting scenario, not evidence that paid acquisition is ready.

## Rollout and validation

1. **Align the promise.** Define viewers as free; select one public creator offer; retire conflicting Supporter/consumer-premium messaging; keep tips off. Update plan vocabulary, terms and product copy together. Confirm the detailed backend/frontend entitlement audit before changing gates. This protects Search Utility and prevents inconsistent pricing claims.
2. **Recruit 10–15 adult independent comedians/humor creators as design partners.** Test their actual weekly work with their own material. Ask them to prepare, classify, select and reuse pieces; record existing alternatives and time taken. No outreach was sent as part of this research. Narrow the group further if their workflows differ substantially.
3. **Deliver a focused free pilot over two weeks.** Start with metadata suggestions, own-library organization/export and basic performance evidence. Define activation as completing one meaningful workflow on at least three owned items and returning within seven days. Record missing-data states and curation time. A concierge operation may validate the workflow before expensive automation.
4. **Offer a real $15 monthly paid pilot only after the feature, billing, tax, privacy and support path is ready.** Initial learning gates: at least five participants pay without a special services bundle; at least 60% of payers complete the core workflow in three of the next four weeks; at least half renew for month two. These are provisional decision thresholds for a small cohort, not PMF or statistically conclusive findings.
5. **Measure both sides for six to eight weeks.** Creator indicators: activation, weekly core-workflow use, measured preparation time, recommendation acceptance, paid conversion by activated cohort, cancellation reasons and contribution. Viewer indicators: Weekly Active Searchers, search success/zero results, saves and D7 retention. Track quality/rejection rate, review minutes per approved item and moderation backlog as guardrails.
6. **Decide from behavior.** If creators value organization but ignore analytics, package around the workflow. If they return only after JokesFor generates views, prioritize catalog/reader acquisition rather than more paid charts. If fewer than five buy after repeated useful sessions, revise value/segment before testing annual commitments or adding Studio. Expand only after retention and unit-cost evidence.

The earlier consumer PMF gate—D7 >20% for two months, 10K MAU, >2 searches/session, viral coefficient >0.3—remains a separate unproven gate. Creator willingness to pay does not establish consumer PMF. Source: `JokesFor/Business/goals-and-metrics`, Phase-1 → Phase-2 gate. This experiment deliberately tests creator SaaS earlier than the old creator-marketplace sequence; it does not authorize building a payout marketplace before demand.

## Risks and owner decisions still needed

- **Audience cold start:** zero/low-data analytics need honest empty states. No claimed uplift, virality, audience demographics or earning potential without evidence.
- **Curation cost:** content supply improves only if review capacity grows with submissions; paid analysis and publish capacity must be distinguished.
- **Pricing scope:** confirm which incremental capabilities justify the $15 offer. Preserve a useful free participation path and basic feedback.
- **Account readiness:** verify the confirmed US entity's Stripe activation, bank/payout access, product acceptance, tax setup and cancellation/refund terms. Choosing a provider does not authorize switching production to live mode.
- **Privacy and rights:** determine allowed draft retention and AI-provider handling before sending private material; keep creator attribution and rights clear. Safety classification remains controlled by the moderation process.
- **Creator payouts:** existing tip collection is not a payout system. Keep tips disabled until a separate ledger, payout mechanism, accounting, disputes/refunds and creator terms are ready. The old 80–85% revenue-share promise does not apply to toolkit subscriptions and should be removed or explicitly reserved for a future separately defined marketplace.
- **Definition of success:** approve or amend the small-pilot learning thresholds, curation budget and maximum delivery cost before interpreting results.

## Vault notes to update after the owner accepts the decision

No vault updates are made by this report. Recommended updates:

- `JokesFor/Business/business-model`: free viewers, Creator Starter/Pro hypothesis, US Stripe decision, subscription-versus-payout distinction and channel cost assumptions.
- `JokesFor/Business/goals-and-metrics`: creator activation/retention/payment experiment, keeping Weekly Active Searchers and consumer PMF separate.
- `JokesFor/Business/market-and-competition`: current specialist-tool benchmarks and independent-comedian beachhead.
- `JokesFor/Business/pitch-vs-system-drift`: retire consumer pricing/reveal/paywall claims and unsupported AI/payout promises; mark proposed tools as unbuilt.
- `JokesFor/Business/document-register`: register this dated research memo and superseded pricing sections.
- `JokesFor/Context/open-gaps`: tracked implementation/operating gaps only, distinguishing audit findings from proposals.
- `JokesFor/Business/compliance-framework`: creator-tool data handling and the chosen iOS commerce design after review.
- Relevant billing, entitlement, creator-insights and Stripe go-live notes: update after implementation verification. Do not rewrite `Context/current-state` as a fresh checkpoint without re-measurement.
