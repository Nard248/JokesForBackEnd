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

**Population (privacy line):** aggregates use only adults with `share_analytics`
(`creator_insights.privacy.eligible_analytics_users`), plus adults who explicitly
joined. Signals only from `tier_1`, non-removed jokes. Counts under 5 are
returned as `null`. No response contains user ids, names or samples. A person's
own affinity is computed from their own activity and returned only to them.

Request-triggered only: the aggregate is computed over the bounded window and
cached (`communities:aggregate:v1`, 300 s). Reactions, favorites, saves, shares
and profile saves invalidate it (`communities/signals.py`). Scaling path:
materialize per-(user, community) scores incrementally; engine inputs unchanged.

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

`members`, `engaged_members`, `stats.members`, `stats.multi_community_members`:
`null` under 5. `growth`: only for active communities with ≥5 engaged a week ago.

## GET `communities/<slug>/` — AllowAny

`{community, trending[6], newest[4], creators[≤6], bridges[]}`. Jokes are full
`JokeSerializer` payloads filtered by `allowed_tiers(request)` + `visible_jokes`
(removed / blocked hidden), trending ranked by 30-day positive engagement.
`creators` lists only accounts with `public_profile=True`. 404 for unknown or
unlisted slugs.

## POST `communities/<slug>/membership/` — IsAuthenticated

Body `{"action": "join" | "leave"}` → the updated community row (with `viewer`).
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
creator's tier_1 jokes in the window. `members` excludes the creator. Reach and
audience under 5 are `null`. Opportunities are rule-based descriptions of
current evidence, never predictions.

## Account data

`GET users/me/data-export/` includes `community_memberships`
(`[{community, state, updated_at}]`). Inferred affinity is not stored; account
deletion cascades memberships.

## Demo data

`python manage.py seed_showcase` (local-only guard: DEBUG + loopback Postgres +
filesystem storage). See `Docs/Showcase_Demo.md`.
