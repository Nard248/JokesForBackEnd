# Unified search

`GET /api/v1/jokes/?q=coffee` returns the existing `{count, next, previous, results}` response. Authentication is optional. The endpoint applies content tiers, takedowns, and symmetric creator blocks before counting or serializing results.

## Searchable material

- Joke text, setup, punchline, and knock-knock dialogue.
- Category and theme names, slugs, and descriptions.
- Format, age-rating, culture, language, country, and source labels and descriptive metadata, including native names where available.
- Cultural context notes.

Joke content has weight A, classification labels weight B, and descriptions weight C. The stored English and language-neutral PostgreSQL vectors are indexed with GIN. English jokes use English stemming; other languages use the simple configuration. Audio/video pixels or speech are not transcribed or indexed automatically.

## Query rules

The `q` parameter accepts at most 200 characters and 32 word tokens. Whitespace is normalized. Unsupported control characters, including NUL, produce HTTP 400 with a `q` error. Empty input browses the catalog. PostgreSQL web-search syntax supports quoted phrases, `OR`, and `-excluded` terms; punctuation is treated safely. Queries without an indexable positive restriction return no matches. This includes exclusion-only queries and expressions such as `coffee OR -work`, whose negative branch would otherwise scan the whole catalog.

Examples:

```text
/api/v1/jokes/?q=coffee
/api/v1/jokes/?q=astronaut%20puns
/api/v1/jokes/?q=%22cross%20the%20road%22
/api/v1/jokes/?q=coffee%20-work
/api/v1/jokes/?q=coffee&categories=dad-jokes&themes=work
```

With a query, default ordering is relevance, creation date, then primary key. Without a query, newest jokes come first. `ordering=-created_at` and `ordering=popularity` remain supported. Pagination uses the existing server page size and `next` link. Do not assume client `page_size` requests override server limits.

Filters compose with text search: `joke_format`, `age_rating`, `categories` (alias `tones`), `themes` (alias `context_tags`), `culture_tags`, `language`, `country`, and `vibe`. Category/theme aliases take precedence over their legacy names when both are present. Comma-separated taxonomy selections are a union within that axis; separate axes intersect. Explicit language/country/culture selections never silently fall back to another catalog.

`GET /api/v1/saved-jokes/search/?q=...` uses the same indexed documents and validation but requires authentication and a nonempty query. It restricts matches to the caller's saved and visible jokes, preserving saved-list ordering and the nested saved-joke response.

## Index maintenance and rollout

Migration `0041_unified_joke_search` depends on the international-discovery schema/metadata migrations. It replaces the old content-only triggers, installs database functions/triggers for both vectors, and backfills existing jokes in batches of 500. It uses the existing GIN indexes. No external service, worker, cache, or environment setting is required.

The database maintains documents for model and bulk writes, related-row add/remove/clear, and public metadata rename/delete. A BEFORE trigger preserves database-owned vectors against stale values in ordinary full Django model saves; the AFTER trigger rebuilds only when source values actually change. Unrelated fields such as share-card paths do not trigger rebuilding. A metadata rename can refresh every linked joke, so large taxonomy edits are write-heavy. Concurrent conflicting metadata edits may produce a PostgreSQL deadlock; the caller must retry the complete aborted transaction. No partially indexed transaction commits.

After deployment migrations, a repair is available through:

```sh
python manage.py rebuild_search_index --batch-size 500
```

For local commands always set `DATABASE_URL=''` and explicit local `DB_*` values; the developer dotenv may reference production. The repair includes removed rows so a later moderation restore has a current document, but default public queries still exclude them.

The migration rollback reinstates the former content-only trigger behavior. A large backfill takes database time; test on representative staging data and run normal migration/deployment observability. Search does not promise typo correction, semantic similarity, accent folding, or language-specific stemming beyond English.

## Web integration

`/search?q=...` is the canonical screen. Typing commits after 300 ms; Enter submits immediately. Optional format/category/theme filters and locale selection refine the result set. Query and filters live in the URL. React Query isolates pages by query, filters, locale, and account identity and aborts obsolete requests. The UI reports empty/error/loading states without inserting unrelated results.
