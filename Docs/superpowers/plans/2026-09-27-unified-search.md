# Unified Search Implementation Plan

**Goal:** Find jokes by content and public metadata through one integrated search box.

**Architecture:** Extend the stored PostgreSQL vectors and GIN indexes. Database triggers maintain denormalized documents; the existing DRF endpoint enforces visibility and returns paginated results. React Query owns query-specific result pages.

**Tech stack:** Django 5.2, PostgreSQL 15, React 19, TanStack Query 5, TypeScript.

**Spec:** `Docs/superpowers/specs/2026-09-27-unified-search-design.md`.

## Constraints

- Preserve concurrent international-discovery changes and existing API response contracts.
- Use the existing PostgreSQL service; no worker, Redis, external search dependency, or production database writes.
- Queries: 200 characters, 32 terms; server-side visibility is authoritative.
- Keep the web UI accessible and responsive, with existing joke cards and navigation.

## Work packages

1. **Index and query engine** — `jokes/search.py`, index SQL module, search migration, `jokes/models.py`, `jokes/managers.py`, `jokes/tests_search.py`. Write regression tests, implement weighted database-maintained vectors and normalization, backfill, run real PostgreSQL tests and migration-drift checks. Coordinate migration dependency on the international-discovery schema.
2. **API boundaries** — `jokes/views.py`, `jokes/tests_search_api.py`. Document the expanded query, validate `q`, preserve existing filters/access, and apply symmetric block visibility to saved search. Test anonymous/adult/minor, removed/prohibited, both block directions, pagination, and input errors.
3. **Web search** — frontend `SearchPage.tsx`, `features/jokes/api.ts`, transport/adapter, mock API, corresponding tests. Promote the text box, synchronize URL state, add abortable infinite search, account-specific keys, optional filters, and truthful empty/error states. Verify race conditions and build/lint.
4. **Integration and evidence** — PostgreSQL query-plan/scale probe, real API/browser checks, focused regression suites, API/runbook documentation and verification report. Review final shared diff without overwriting unrelated task edits.

## Review focus

- Many-to-many removal and metadata rename must remove stale terms.
- Old or aborted responses must never appear under a different query or account.
- Negative/phrase query semantics must hold for each language configuration.
- Hidden content must not leak through counts, saved search, or metadata matches.
- Existing data must be searchable immediately after migration, and the index must be usable at scale.
