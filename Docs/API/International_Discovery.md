# International joke discovery

Implemented 2026-09-27. Content language and cultural context are separate from the application's interface language.

## Selecting content

`GET /api/v1/discovery-locales/` returns unpaginated `languages`, `countries`, `cultures`, and `collections`. Languages use `code`, `name`, and `native_name`. Countries also expose `language_codes`; culture rows expose `slug`, `description`, `language_codes`, and `country_codes`. Each collection is an explicitly declared language-country-culture triple and includes its viewer-visible `joke_count`. An empty collection remains visible with zero jokes.

Examples:

```text
GET /api/v1/jokes/?language=es&country=ES&culture_tags=spain-everyday
GET /api/v1/jokes/?language=hy&country=AM&q=հեռախոս
GET /api/v1/jokes/random/?language=fr&country=FR
GET /api/v1/daily-jokes/today/?language=it&country=IT
```

The language, country, and culture dimensions intersect. Multiple comma-separated culture tags are a union within the culture dimension. Unknown or incompatible selectors return no matching content; they do not broaden to English. Language codes are normalized to lowercase and country codes to uppercase. These selectors are also applied to trending, tomorrow/history, mystery-box, community detail, and pack discovery. Viewer tier, block, removal and paywall restrictions remain in force.

### Language default (added 2026-10-04)

A request that omits the `language` parameter is served in the viewer's default content language: the signed-in viewer's `preferred_language`, otherwise English. Clients that predate selectors therefore never receive a mostly non-English feed once the international corpus is installed. `language=all` (case-insensitive) or a present-but-blank `language=` explicitly selects every language; a client offering an "All languages" choice must send one of them. Country and culture selectors have no default.

The default applies to joke browsing without `q`, random, daily today/tomorrow (anonymous and signed-in), trending, mystery box and community detail jokes/creators. It does not apply to text search (`/jokes/?q=...` spans every language unless `language` is given), to packs (curated content; only explicit selectors narrow them), or to daily history (the viewer's own record).

### Daily pick stability

A signed-in viewer's stored `(user, date)` daily pick is never replaced because the selection changed. When the stored joke is outside the requested selection, the endpoint serves a selection pick that is stable for that viewer, day and selection but is not stored (`id`, `delivered_at` and `created_at` are `null`). The stored row is replaced only when its joke can no longer be served to the viewer (taken down, tier or block change). Tomorrow's teaser follows the same rule.

Joke responses add `countries: [{id, code, name, native_name}]`, `origin_country`, `cultural_note`, and `editorial_status`. Explanatory cultural notes are withheld when a joke is paywall-locked.

Language and nationality are **properties of a joke**, not pages or routes: there are no per-locale URLs. A reader reaches German jokes with the `language` selector, and every joke says where it comes from.

### `origin_country` (added 2026-10-05)

`origin_country: {code, name, native_name} | null` is the country the joke *comes from* (its nationality) — for an imported record, its collection's primary country (e.g. `DE` for `de-de-everyday`). It is never a statement about a nationality. `countries` keeps its meaning: every country the joke is set in or relates to (the primary country plus neighbour contexts such as `AT`). Legacy and creator jokes have `origin_country: null`. Editors can change it in the Joke admin; the importer only fills it when empty.

Card badges: the full `JokeSerializer` (feeds, Explore, search, daily, packs, saved) and the compact `JokeListSerializer` (creator profile `jokes`) both carry `language: {id, code, name, native_name}`, `origin_country: {code, name, native_name} | null` and `editorial_status`; clients show an "AI-screened" badge when `editorial_status == 'ai_screened'`.

## Publication gate (added 2026-10-05)

`editorial_status` is one of:

| Status | Meaning | Served to readers | Sitemap / share page |
|---|---|---|---|
| `legacy` | Human-written (seed, editorial, creator) | yes | listed / indexable |
| `generated` | AI-authored, **held** — not screened | **never** | absent / 404 |
| `ai_screened` | AI-authored, passed an AI editorial screen; **not** native-reviewed | yes | absent / `noindex` |
| `native_reviewed` | Reviewed by a native speaker | yes | listed / indexable |

The gate is fail-closed and lives in `JokeManager.get_queryset()` next to the takedown filter: `Joke.objects` serves only `PUBLISHED_EDITORIAL_STATUSES = (legacy, ai_screened, native_reviewed)` (an allow-list, so any future status is held until added). Read paths that bypass the manager — FK traversals (saved, favorites, collections, daily history, recently viewed, pack entries, exports), reverse-relation aggregates (tag trending, popular themes, favourite stats, humour DNA), community through-table counts and signals, and the daily-digest pick — apply the same `live_joke_q('joke__')` predicate. A held joke therefore returns 404 on detail and share pages and is absent from lists, search, random, daily, trending, packs, discovery-locale `joke_count`, communities and creator insights. Admin uses `Joke.all_objects`. Held jokes never render a share card.

Share pages for AI-authored jokes carry `<meta name="robots" content="noindex">`; every share page sets `<html lang>` and JSON-LD `inLanguage` from the joke's language. Only `legacy` and `native_reviewed` jokes appear in `/sitemap.xml`.

### Content tiers of imported records

The age rating is still derived by the single rule `jokes/serving.py:content_tier_for_age_rating`. The importer layers two rules that can only raise a tier: records in the `dark` or `edgy` category are **never `tier_1`** — they import as `tier_2` (adult + explicit `show_mature` opt-in) whatever their age rating, and existing tier_1 rows are raised on the next run — and launch-set `blocked` records are `tier_3` (never served).

### Human-first ordering

Imported jokes have fresh `created_at` values and would otherwise flood recency feeds. Human content (`legacy`, `native_reviewed`, including all creator jokes) ranks ahead of `ai_screened` wherever recency is the default or a tie-break:

- `/jokes/` browse with no `ordering`: human first, then newest.
- Search (relevance) and `ordering=popularity`: human first among equal scores.
- Trending and community trending/newest rails: human first among ties.
- Random, daily (anonymous, signed-in selection pick and personalised pick): the pool narrows to human jokes whenever any qualify; AI-screened jokes are served when nothing human matches the selection (e.g. `language=de` today).
- An explicit `ordering=-created_at` stays pure recency.

## Launch set and import (added 2026-10-05)

`jokes/fixtures/international/launch_set.json` is the only publication switch for the corpus:

```json
{"version": 1, "method": "AI editorial screen — not native review", "screened_at": "YYYY-MM-DD",
 "publish": ["<record key>", ...], "blocked": {"<record key>": "<reason>"}}
```

`import_international_jokes --launch-set PATH` (atomic, advisory-locked, idempotent):

1. Validates the corpus and the launch set before writing. Unknown keys, a key both published and blocked, duplicate keys and any `dark`/`edgy` key in `publish` fail loudly (the command exits non-zero).
2. Creates new records as `generated` (held) with `origin_country` set; existing records keep editor changes.
3. Promotes `publish` keys from `generated` to `ai_screened` only — never downgrades `legacy`/`native_reviewed`/`ai_screened`, never touches removed or `tier_3` jokes.
4. Applies `blocked`: `tier_3`, and an `ai_screened` record goes back to `generated`.
5. Writes one `editorial_launch_set_applied` audit row when anything was published or blocked.

Without `--launch-set` an import only holds records. The old `--publish-unreviewed` flag is gone. Dropping a key from `publish` does not unpublish it; use the admin **Hold** action or add it to `blocked`. Report keys: `database.coverage[]` has `installed_count` (non-removed, non-tier_3, still matching its target, held or not), `public_count`/`mature_count` (published, by tier), `held_count` and `missing`; `database.installed_complete`, `live`, `held`, `published`, `blocked`, `mature_floor`, `origin_backfilled`.

### Production delivery (Cloud Build)

`cloudbuild.yaml` runs an `ImportInternational` step right after `Migrate`, inside the freshly built image with the same env and `DATABASE_URL` secret:

```text
python manage.py import_international_jokes --launch-set jokes/fixtures/international/launch_set.json
```

Nobody needs production database access: committing a new launch set (or corpus file) and merging to `main` publishes it on the next deploy. The first run creates the 10,800 held rows (≈50 s locally); unchanged data is a no-op (≈3 s, zero row writes). Any validation error fails the build before `Deploy`. The step is deliberately not a data migration — tests run migrations, and 10,800 rows would slow every test database. Norwegian Bokmål (`nb`), Norway (`NO`) and the `nb-no-everyday` collection are created by this step from the manifest, like every other collection; until something is published their `joke_count` is 0.

### Owner workflow: native review

1. Admin → Jokes → filter **Editorial status**, **Language** and **Origin country** (e.g. `ai_screened` + `de` + Germany).
2. Read each joke. Bulk actions: **Mark native-reviewed (publish)** (a dark/edgy joke is kept at `tier_2`), **Publish as AI-screened** (refuses dark/edgy — those need native review), **Hold** (unpublishes AI-authored content; creator jokes are skipped — withdraw those with the takedown action, which sends the DSA notice). Each changed joke gets an audit row (`editorial_native_reviewed`, `editorial_publish_ai_screened`, `editorial_hold`).
3. Use the content-report takedown for anything that must be removed; set `content_tier=tier_3` for prohibited content.
4. Native-reviewed jokes become indexable and enter the sitemap on the next frontend deploy.

`GET /api/v1/countries/` is an unpaginated editor lookup. Submission/draft input accepts `language` as a code and `countries` as a list of country codes; existing `culture_tags` accepts culture slugs. Omitted language on a new submission defaults to English. A partial update that omits language preserves its current value. Admin publication copies country associations.

## Frontend behavior

The Flow shell exposes “Joke languages” with native language names, independent country and culture choices, and collection shortcuts. `/explore` is public. Browser persistence restores the content selection; explicitly provided `language`, `country`, and `culture_tags` URL parameters take precedence. Blank URL values explicitly select “all.” Changing the selection resets feed pagination and does not reuse cards from the previous language.

For example, `/explore?language=hy&country=AM&culture_tags=armenia-everyday` is a shareable Eastern Armenian collection link. Browser persistence is local to that browser; it is not an account-wide or iOS preference. The application chrome remains English. Joke text carries its language for accessibility.

## Extending the catalogue

`Language` and `Country` name the independent axes. `CultureTag` describes a curated context. `CulturalCollection` stores an exact `(language, country, culture)` triple with a stable slug, preventing accidental Cartesian combinations. Add exact triples in admin or through a validated corpus manifest. Existing cultural associations remain useful picker metadata.

Main collection metadata: `es/ES/spain-everyday`, `fr/FR/france-everyday`, `de/DE/germany-everyday`, `hy/AM/armenia-everyday`, `it/IT/italy-everyday`, and `nb/NO/norway-everyday`. Eastern Armenian `hy` is not a Western Armenian `hyw` edition; Bokmål `nb` is not a Nynorsk `nn` edition. The corpus importer creates additional language/country/culture metadata, so new authored editions do not require schema migrations.

Some jokes involve multiple countries. German content involving Austria has `DE` and `AT` associations; Bokmål neighbour scenes can have `NO` plus `SE` or `FI`. `/jokes/?language=de&country=AT` and `/jokes/?language=nb&country=FI` browse those specific scenes. Country language lists include languages of visible associated jokes as well as declared collection triples. Secondary country tags do not create collection shortcuts or duplicate joke records. Country totals therefore overlap and must not be summed as unique-corpus totals.

The manifest declares 54 primary collection/category targets, each 200. Source research, authoring provenance, strict import options and installed coverage evidence are documented in `jokes/fixtures/international/README.md` and `Docs/Testing/2026-09-27-international-corpus-coverage.json`.
