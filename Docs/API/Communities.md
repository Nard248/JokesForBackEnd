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
only active adults with `share_analytics` (`creator_insights.privacy.eligible_analytics_users`),
and only signals recorded **after** that person's latest opt-in
(`AnalyticsConsentRecord`; consent is never applied backwards). Signals only from
`tier_1`, non-removed jokes. Public person-counts (members, engaged members,
bridges, stats, growth) are rounded to the nearest 5 and are `null` under 5;
`activity` and `score`
are `null` while fewer than 5 people contributed in the last 7 days. No response
contains user ids, names or samples. A person's own affinity is computed from
their own activity and returned only to them. Explicit joins by people who do not
share analytics change only their own view.

Request-triggered only. The aggregate is cached without TTL
(`communities:aggregate:v2`) behind an opaque, never-reused version (a culled
version key forces a recompute) and a 1-hour hard max age; engagement writes and
profile saves replace the version
**after commit** (`communities/signals.py`; anonymous shares are ignored). A stale
entry is recomputed at most every `COMMUNITIES_MIN_REFRESH_SECONDS` (default 10)
by one lock holder while others serve the previous state, so engagement bursts
cannot force recomputation. Scaling path: materialize per-(user, community)
scores incrementally; engine inputs unchanged.

**Residual risks (accepted 2026-10-04, documented):**
- Formation is Sybil-sensitive — five consenting accounts can activate a theme.
- Deterministic coarsening still leaks at rounding boundaries: an attacker with
  sock accounts can sometimes detect one additional counted member. Layers in
  place: 5-person threshold, rounding to 5, refresh floor, daily creator
  snapshot, consent gating, no identities. Fully closing this needs calibrated
  noise (differential privacy).
Both are acceptable while communities grant no privileges and expose no member
lists; revisit before community feeds, conversations or member directories.

## GET `communities/` — AllowAny

```jsonc
{
  "generated_at": "2026-10-04T11:43:50Z",
  "stats": {"active_communities": 12, "forming_communities": 1, "members": 150,
            "multi_community_members": 57, "signals_7d": 1867},
  "viewer": null | {"counted": true, "communities": ["puns", "space"]},
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
                  "minimum_display": 5, "description": "…"}
}
```

`members`, `engaged_members`, `stats.members`, `stats.multi_community_members`,
`bridges[].members`: nearest 5, `null` under 5. `growth`: nearest 5, only for
active communities with ≥5 engaged a week ago.

## GET `communities/<slug>/` — AllowAny

`{community, trending[6], newest[4], creators[≤6], bridges[]}`. Jokes are full
`JokeSerializer` payloads filtered by `allowed_tiers(request)` + `visible_jokes`
(removed / blocked hidden), trending ranked by 30-day positive engagement using
per-signal correlated subqueries (no join fan-out; anonymous shares excluded).
`creators` lists only active accounts with `public_profile=True`. 404 for unknown or
unlisted slugs.

## POST `communities/<slug>/membership/` — IsAuthenticated

Body `{"action": "join" | "leave"}` → the updated community row (with `viewer`;
aggregate counts may lag by up to the refresh floor).
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

Audience = eligible adults (excluding the creator) with a positive signal on the
creator's tier_1 jokes in the window. `members` excludes the creator. To stop a
creator from matching a single new reader (e.g. with sock accounts plus a "new
follower" notification) the payload is a **daily snapshot** (`snapshot_date`, UTC)
and counts are coarsened: `reached_members` and `audience.size` floor to multiples
of 5, `members` rounds to the nearest 5, `reach_rate` floors to 5 % steps; under 5
is `null`. Snapshot sets are intersected with **current** eligibility on every
read, so consent withdrawal or account deletion removes a reader immediately
(numbers can fall within a day, never rise). Opportunities are rule-based
descriptions of current evidence, never predictions.

## Account data

`GET users/me/data-export/` includes `community_memberships`
(`[{community, state, updated_at}]`). Inferred affinity is not stored; account
deletion cascades memberships.

## Demo data

`python manage.py seed_showcase` (local-only guard: DEBUG + loopback Postgres +
filesystem storage). See `Docs/Showcase_Demo.md`.
