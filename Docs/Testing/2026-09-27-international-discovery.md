# International discovery verification and current state

Date: 2026-09-27. Status: **implemented and verified locally, with all 54 declared category targets complete**. No commits, production import or deployment were performed. Unrelated workspace changes were preserved; shared search changes were coordinated with the concurrent unified-search task.

## Delivered behavior

Migrations 0039/0040 add country context, native display names, editorial provenance and the first five language/country/culture associations. Search migration 0041 belongs to the coordinated search work. Migration 0042 represents cultural collections as explicit triples, preventing unsupported language-country combinations. The importer creates additional metadata, including Norwegian Bokmål, without another schema migration.

Language, country and culture filters apply across browse/search/random/trending/daily/tomorrow/history/mystery/packs. Counts respect viewer visibility and content tiers; cached daily picks are revalidated. Paywall-locked responses withhold cultural explanations. Creator metadata survives partial edits and publication.

The frontend provides native-name selectors, collection presets with actual counts, browser persistence, shareable URLs, public Explore, nine categories, isolated pagination/query caches, content language attributes and creator language/country controls. Switching collections clears previous-language cards. Interface labels remain English. Preferences are browser-local, not account-wide or synchronized to iOS.

## Completed corpus

The dedicated local database `jokesfor_international` contains **10,800 AI-authored joke records**, exactly 200 in each of nine primary categories for every main collection:

| Country | Reading language | Records | Per category |
| --- | --- | ---: | ---: |
| France | French (`fr`) | 1,800 | 200 |
| Armenia | Eastern Armenian (`hy`) | 1,800 | 200 |
| Italy | Italian (`it`) | 1,800 | 200 |
| Germany | German (`de`) | 1,800 | 200 |
| Norway | Norwegian Bokmål (`nb`) | 1,800 | 200 |
| Spain | Spanish (`es`) | 1,800 | 200 |

Categories: wholesome, office-proper, dad, kid-safe, nerd, surreal, dark, edgy and puns. Spain preserves the original Spanish requirement alongside the five countries subsequently selected. No country-list answer remains pending for this release.

Neighbour scenes provide **407 German-language records associated with Austria**, **180 Bokmål records associated with Sweden**, and **180 associated with Finland**. These secondary tags overlap the main collections: they are not extra records, Swedish/Finnish editions or separate 200-per-category quota collections. Regional subjects are researched settings, not an exhaustive taxonomy of every culture. Eastern Armenian does not imply Western Armenian or dialect coverage; Bokmål does not imply Nynorsk or Sámi coverage.

The original 1,000 starter records retain their IDs and text. The expansion adds 9,800 individually authored records with researched settings and explanations. Joke anthologies were not scraped; assembly scripts do not pad quotas with noun-swapped templates. All records retain `generated` status. Textual checks and AI editorial review do not establish global novelty, consistent comedic quality or native linguistic naturalness. No human native-speaker review or cultural endorsement is claimed. See the [research index and six detailed briefs](../Research/2026-09-27-international-humor-index.md).

## Import evidence

The final strict import reported `created=1600 unchanged=9200 removed=0`. Authored and installed public coverage meet all 54 targets; `public_bundle_records=10800`, `context_complete=true`, with no mismatches. Strict reimport reported **`created=0 unchanged=10800 removed=0`**, retaining complete coverage and country associations.

Imports validate the full bundle, serialize writes with a PostgreSQL advisory lock, and use atomic transactions. Stable keys cannot silently change text/language/format. Duplicate text under a new key is rejected, including moderated originals. Removed records are never restored; editorial classifications and country links remain authoritative. Missing authored country links appear in a separate report; strict import rolls back even when category quotas are met. Extra editorial country links are accepted. Bulk import does not render share cards.

Evidence files:

- [Authored/installed coverage and strict reimport](2026-09-27-international-corpus-coverage.json).
- [Populated API checks](2026-09-27-international-api-checks.json).
- [Actual browser checks](2026-09-27-international-browser-checks.json).
- [Textual similarity screening and limits](2026-09-27-international-text-similarity.json).
- [Manifest and 59 explicitly listed corpus files](../../jokes/fixtures/international/manifest.json).

## Final expansion verification

| Check | Result |
| --- | --- |
| Pure corpus validation | 10,800 records; 54 targets exactly 200; stable IDs, normalized text fingerprints, schema and provenance pass |
| Focused backend corpus/discovery suite | **49 passed**, including shipped-bundle coverage and country-drift rollback regressions |
| Frontend discovery tests | **9 passed in 3 files** |
| TypeScript + Vite production build | Passed; existing large-chunk warning |
| Ruff on changed corpus/discovery modules and tests | All checks passed |
| Migration drift | No changes detected |
| Actual HTTP API | Six collections at 1,800; 54 categories at 200; matching metadata, random selection and Unicode search; incompatible `es+AM` returns zero |
| Neighbour-country API | Austria 407 in German; Sweden 180 and Finland 180 in Bokmål; matching catalogue language metadata |
| Actual headless browser, real API | Six presets at 1,800; correct article languages with no previous-language cards; three neighbour routes render |
| Layout and state | No horizontal overflow at 375/768/1280 pixels; country selection persists; clearing works; no page errors |
| Similarity screening | No candidate pairs met the documented within-language threshold; not a semantic or native-editorial certification |

The earlier integration phase also passed the combined backend suite (`1119 tests`, one skipped), full frontend suite (`900 tests in 126 files`), frontend lint (zero errors, 22 existing warnings), and three international Playwright checks. Those broader results precede this final corpus expansion; the table records fresh expansion checks. Earlier concurrent search failures were resolved before the broad green suites.

Final expansion logs: `/tmp/jokes-intl-expansion-final-backend.log`, `/tmp/jokes-intl-country-expansion-frontend.log`, `/tmp/jokes-intl-expansion-build.log`, `/tmp/jokes-intl-expansion-migration-check.log`, `/tmp/jokes-intl-complete-import.log`, `/tmp/jokes-intl-complete-reimport.log`. Earlier full-suite logs: `/private/tmp/jokesfor-search-20260927/final-backend.log` and `/tmp/jokes-intl-final-frontend.log`.

## Local preview and maintenance

Frontend: `http://localhost:5286/explore`. API: `http://localhost:8023/api/v1/`, backed only by `jokesfor_international`. The frontend uses the real API. Backend production integrations are disabled; local throttle limits were increased for automated checks. Every Django command explicitly used `DATABASE_URL=''`; production Neon was never selected.

The [corpus README](../../jokes/fixtures/international/README.md) documents strict validation/import; [API documentation](../API/International_Discovery.md) describes selectors and visibility. Human editors can refine jokes and record native review without changing the generated corpus's provenance claims.

Four concurrent agent slots including the root were available and used; 100 simultaneous agents were unavailable. Ruflo/ToolSearch capabilities were absent, so native collaboration tools were used. Obsidian was not synchronized because `~/.obsidian-Codex.env` is absent. These documents are the local session record.
