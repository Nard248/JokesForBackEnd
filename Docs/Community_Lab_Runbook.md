# Run the self-forming communities demo

This demo uses synthetic people, jokes, and events. Its PostgreSQL database, settings, API, UI entry point and ports are separate from the active creator portal work. It does not read production content or infer interests for real accounts.

## Source repositories and runtime

- Backend: `/Users/narekmeloyan/PycharmProjects/JokesForProject`.
- Frontend: `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend`.
- Local PostgreSQL: `community_lab`, socket `/private/tmp/jokesfor-communities/pgsocket`, port `55437`, role `community_demo`.
- API: `http://127.0.0.1:8017/api/v1/community-lab/snapshot/`.
- UI: `http://127.0.0.1:5187/communities.html`.

The implementation now lives directly in these repositories and uses their existing `.venv` and `node_modules` dependencies. The initial prototype is also preserved on the `codex/self-forming-communities` branches. The temporary directory is only required for the dedicated database runtime; the launcher can recreate it. The source no longer depends on the prototype worktrees.

## Start

Requires the project's existing Python/Node dependencies and PostgreSQL executables on PATH. In one terminal:

```sh
cd /Users/narekmeloyan/PycharmProjects/JokesForProject
bash scripts/community-lab.sh serve
```

The launcher initializes the dedicated cluster if absent, starts it only when needed, migrates the demo app and seeds only an empty demo. It deliberately ignores `DATABASE_URL` and never sources `.env`. It fails instead of moving to another API port.

In another terminal:

```sh
cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend
npm run dev:communities
```

Open `http://127.0.0.1:5187/communities.html`. Both HTTP servers listen on loopback only. PostgreSQL uses local trust authentication for synthetic demo data and is not a deployment configuration.

## Try the complete loop

1. Select an emerging subject and inspect why it has not formed yet.
2. Share one of its jokes. The demo records your share, attributed friend engagement, and follow-on enjoyment of similar content.
3. Inspect the subject's participant count, formation state, activity stream, and graph. Multiple distinct people enjoying multiple jokes establish an active community.
4. Join a community explicitly, then leave it. Reload to confirm that your choice persists.
5. Simulate more activity or advance seven days to see the balance between growing interests and decaying evidence.
6. Explore overlaps between topics. The drawn member nodes are a sample; aggregate counts represent the full synthetic population.

## Verify

```sh
cd /Users/narekmeloyan/PycharmProjects/JokesForProject
bash scripts/community-lab.sh test
DATABASE_URL='' .venv/bin/python -m django makemigrations --check --dry-run --settings=community_lab.settings
.venv/bin/ruff check community_lab

cd /Users/narekmeloyan/WebstormProjects/jokes-for-frontend
node_modules/.bin/tsc --project tsconfig.communities.json --incremental false
npm run build:communities
node_modules/.bin/eslint src/features/communities vite.communities.config.ts playwright.communities.config.ts e2e/community-lab.e2e.ts
npm run test:communities
# Requires both demo HTTP servers to be running; exercises real PostgreSQL.
npm run e2e:communities
```

These commands target the dedicated community subsystem. Ordinary Django discovery skips the community database suite unless `community_lab.settings` is selected; its pure scoring tests can run in either suite. Community browser tests use a dedicated `.e2e.ts` suffix so the normal application suite does not run them against the main API. Browser tests intentionally change synthetic state; reset before a presentation if desired.

### Verified on 2026-09-27

- Django: `Ran 29 tests in 1.649s` / `OK`.
- UI components: `Tests 8 passed (8)`.
- Browser-to-PostgreSQL integration: `6 passed (5.3s)`.
- App TypeScript check, changed-file ESLint, community Ruff, standalone Vite production build, and migration consistency check passed.
- Desktop and 390-pixel mobile layouts inspected; browser has no uncaught page errors and no horizontal page overflow.
- A share changed Space oddities from forming to active. Replaying the same request did not add events. Membership choices survived reload. Advancing seven days halved all subject scores and persisted the clock.
- Eight sequential local snapshot reads at the seeded scale measured 78 ms median and 91 ms maximum. This is a local responsiveness check, not a production load test. The projection uses six database queries and currently reads the entire synthetic event ledger; production ingestion needs incremental aggregation.
- Independent review found no remaining blocking issues after fixing historical membership ordering, hostile IDs, repeated-reaction trending inflation, and sampled-graph labeling/focus.

The presentation dataset was restored after verification: 1,600 people, 216 jokes, 13,472 events, eight active subjects and one forming subject. The graph draws 240 sampled people plus nine subject nodes.

### Integration into the main repositories

- Ordinary Django suite: `Ran 1003 tests in 108.962s` / `OK (skipped=2)`, using the dedicated local cluster at `127.0.0.1:55437` with a separate `test_jokesfor_community_integration` database. The loopback host is required by the existing creator seed command's safety guard.
- Ordinary frontend suite: `Test Files 115 passed (115)` / `Tests 833 passed (833)` after the source transfer.
- Community backend suite from the main directory: `Ran 29 tests in 1.800s` / `OK`.
- Ordinary browser discovery remains at 38 tests; the six community browser checks are collected only by `npm run e2e:communities`.
- Community Ruff and changed-file frontend lint pass. Whole-repository backend Ruff reports an existing unused `Format` import in `jokes/tests_submit_language_default.py:13`; this unrelated creator test was left unchanged.
- The pre-existing backend `.gitignore` edits and other local files were preserved.

### App visual standards verification

- The community entry imports the shared application stylesheet, fonts and logo. It uses the Flow background, purple pill controls, lime joke cards, app spacing and card radii; feature overrides stay scoped to community roots.
- After the visual alignment, the dedicated TypeScript/build check, changed-file ESLint and eight component tests passed. The six browser-to-PostgreSQL tests passed in 13.2 seconds from the canonical repositories.
- Desktop, tablet and 375-pixel mobile layouts have no horizontal overflow. All visible mobile buttons and links meet the 44-by-44-pixel touch target, search is 52 pixels high, the methodology dialog closes with Escape, and header anchors clear the sticky header.
- Concurrent creator work continued after the full-suite integration checks above. The latest whole-app TypeScript check reports `TS2698` in `src/pages/CreatorLibraryPage.test.tsx:28`; that file belongs to the parallel work and was preserved. The community TypeScript/build check passes independently. Whole-app suite results above describe the tested snapshot, not subsequent parallel edits.
- The synthetic presentation dataset was reset after the browser checks.

## Reset and stop

Reset only the synthetic demo data:

```sh
cd /Users/narekmeloyan/PycharmProjects/JokesForProject
DATABASE_URL='' .venv/bin/python -m django seed_community_lab --reset --settings=community_lab.settings
```

Stop each HTTP server with Ctrl-C in its terminal. When no demo server or tests are using it, stop the dedicated database:

```sh
pg_ctl -D /private/tmp/jokesfor-communities/pgdata stop
```

## Boundaries

This implements topic-centered community formation, decay, explicit membership choices, a sampled graph and persisted simulation. Subject names are seeded; this is not an unsupervised topic-discovery or automatic merge/split system. There is no real-user messaging, moderator replacement, production ingestion, production auth, or creator analytics coupling. The graph exposes synthetic people only. See `Community_Lab_Design.md` for the production adapter boundaries and `Community_Lab_Product_Notes.md` for the product hypothesis.
