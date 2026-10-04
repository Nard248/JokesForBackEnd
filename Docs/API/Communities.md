# Communities API (self-forming communities)

Base: `/api/v1/`. Implementation: `communities/` (engine, services, views), creator
route in `creator_insights/urls.py`. Released on `release/creator-studio-communities`.

## Concept

A **community** is the audience that forms around one theme (`ContextTag`). Every
listed theme has one `Community` row (presentation: emoji, colour, tagline,
`is_listed`). Nobody creates or moderates a community; it **forms** when enough
people independently enjoy several jokes on the theme and **cools** when the
laughs stop.

| Rule | Value (`communities/engine.py`) |
|---|---|
| Signals | positive reaction (`lol`, `crying`) 3 · favorite 4 · save 4 · signed-in share 2 · view 0 |
| Per-joke cap | strongest signal per person per joke, max 4 points |
| Decay | 7-day half-life, 90-day window |
| Personal membership | ≥ 6 points across ≥ 2 distinct jokes |
| Activation | ≥ 5 independently engaged (inferred) members |
| Status | `active` ≥5 engaged · `cooling` <5 now but ≥5 seven days ago · `forming` otherwise |
| Explicit choice | `joined` counts as a member but never toward activation; `left` overrides inference until rejoined |

**Population (privacy line):** every aggregate — including explicit joins — uses
only **established** active adults with `share_analytics`
(`communities.privacy.established_users`, built on
`creator_insights.privacy.eligible_analytics_users`; see **Privacy: established
accounts and stable noise** below), and only signals recorded **after** that
person's latest opt-in (`AnalyticsConsentRecord`; consent is never applied
backwards). Signals only from `tier_1`, non-removed jokes. Public person-counts
(members, engaged members, bridges, stats, growth) are released from a daily
snapshot with keyed, day-stable noise, then rounded to the nearest 5 and `null`
when the noisy value is under 5; `activity` and `score` are `null` while fewer
than 5 people contributed in the last 7 days. Status (`active`/`cooling`/`forming`)
stays live. No response contains user ids, names or samples. A person's own
affinity is computed from their own activity and returned only to them. Explicit
joins by people who do not share analytics, or by accounts that are not yet
established, change only their own view.

Request-triggered only. The aggregate is cached without TTL
(`communities:aggregate:v3`) behind an opaque, never-reused version (a culled
version key forces a recompute) and a 1-hour hard max age; engagement writes and
profile saves replace the version
**after commit** (`communities/signals.py`; anonymous shares are ignored). A stale
entry is recomputed at most every `COMMUNITIES_MIN_REFRESH_SECONDS` (default 5)
by one lock holder while others serve the previous state, so engagement bursts
cannot force recomputation. Recomputation reads the materialized signal table,
not the engagement ledgers — see **Scale: incremental materialization** below.

## Privacy: established accounts and stable noise

`communities/privacy.py`. These replace the two residual risks accepted on
2026-10-04 (five fresh accounts could activate a theme; deterministic rounding
let sock accounts detect one extra counted member at a rounding boundary).

**Established accounts (Sybil resistance).** A consenting adult counts toward any
aggregate — activation, member counts, bridges, growth, stats, creator reach —
only when the account is at least `COMMUNITIES_ESTABLISHED_ACCOUNT_DAYS` old
(default **7**) and has a positive signal (`CommunitySignal`: like, favorite,
save, signed-in share) on at least `COMMUNITIES_ESTABLISHED_MIN_JOKES` distinct
jokes (default **3**). "Active" already implies a verified email whenever
`EMAIL_VERIFICATION_REQUIRED` is on (unverified sign-ups stay `is_active=False`),
and Google sign-ups are verified by Google. Why these values:
- 7 days: a sock farm has to be prepared a week ahead and cannot react to a
  same-day event (a new creator, a new joke, a target joining); a real reader
  who signs up and enjoys jokes waits one week, which costs nothing for a
  descriptive number.
- 3 distinct jokes: one more than the 2-joke membership minimum, so an account
  cannot become a counted member from exactly the two jokes that put it in a
  community; each sock needs engagement beyond the target theme. Signals on any
  joke count (this gates authenticity, it releases nothing).
- Both stack with the per-request throttles and the email gate; together they
  raise the cost of activating a community from "five sign-ups" to "five
  verified accounts, a week old, each with spread-out engagement".
A non-established account still sees its own affinity, progress and explicit
join/leave; `viewer.counted` is `false` and its explanation says when it will
count. Thresholds are read at query time (no stored flag), so an account starts
counting at the first recompute after it qualifies.

**Stable calibrated noise (differencing).** Every released person-count gets
two-sided geometric (discrete Laplace) noise, `P(k) ∝ exp(−ε·|k|)`, the standard
mechanism for a sensitivity-1 count, at `COMMUNITIES_NOISE_EPSILON` (default
**1.0**). The noise is a deterministic function of an HMAC
(`salted_hmac`, SHA-256, keyed from `SECRET_KEY`) over
`(statistic, subject ids, UTC day)`: asking again on the same day returns the
same draw, so repeated queries cannot be averaged, and nobody without the key
can predict or subtract it. The noisy value is then rounded to the nearest 5 and
suppressed when under 5 (rounding/suppression are post-processing: free).
Engaged ≤ members and multi-community ≤ total are enforced after noise (also
post-processing). Every community pair gets a bridge draw, including pairs with
zero overlap, so a released bridge never proves a real overlap exists.

Released counts come from a **once-a-day snapshot** (`services.daily_aggregate`,
cache key `communities:daily:v2:{day}`, frozen by the first recompute of the UTC
day). Without the freeze, an attacker could add or remove socks one at a time to
locate the day's noise and a rounding boundary, then watch for a real reader
crossing it; with it, nothing can rise within the day. The snapshot's id sets are
re-intersected with who counts *now*, so consent withdrawal or account deletion
still lowers today's numbers (they can only fall within a day).

| Statistic id | Subject | Where |
|---|---|---|
| `members`, `engaged` | community | directory, detail, creator `members` (same draw) |
| `growth` | community | directory (`release_delta`: noised, rounded, never suppressed) |
| `bridge` | community pair | directory, detail bridges |
| `member-total`, `multi-community` | — | directory `stats` |
| `creator-audience` | creator | `creators/me/communities/` `audience.size` |
| `creator-reached` | creator, community | `creators/me/communities/` `reached_members` |

**Privacy budget.** Each statistic has sensitivity 1 (one person changes it by at
most 1) and costs ε per day. One person in *k* communities touches about
`2k` (members, engaged) + `k` (growth) + `C(k,2)` (bridges) + 2 (stats) + their
creators' reach statistics, so the per-day budget is that many ε — e.g. ≈ 9ε for a
reader in two communities. Across days the draws are fresh, so an attacker who
watches a constant count for *n* days composes to *n*·that. This is therefore a
deterrent calibrated to the threat that was actually accepted — detecting one
extra person at a rounding boundary — not a lifetime differential-privacy
guarantee: at ε = 1 the noise has standard deviation ≈ 1.4 people, so whether
one person moved a count across a rounding boundary is masked by a draw the
attacker cannot see, cannot repeat within the day, and cannot hold steady across
days (the true count, the noise and the rounding boundary all move). Raise
protection by lowering ε (e.g. 0.5 doubles the noise); 0 disables noise and is
for tests only (exact-count tests run with `COMMUNITIES_NOISE_EPSILON=0`).

**Remaining, much narrower residuals (documented):** within one day, established
socks that are in the snapshot can withdraw consent one at a time to learn where
a count sits relative to a rounding boundary, and could then see that *someone*
in the set withdrew or deleted their account that day (never who, never a join).
Revisit the budget before community feeds, conversations or member directories,
which would add statistics per person.

## Scale: incremental materialization

Single Cloud Run service, no workers or schedules — the write that changes the
ledger also changes the materialization, in the same transaction.

**`CommunitySignal`** (`communities/models.py`, migrations `communities/0003`
schema + `0004` backfill): one row per positive ledger row —
`(user, joke, kind ∈ like|favorite|save|share, source_id, occurred_at)`, unique
on `(kind, source_id)`, indexed on `occurred_at` and `(user, joke, kind)`.
`like` mirrors a `lol`/`crying` `JokeReaction` at its `updated_at`; favorites,
saves and signed-in shares mirror `created_at`. Negative reactions and anonymous
shares never get a row.

**Upkeep** (`communities/materialize.py`, wired in `communities/signals.py`):
`post_save`/`post_delete` on `JokeReaction`, `Favorite`, `SavedJoke`,
`ShareEvent` upsert or delete the mirror row synchronously. A reaction switched
to 🤔/🙄 or toggled off loses its row; one switched back gets the new
`updated_at`. Unsaving from one collection keeps saves in the others. Shares are
the only unbounded kind: a share older than 7 days that has a newer share also
older than 7 days can never again change any number, so it is pruned on write
(deleting a share resyncs that person/joke's shares from the ledger). Deleting
an account or joke cascades. Writes that bypass model signals (`bulk_create`,
`QuerySet.update` on a ledger, `loaddata`) must be followed by
`python manage.py rebuild_community_signals` (idempotent: recreates the table
from the four ledgers and prunes); `seed_showcase` and `seed_demo_creator` call
it.

**Eligibility stays at read time:** consent (`share_analytics`, active, adult,
signal after the latest opt-in), `tier_1`, `is_removed=False`, themes and
listing are applied when reading, so withdrawals, account deletion, takedowns
(even via `QuerySet.update`), tier changes and re-tags apply on the next
recompute without touching the table. Re-tags also invalidate the cached
aggregate (`m2m_changed` on `Joke.context_tags`); takedowns and tier changes
done with `QuerySet.update` are picked up within the 1-hour max age, as before.

**Read:** `services.signal_rows()` filters the table (eligibility as
semi/anti-joins, evaluated set-wise). `services.affinities_at()` lets Postgres
take each person's strongest capped, decayed signal per joke
(`min(4, weight) · 2^(−age/7 days)`, the same double-precision operations as
`engine.decay`, half-life applied at read time) and sum it per (person, theme)
with the number of contributing jokes; `engine.affinities_from_totals()` then
applies the unchanged membership rules (≥ 6 points across ≥ 2 jokes, `left`
overrides, `joined` never activates). Activity counts and distinct
contributors are grouped per (theme, UTC day) in SQL too. A fixed set of
queries regardless of traffic (asserted in tests); Python handles one row per
(person, community) instead of one per signal. Local benchmark (3,000
consenting adults, 313k ledger rows → 176k mirrored): ledger scan 1,048 ms,
materialized 410 ms per recompute, byte-identical output. Recompute still runs
at most once per refresh floor behind the cache.

**Equivalence:** `communities/tests/test_materialization.py` replays randomized
engagement (reactions, switches, unreacts, favorites, multi-collection saves,
repeated shares, consent histories, minors, inactive accounts, memberships,
takedowns, tier and theme changes, withdrawal, account and joke deletion)
through the real write paths and asserts the result equals the frozen ledger
scan (`communities/tests/legacy.py`) field by field — aggregates, per-person
affinities now and a week ago, viewer states and creator audiences — both under
incremental upkeep and after a full rebuild. Membership sets and counts are
compared exactly; scores to 9 decimals (Postgres may add the same terms in a
different order, so only the last bit can differ).

**Next step if recompute time grows:** keep per-(person, theme) running totals
anchored to a fixed epoch (`Σ w·2^(t/h)`) so a recompute reads one row per pair;
needs lazy correction for signals leaving the 90-day window and for the
week-ago comparison.

## GET `communities/` — AllowAny

```jsonc
{
  "generated_at": "2026-10-04T11:43:50Z",
  "stats": {"active_communities": 12, "forming_communities": 1, "members": 150,
            "multi_community_members": 57, "signals_7d": 1867},
  "counts_date": "2026-10-04",   // UTC day of the snapshot the person-counts come from
  "viewer": null | {"counted": true, "shares_analytics": true, "communities": ["puns", "space"]},
  "communities": [{
    "slug": "work", "name": "Work", "description": "…", "emoji": "💼", "color": "#6A1CF6",
    "status": "active", "members": 44, "engaged_members": 40, "growth": 3, "score": 182.4,
    "joke_count": 24, "activity": [12, 9, 14, 20, 31, 28, 17],   // 7 days, oldest first
    "explanation": "40 people each enjoyed at least 2 Work jokes recently.",
    "viewer": null | {"affinity": 3.95, "content_count": 1, "inferred": false, "member": false,
                      "explicit": null | "joined" | "left", "progress": 0.66}
  }],
  "bridges": [{"source": "puns", "target": "tech", "members": 10}],  // ≥5 only, slugs sorted
  "methodology": {"half_life_days": 7, "membership_threshold": 6, "minimum_content": 2,
                  "minimum_members": 5, "content_cap": 4, "weights": {...}, "window_days": 90,
                  "minimum_display": 5, "description": "…", "established_account_days": 7,
                  "established_min_jokes": 3, "noise_epsilon": 1.0}
}
```

`members`, `engaged_members`, `stats.members`, `stats.multi_community_members`,
`bridges[].members`: day-stable noise, then nearest 5, `null` when the noisy value
is under 5 (so a `null` or a `5` no longer reveals the exact count). `growth`:
noised change in engaged members since a week ago, nearest 5, only for active
communities whose engaged count is shown. `viewer.counted` is `true` only for an
established, consenting account; `shares_analytics` tells a non-counted viewer
whether the missing piece is consent or account age/activity.

## GET `communities/<slug>/` — AllowAny

`{community, trending[6], newest[4], creators[≤6], bridges[]}`. Jokes are full
`JokeSerializer` payloads filtered by `allowed_tiers(request)` + `visible_jokes`
(removed / blocked hidden), trending ranked by 30-day positive engagement using
per-signal correlated subqueries (no join fan-out; anonymous shares excluded).
`creators` lists only active accounts with `public_profile=True`. 404 for unknown or
unlisted slugs.

## POST `communities/<slug>/membership/` — IsAuthenticated

Body `{"action": "join" | "leave"}` → the updated community row (with `viewer`;
status may lag by up to the refresh floor; person-counts come from the day's snapshot).
400 invalid action, 404 unknown slug. Throttle scope `community_membership`
(`THROTTLE_COMMUNITY_MEMBERSHIP`, default 60/hour).

## GET `creators/me/communities/` — Creator Pro

Permissions: `IsAuthenticated` + `IsCreator` (≥1 published joke) +
`HasFeature('creator_community_insights')` (enabled on `creator_pro` by
`billing/migrations/0010`). Throttle `creator_insights`. `Cache-Control: no-store`.

```jsonc
{
  "window_days": 90,
  "audience": {"size": 135 | null, "minimum": 5},
  "communities": [{"slug": "work", "name": "Work", "emoji": "💼", "color": "#…", "status": "active",
                   "members": 44, "joke_count": 24, "reached_members": 40, "reach_rate": 90.9,
                   "your_jokes": 5}],
  "opportunities": [{"kind": "stronghold" | "untapped" | "emerging", "slug": "puns", "name": "Puns",
                     "emoji": "🔤", "evidence": "24 readers form an active Puns community. 16 of them already enjoy your jokes, but you have not published for this theme yet.",
                     "action": "Try one Puns joke and tag it with the theme so this audience can find it."}],
  "measurement_notes": ["…"]
}
```

Audience = established, consenting adults (excluding the creator) with a
positive signal on the creator's tier_1 jokes in the window. `members` excludes
the creator. To stop a creator from matching a single new reader (e.g. with sock
accounts plus a "new follower" notification) the payload is a **daily snapshot**
(`snapshot_date`, UTC) and every count is released like a public count:
day-stable keyed noise (`creator-audience`, `creator-reached`; `members` reuses
the public `members` draw so extra creator accounts get no fresh samples of it),
nearest 5, `null` when the noisy value is under 5; `reached_members` ≤ `members`;
`reach_rate` is computed from the released numbers and floors to 5 % steps. Snapshot sets are intersected with **current** eligibility on every
read, so consent withdrawal or account deletion removes a reader immediately
(numbers can fall within a day, never rise). Opportunities are rule-based
descriptions of current evidence, never predictions.

## Account data

`GET users/me/data-export/` includes `community_memberships`
(`[{community, state, updated_at}]`). Inferred affinity is not stored;
`CommunitySignal` only mirrors reactions, favorites, saves and shares that the
export already contains. Account deletion cascades memberships and signals.

## Demo data

`python manage.py seed_showcase` (local-only guard: DEBUG + loopback Postgres +
filesystem storage). See `Docs/Showcase_Demo.md`.
