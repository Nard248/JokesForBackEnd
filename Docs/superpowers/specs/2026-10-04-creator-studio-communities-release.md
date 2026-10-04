# Release: Creator Studio + self-forming communities (2026-10-04)

Branch `release/creator-studio-communities` (backend + web), cut from
`codex/creator-business-model` (`ad8175c` / `cabce62`). Two Codex drafts were
consolidated into one product release. The uncommitted International Discovery /
Unified Search draft in the main checkout is a third, separate effort and is not
part of this release.

## What the two drafts were

| | Business Creator Tools | Self-Forming Communities |
|---|---|---|
| State found | Real models/auth/entitlements; 12 BE + 5 web commits | Isolated synthetic sandbox: own settings, own Postgres (:55437), own `Participant`/`Content` tables, standalone `communities.html` bundle |
| Business value | Free audience; paid Creator Pro tools (content workbench, CSV export, private library, metadata review) | Makes collective taste visible; audiences that form around themes |
| Gaps | Four creator pages that looked like four apps; no "Creator Pro" name in UI; empty insights without consenting adults | Not reachable from the app; graph drew individual people (unacceptable on real users); demo-only mutations (`simulate`, `advance`, share cascade) |

## Decisions

1. **Port the value, not the sandbox.** Keep the pure, tested scoring engine
   (`communities/engine.py`, unchanged math) and rebuild the adapter on real data:
   subjects = `ContextTag`; signals = positive `JokeReaction`, `Favorite`,
   `SavedJoke`, signed-in `ShareEvent`; real auth; real membership. Delete
   `community_lab/`, its settings, DB, launcher and standalone web bundle. The
   prototype remains on the `codex/self-forming-communities` branches.
2. **Privacy is structural.** Aggregates only from adults sharing analytics
   (+ adult explicit joiners); tier_1, non-removed content only; counts < 5
   withheld; no identities in any payload; the map draws communities and bridges,
   never people. A person's own affinity is visible only to them, and the UI tells
   non-sharing readers they are not counted (consent tie-in, not a dark pattern).
3. **Communities are the Creator Pro differentiator.** New paid feature
   `creator_community_insights` → `GET creators/me/communities/`: which
   communities a creator's consenting audience belongs to, reach rate, and
   rule-based opportunities (stronghold / untapped-but-warm / emerging). This ties
   the audience concept to the revenue model instead of shipping two parallel
   experiments.
4. **One Creator Studio.** Shared layout, tab bar, plan badge and a single
   Creator Pro gate across Overview / Content / Insights / Communities / Library;
   "Studio" nav item; "Creator Pro" named in billing. Communities live in the
   SPA at `/communities[/:slug]` with a nav item and an Explore entry.
5. **No workers.** Aggregate cached in DatabaseCache, invalidated by engagement
   writes; bounded 90-day window. Documented scaling path: incremental
   per-(user, community) materialization.
6. **Demo data is a guarded seed, not a mode.** `seed_showcase` (local-only
   guard) builds a Creator Pro comedian, a free creator, a reader one laugh away
   from activating the forming *Space* community, ~260 synthetic adults (15%
   non-consenting), a cooling *Weather* community and full Studio library data.

## Out of scope / still open

Payment activation (Stripe account onboarding, `CREATOR_CHECKOUT_ENABLED`), price
validation ($15 is a hypothesis), Supporter subscriber migration, iOS surfaces for
communities/Studio, community feeds/conversations, unsupervised topic discovery or
merge/split, recipient-attributed shares, incremental aggregation at scale,
counsel review of privacy copy, and the 47-entry dependency audit.
