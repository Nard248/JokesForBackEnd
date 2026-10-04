# International discovery implementation plan

**Goal:** Make multilingual and cultural joke discovery consistent across the app, backed by an auditable corpus importer.

**Architecture:** Extend existing taxonomy, centralize explicit discovery filtering, expose a catalogue and keep frontend URL/persistent state in sync. Validate and import authored corpus files separately from schema migrations.

**Tech stack:** Django/DRF/PostgreSQL; React/TypeScript/TanStack Query/Zustand.

**Spec:** `Docs/superpowers/specs/2026-09-27-international-discovery-design.md`.

## Constraints and review focus

- Preserve tier, paywall, moderation and symmetric block checks.
- Never let daily caches or frontend placeholder pages cross a selected language/country/culture.
- A country is context, not an inferred speaker identity; do not treat Eastern/Western Armenian interchangeably.
- Safe local database environment is mandatory; no production import during development.
- Duplicate text, changed stable keys, removed records, unknown taxonomy and partial target coverage must be observable.

## Tasks

- [x] Backend: tests for selector consistency and language search; models/migrations, shared discovery helper, catalogue endpoint, discovery read paths, serializer/admin and submission propagation.
- [x] Frontend: tests for URL/persistence, accessible controls and reset pagination; discovery feature module, Flow shell, browse/search/cache keys, daily and random requests, content `lang`, creator classification.
- [x] Importer and initial corpus: validator/importer/tests, manifest, and 1,000 authored draft records; verified local import and reimport. The expansion below fills the initial per-category deficits.
- [x] Research: cross-language primary-source memo plus six expanded country briefs, including neighbour contexts, language variants, provenance and native-review boundaries.
- [x] Integration: actual catalogue and selector API tests, frontend build/test/lint and backend suite/lint/migration drift, real browser verification; evidence in `Docs/Testing/2026-09-27-international-discovery.md`.
- [x] Complete corpus: six main collections (10,800 total; exactly 200 in each of nine categories), strict authored/installed/context coverage passed, strict reimport unchanged, and populated API/browser checks passed.

## Execution record

- Existing backend and frontend branches are `codex/creator-business-model`; unrelated backend changes are preserved. No commits or branch changes have been made for this task.
- Ruflo/ToolSearch capabilities are absent from the available tool inventory; native collaboration tools are used.
- The configured Obsidian skill environment `~/.obsidian-Codex.env` is absent; in-repository documents serve as the session record until vault sync is available.
- The owner supplied France, Armenia, Italy, Germany and Norway, delegated cultural-topic choices, and requested neighbour humour. Spain remains for the earlier Spanish requirement. Austria/Sweden/Finland are secondary joke contexts. No further scope answer is pending for this matrix.
- Native collaboration has four active slots including the root; all are used. The request for 100 simultaneous agents exceeds this environment's capacity. Authorship is split by language and category, with independent files and rebalanced ownership as batches finish.
- Concurrent search task coordinated ownership of `managers.py`, `search.py`, `search_index.py`, migration 0041, and shared frontend search files. Exact collection triples were added in migration 0042 after review identified false Cartesian combinations.
- Final combined checkout verification: backend `Ran 1119 tests in 124.135s — OK (skipped=1)`; frontend `126 files / 900 tests passed`; Vite build passes; backend Ruff clean; frontend lint 0 errors and 22 existing warnings; migration check reports no changes. Three international browser checks passed, plus manual populated-collection switching and actual API checks.
- Final corpus-expansion verification: 49 focused backend tests and 9 frontend tests passed; fresh TypeScript/Vite build, Ruff and migration check passed. Actual API verified all 54 category counts and six 1,800-record collections. Actual browser verified all six presets, neighbour routes, persistence/clear and 375/768/1280 layouts without page errors. Strict reimport created zero and preserved 10,800. Detailed evidence is in `Docs/Testing/2026-09-27-international-discovery.md`; the broader combined-suite numbers above are from the earlier integration phase.
