# International joke discovery

The reader chooses the language of the joke, its country context, and an optional cultural collection. These are independent descriptors, not nationality or ethnicity inferred from a person. Explicit filters intersect and never silently fall back to English. Existing unfiltered API clients remain compatible.

The requested languages initially were Spanish, French, German, Armenian, and Italian. The owner subsequently named France, Armenia, Italy, Germany and Norway, delegated cultural-topic selection, and requested neighbour humour involving Norway/Sweden/Finland and Germany/Austria. The implementation matrix has six main country/language collections: France/French, Armenia/Eastern Armenian, Italy/Italian, Germany/German, Norway/Bokmål, and retained Spain/Spanish. Each targets **200 distinct records in each of nine primary categories**: `wholesome`, `office-proper`, `dad`, `kid-safe`, `nerd`, `surreal`, `dark`, `edgy`, and `puns`. This is 10,800 records. No template substitutions or indiscriminate multi-tagging count as distinct editorial work.

Austria, Sweden and Finland are individually tagged neighbour contexts, not additional quota collections or native Swedish/Finnish editions. Regional research informs specific scenes and cultural notes; the release does not claim exhaustive 200-per-category coverage of every subculture within each country. Extra country tags never grant extra primary collection/category credit.

## Selected approach

Extend existing `Language` and `CultureTag` rather than introducing competing taxonomies. Add `Country`, country associations, native display names, and associations describing the languages/countries a cultural collection covers. Initial catalogue entries describe Spain, France, Germany, Armenia (Eastern Armenian), and Italy. This establishes baseline metadata, not a claim that each language belongs to one country. Western Armenian is a separate language code (`hyw`) when commissioned, not a country-derived translation of `hy`.

An alternative single locale dropdown would conflate language and country. A fully automatic translation service would miss wordplay and invent cultural equivalence. We use explicit authored texts and metadata instead. The interface language remains separate from content selection.

## Backend and API

- Additive joke fields: `countries`, `seed_key` (unique nullable stable import key), `cultural_note`, and `editorial_status` (`legacy`, `generated`, `native_reviewed`). Existing rows remain `legacy`; generation never claims native review.
- `GET /api/v1/discovery-locales/` returns `languages`, `countries`, `cultures`, and `collections`. Country records include `language_codes`; culture records include `language_codes` and `country_codes`; collections expose actual viewer-visible `joke_count`.
- Discovery requests accept `language`, `country`, and comma-separated `culture_tags`. Apply them to browse, search, random, today/tomorrow, and mystery-box pools. Revalidate cached daily selections. Preserve existing content-tier, block, removal and paywall behavior.
- Preserve English search stemming and add a consistent simple-vector path for other languages. Unicode text remains intact; language analysis must match indexing and querying.
- Extend creator metadata and publication paths for country context. Keep native authentication compatible.

## Reader experience

Place accessible selectors in the actual Flow shell. Use native language names and explicit country/culture labels, with “all” states; do not use flags as language names. Persist content preferences in the browser. URL parameters take precedence for shared links. Include selector state in request/cache keys, reset accumulated pagination, and never display placeholder results from a previous language. Display empty collections honestly. Mark joke text with its language for screen readers.

## Corpus and importing

Use UTF-8 JSON with a versioned manifest and explicit collection/category targets. Each authored record has one primary category, a stable identifier, language, country, culture, text/format, age rating, themes, and a cultural note. Corpus provenance is generated original material with no claimed external origin or native review. Research sources explain context; they do not license copying their jokes.

The importer validates the whole bundle before writing, normalizes Unicode for duplicate detection, rejects duplicate keys/text and unknown taxonomy, reports unique counts and deficits for every target, and offers a no-write dry run. Imports are atomic and idempotent, use bulk creation rather than per-joke image rendering, and never revive moderated content or overwrite edited rows. Completeness can be required explicitly. Imported generated content is inspectable locally; production rollout remains a separate operation.

## Verification and boundaries

Verify mixed selectors, empty/mismatched filters, daily cache isolation, Unicode search, native script preservation, actual catalogue counts, API paywall/tier/block behavior, importer atomicity/idempotency/conflicts, URL and persistence behavior, and pagination resets. Run both repositories' appropriate tests and lint/build/migration checks, followed by a real local API/browser check where available.

Local Django commands must use `DATABASE_URL='' DEBUG=True DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` because `.env` otherwise selects production. Preserve unrelated work on the existing working branches. No external publication is implicit in local development. The corpus target remains incomplete until each specified collection/category actually reaches 200 and the coverage report proves it.
