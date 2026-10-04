# Unified joke search

## Intended outcome

A reader can type a remembered joke, punchline, category, theme, or other public metadata into one prominent search field and find relevant published jokes. Search remains free and respects moderation, symmetric creator blocks, and age/mature-content access. The existing web app and shared API are the initial integration surfaces; native clients retain the existing API contract.

## Architecture decision

Extend the existing PostgreSQL full-text index and `/api/v1/jokes/?q=` endpoint. Store weighted search documents on each joke, indexed with GIN. Compose the document at write time using database triggers, including changes to many-to-many membership and taxonomy labels. This makes reads indexable without per-result relation scans and keeps bulk updates, admin edits, and publishing consistent.

Alternatives considered: adding relational `icontains` predicates is simpler but causes broad scans and weak relevance; a separate search service offers advanced typo/semantic ranking but introduces another service, synchronization failures, and operating cost. The current single-service PostgreSQL architecture does not need that complexity. PostgreSQL documents GIN as its preferred full-text index: https://www.postgresql.org/docs/15/textsearch-indexes.html.

## Search document and query

Content (`text`, `setup`, `punchline`, dialogue `lines`) has the highest weight. Public category/theme/culture/format/language/age-rating/source labels and slugs have the next weight; descriptions have lower weight. Private submissions, accounts, and unpublished drafts are never indexed by this public search. Media is searchable through its textual metadata, without inventing OCR or transcripts.

Coordinate with the concurrent international-discovery change: retain its English and language-neutral vectors. Each language uses the same configuration for indexing and querying; boolean exclusions must not be weakened by indiscriminately OR-ing configurations. Both vectors receive the complete weighted document. English stemming and existing web-search syntax (quoted phrases, OR, minus exclusions) remain available.

Normalize whitespace and limit input to 200 characters and 32 terms. Reject invalid control characters with a field-level `q` error. Empty input browses; punctuation-only search returns no matches. Rank results by relevance, then newest creation time and primary key for deterministic pagination. Preserve existing format/taxonomy/language filters and pagination response shape.

## Synchronization and migration

Refresh indexes on relevant joke content/FK edits, relation add/remove/clear, bulk through-table writes, and metadata rename/delete. Serialize refreshes on the target joke before reading related values to avoid overwriting a newer document with stale content. Avoid reindexing on unrelated counters or share-image writes. Backfill existing rows in the schema migration and provide a repair/rebuild command if needed. Document migration cost and rollback; deployment remains a separate step.

## Web experience

Use the existing Search route/navigation and visual language. Promote a labeled text field with submit and clear actions above optional filters. Persist committed query/filter values in the URL, debounce typing, and synchronize browser navigation. Use a query-key-scoped infinite query and abort obsolete requests. Scope cached results by account identity so results cannot carry across account changes. Reuse existing joke cards and their access behavior. Show real loading, error/retry, empty, and load-more states; never fill an empty search with unrelated mock results.

## Verification

Exercise every document source and mutation path in real PostgreSQL, plus stemming, phrase/boolean behavior, query limits, ranking, pagination, access rules, and migration consistency. Verify frontend URL/debounce/cancellation/pagination behavior with a real QueryClient, build the app, and inspect desktop/mobile interaction against the real API. Use an isolated local database, always overriding `DATABASE_URL=''`. Measure representative search plans and latency using synthetic data; report local measurements as local evidence, not production guarantees.
