# Self-forming communities demo

## Purpose

Build a working JokesFor audience-side demo where shared jokes and positive engagement form overlapping subject communities. Show the graph, community explanations, statistics, activity, trending content, and a reproducible sharing cascade. Synthetic data must be clearly labeled. This is a new subsystem and an experimental hypothesis, not a claim of novel graph science or a production rollout.

## Isolation

The backend lives in `community_lab/` in `/Users/narekmeloyan/PycharmProjects/JokesForProject`; the frontend lives in `src/features/communities/` in `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend`. The original prototype checkpoints remain on the `codex/self-forming-communities` branches. Integration is additive and preserves the creator portal implementation and existing local edits. Runtime isolation remains: a dedicated local PostgreSQL cluster on port 55437, Django server on 8017, and Vite on 5187. No production secrets or `.env` loading. No new dependencies. Demo settings install only the community app; production settings and routes do not expose synthetic actions.

## Behavior

Canonical subjects prevent duplicate groups about identical topics. Users can belong to multiple communities; overlapping interests create bridges. Positive actions create weighted affinity that decays with a seven-day half-life. Repeated actions on identical content cannot amplify affinity without bound. At least two distinct jokes and a minimum score are required for inferred membership; at least five independently engaged participants form an active community. Watching alone and the act of sending a share alone cannot establish recipient membership. An explicit join is separate from inferred affinity. Leaving overrides inference until the person joins again. The graph is a capped sample of anonymous synthetic participants; full aggregate counts must be labeled separately.

The simulator records sender actions and independently attributed recipient reactions. It does not imply that production share events provide this attribution. A rare subject starts below threshold so a share cascade can visibly turn it into an active community. Activity and trends come from persisted events. The browser reads the backend; no client-generated random statistics or success fallbacks.

## API contract

Base: `/api/v1/community-lab/`. GET `snapshot/` sets a CSRF cookie and returns the shape below. POST `simulate/` accepts `{subject_id?: string, steps: integer (1..100)}`. POST `share/` accepts `{content_id: string, event_id: string}` and creates a demo-you share plus a bounded attributed synthetic friend cascade. POST `membership/` accepts `{subject_id: string, action: 'join'|'leave'}`. POST `advance/` accepts `{days: integer (1..30)}` to demonstrate decay. All mutations return the updated snapshot and enforce CSRF. Browser identity is fixed to the synthetic demo participant; arbitrary actors are rejected. Demo write operations cannot be enabled by importing URLs under production settings.

```typescript
type Snapshot = {
  meta: {is_demo: true; simulated_at: string; revision: number; sampled_nodes: number; total_members: number; caption: string};
  stats: {participants: number; active_communities: number; emerging_communities: number; interactions: number; shares: number; bridges: number};
  viewer: {id: string; name: string};
  subjects: {id: string; name: string; description: string; color: string; emoji: string; members: number; active_members: number; growth: number; score: number; status: 'forming'|'active'|'cooling'; joined: boolean; affinity: number; explanation: string; activity: number[]}[];
  graph: {nodes: {id: string; kind: 'subject'|'member'; subject_id: string; label: string; color: string}[]; edges: {source: string; target: string; weight: number; kind: 'affinity'|'bridge'}[]};
  activity: {id: string; actor: string; kind: string; subject_id: string; subject_name: string; content_title: string; created_at: string; description: string}[];
  content: {id: string; subject_id: string; title: string; punchline: string; format: string; creator: string; likes: number; shares: number; trending_score: number}[];
  methodology: {half_life_days: number; membership_threshold: number; minimum_members: number; minimum_content: number; weights: Record<string, number>; description: string};
};
```

IDs are strings. Graph subject node IDs equal subject IDs. A member may connect to multiple subject nodes; graph coordinates are a stable presentation concern for the frontend. Growth is a signed integer change in engaged members against the prior seven-day window, not a fabricated percentage. `activity` arrays contain seven daily event counts. `score` is aggregate decayed subject affinity. `affinity` is the demo viewer's decayed score. The optional `steps` controls simulated event batches, not real time.

## Visual direction

Use the existing JokesFor Flow visual system from `src/index.css`: Epilogue display typography, Plus Jakarta Sans body copy, Fraunces editorial emphasis, warm `#FBFAF7` background, `#6A1CF6` primary controls, `#E9E8E7` borders and the actual `appicon_purple.svg` brand asset. Match the app's pill buttons, 16–20px cards, readable labels, 1200px content cap and responsive breakpoints. A large pale graph canvas remains the central experience; the community filter pane is content navigation, not a competing application brand. The inspector, trending jokes and activity ledger follow the existing card and spacing conventions. Scope feature CSS to community roots, including its dialog, so importing the feature cannot restyle creator pages. Actual SVG nodes respond to selection, filtering and zoom; lists provide keyboard alternatives. Show loading, errors, empty results, disabled pending mutations, reduced motion, and mobile layout with 44px touch targets.

## Verification and implementation plan

1. Backend: write meaningful Django tests first for formation, duplicate-event handling, diversity, decay, overlap, explicit leave, input bounds, CSRF, persistence and disabled production settings. Implement separate models, scoring service, snapshot projection, seed command, migration, settings and endpoint handlers in `community_lab/`.
2. Frontend: implement `src/features/communities/`, a standalone `communities.html` entry and `vite.communities.config.ts`; preserve the existing SPA. Read this contract and use real API calls. Provide graph selection/zoom, community search, join/leave, sharing, simulation, time advancement, and content/activity tabs. Add targeted tests for meaningful user behavior.
3. Integration: seed approximately 1,600 synthetic participants, 200+ original joke entries, and enough persistent actions to form several distinct and overlapping communities. Start dedicated services. Verify the complete browser-to-PostgreSQL loop, reload persistence, keyboard interactions, and mobile rendering. Run the demo suite, frontend type check/build and changed-file lint.
4. Review: independent assessment of aggregation correctness, write boundaries and integration gaps. Record exact run commands and limitations. Preserve prototype checkpoints, integrate the module into the canonical repositories, and show a running local demo.

## Production follow-up

An adapter should reuse `ContextTag` for subjects, existing auth and visibility filters, and permissioned activity signals. Production shares currently lack recipient attribution. Public graphs must never disclose inferred private interests or social edges. Discovery consent, membership visibility, content reports, abuse resistance, moderation, and retention policy need product decisions before real-user rollout. Topic-centered affinity communities are the first hypothesis; unsupervised discovery of new subjects or automatic merge/split behavior is outside this demo.
