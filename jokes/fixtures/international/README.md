# International corpus

These are original AI-authored drafts, not externally collected folklore or a native-reviewed anthology. Research and writing guidance are in `Docs/Research/2026-09-27-humor-localization-research.md`. Language, country context, and cultural collection are independent metadata; an ordinary scene set in a country does not assert a national trait.

`manifest.json` defines exact collections and category targets. Each record has one primary category, so attaching more tags cannot inflate authored coverage. Keys are stable and must not be reused for different text. Text is stored in its original Unicode script; validation normalizes display strings to NFC and compares NFKC/case/punctuation-insensitive fingerprints within each language. This catches cosmetic duplicates, but does not replace editorial review for shared premises or naturalness.

The declared target is **200 per category in each of six main collections**, totaling **10,800 records** across nine categories. The owner named France, Armenia, Italy, Germany and Norway; Spain remains because Spanish was explicitly requested earlier. Norway uses Norwegian Bokmål (`nb`), Armenia uses Eastern Armenian (`hy`). Neither implies support for Nynorsk or Western Armenian. The original five 200-record files retain their stable IDs and text. Independently authored expansion files live in per-language directories; the manifest lists every included file explicitly.

Austria, Sweden and Finland are researched neighbour contexts. Individual German jokes involving Austria and Bokmål jokes involving Sweden or Finland have `related_countries` tags. These are discoverable country associations on the same records, not additional translated editions or separate 200-per-category collections. The main-country quota counts a record only once. This release does not claim exhaustive coverage of every regional culture within any country.

## Validate and import

From the backend repository, validate files without database writes:

```sh
DATABASE_URL='' DEBUG=True DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
  .venv/bin/python manage.py import_international_jokes --dry-run \
  --require-complete \
  --report /tmp/international-authored-coverage.json
```

Import into the dedicated local preview database:

```sh
DATABASE_URL='' DB_NAME=jokesfor_international DEBUG=True \
  DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
  .venv/bin/python manage.py migrate --noinput

DATABASE_URL='' DB_NAME=jokesfor_international DEBUG=True \
  DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
  .venv/bin/python manage.py import_international_jokes --require-complete \
  --launch-set jokes/fixtures/international/launch_set.json \
  --report /tmp/international-installed-coverage.json
```

Imports are fail-closed. Every new record is created **held** (`editorial_status=generated`): stored and reviewable in the admin, never served to readers. Only `launch_set.json` publishes: keys in its `publish` list move from `generated` to `ai_screened` ("AI generated, screened" — no native review); keys in `blocked` become `tier_3` and stay held. A launch set can never publish a `dark` or `edgy` record, and those categories import as `tier_2` (mature, adult opt-in) regardless of their age rating. The launch set is authoritative for `ai_screened`: removing a key from `publish` holds that record again on the next run (and deletes its share card), so production never drifts from the reviewed file; native review is never undone. The committed launch set holds the 2026-10-05 AI editorial screen (1,260 published, 83 blocked); production runs this command in Cloud Build after migrations (see `Docs/API/International_Discovery.md`, "Production delivery"), so editing the launch set and deploying is the whole publication workflow. Every record's `origin_country` is its collection country; `countries` also carries related neighbour contexts.

Use `--manifest PATH` for another authored bundle. `--require-complete` rejects unmet authored targets; when importing, it also requires complete installed counts (held or published, excluding removed and tier_3) and country associations. It must pass before reporting quota completion. See the current report in `Docs/Testing/2026-09-27-international-corpus-coverage.json` for actual installed coverage.

## Import behavior

The entire bundle is validated before writing. Imports are atomic and serialized with a PostgreSQL advisory transaction lock. Existing keys with different text/language/format are rejected. Existing editorial classifications and review states are preserved; removed jokes are never restored. Duplicate text under a different ID is rejected, including duplicates of moderated originals. Newly created records use `editorial_status=generated` (held), `origin_country`, and explicit source attribution; age ratings determine the content tier, raised to `tier_2` for dark/edgy and to `tier_3` for blocked keys. Bulk inserts avoid generating a share card for every record, and held jokes never get one.

The JSON report separates `authored_coverage`/`authored_complete` from `database.coverage`/`database.installed_complete`. Installed coverage counts nonremoved, non-prohibited records whose current language, country, culture and primary-category target still match; each row also splits them into `public_count` (published tier 1), `mature_count` (published tier 2) and `held_count`. This distinction makes post-import editorial changes and moderation visible. Counts do not certify native review or the quality of every joke.

`database.context_complete` and `database.context_mismatches` separately report missing primary or secondary country links on existing records. Normal imports warn and preserve those editorial links; strict imports roll back if any required association is missing. Additional editorial country links are accepted. Resolve intended revisions explicitly before retrying a strict import. A changed authored file cannot silently restore a country that an editor removed.

Taxonomy slugs come from current migrations rather than the older `lookup_data.json`. Known categories are `wholesome`, `office-proper`, `dad`, `kid-safe`, `nerd`, `surreal`, `dark`, `edgy`, and `puns`. Future collections can add researched metadata and independently authored texts to the manifest. Do not pad quotas by changing names or objects in the same joke template.

## Neighbour-country metadata

The manifest's optional `context_countries` array declares additional countries using `code`, `name`, and `native_name`. Codes must be distinct uppercase two-letter values and must not redeclare a primary collection country. Each record may contain `related_countries`, a list of distinct declared secondary country codes; its primary country is implicit in `collection` and must not be repeated. The importer adds those country links and the culture's declared associations. Discovery exposes the actual readable language for these countries without inventing a new collection preset.

The cultural research briefs are in `Docs/Research/2026-09-27-*-humor-contexts.md`; the Norway/Nordic brief is `2026-09-27-norway-nordic-humor-contexts.md`. Sources substantiate customs and language decisions. They are not sources of copied joke text. Automated coverage and textual-similarity checks cannot certify funniness, regional naturalness, or human editorial review.
