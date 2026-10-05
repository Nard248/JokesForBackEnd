# Unified search verification — 27 September 2026

## Delivered behavior

The existing web Search screen now prioritizes one text input covering joke content, punchlines, dialogue, categories, themes, and public classification/source metadata. Optional filters and language/country/culture selection compose with it. Search text and filters survive URL navigation; pagination is scoped to query/account/locale, and obsolete requests are cancelled. Saved search retains the caller's visibility constraints.

The existing PostgreSQL GIN indexes now serve weighted English and language-neutral documents. Database triggers maintain the documents for content, bulk writes, M2M changes, and taxonomy edits. Source-column writes preserve database-derived vectors against stale model-instance values. No additional service, queue, worker, dependency, or production data change was introduced.

## Automated verification

- Full backend suite on a freshly migrated isolated PostgreSQL database: **Ran 1119 tests in 124.135s — OK (skipped=1)**.
- Final combined frontend Vitest suite, including the concurrent locale-clear correction: **126 test files, 900 tests passed**.
- Real desktop/mobile browser tests against the API: **7 passed in 17.5s**, including paused-space typing, punchline/category matches, filter composition, empty results, URL/history, pagination reset, and 44-pixel mobile controls without horizontal overflow.
- Production frontend build: **passed**. Existing bundle-size warning remains; the optional sitemap fetch used its unavailable local default API and emitted a warning.
- Backend Ruff: **All checks passed**.
- Frontend ESLint: **0 errors, 22 existing warnings** across the shared checkout.
- Migration drift check: **No changes detected**.
- Independent review reproduced and led to fixes for stale model saves overwriting vectors and debounce replacement dropping trailing spaces. Regression coverage now exercises both cases, including multiword typing focus/caret and browser history.

Search coverage includes weighted relevance, deterministic ties, every indexed text source, English stemming, non-English token matching, boolean/phrase queries, query limits, negative-only scan prevention, M2M add/remove/clear/bulk writes, metadata renames/deletes, concurrent relation changes, migration replay, repair, category/theme aliases, moderation, symmetric blocks, and adult/minor access.

All backend commands explicitly cleared `DATABASE_URL` and used an isolated PostgreSQL 15.15 cluster on `127.0.0.1:55443`. Production was not migrated or queried. Concurrent multilingual work shares the checkout and is included in the full-suite totals; this search feature preserves its selectors and indexed fields.

## Performance evidence

A transaction inserted 50,000 synthetic English jokes, populated both vectors using live triggers, added category memberships, and ran `ANALYZE`. Fifty records matched the selective content term; fifty matched the category term. Ten repeated count-plus-first-page queries were timed. All synthetic data was rolled back afterward.

| Query | Matches | Median count + first page | PostgreSQL page execution |
|---|---:|---:|---:|
| Selective content | 50 | 3.54 ms | 1.372 ms |
| Selective category metadata | 50 | 3.96 ms | 1.333 ms |
| Common content term | 50,000 | 36.01 ms | 25.204 ms |
| Exclusion only | 0 | 0.90 ms | 0.011 ms |

`EXPLAIN (ANALYZE, BUFFERS)` confirms bitmap scans of `joke_search_vector_idx` and `joke_simple_search_idx` for selective queries. Exclusion-only search simplifies to a zero-row Result plan. Removing unnecessary wide-row DISTINCT from searches without M2M filter joins reduced the broad-query local median from approximately 114 ms to 36 ms; M2M-filtered searches still deduplicate correctly.

These are warm local measurements, not production latency promises. They exclude HTTP transport, serializers, browser rendering, cold starts, and network/database contention. Broad matches necessarily perform more work than selective lookups. Raw final query plans are in `2026-09-27-unified-search-benchmark.json` beside this report. The final stale-save guard changes writes only and does not alter the measured read query plans.

## Rollout

Apply the normal database migrations before deploying the updated API and web app. Search migration `0041_unified_joke_search` depends on international-discovery migrations `0039`/`0040`, retains existing GIN indexes, and backfills in batches of 500. `rebuild_search_index` repairs documents in bounded batches. Search remains usable by existing API/native clients; the native iOS interface was outside this task's agreed scope.

See `Docs/API/Unified_Search.md` for query behavior, index maintenance, migration rollback, and operational limits. This work is implemented and locally verified; production deployment is pending.
