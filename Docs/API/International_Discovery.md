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

Joke responses add `countries: [{id, code, name, native_name}]`, `cultural_note`, and `editorial_status`. Explanatory cultural notes are withheld when a joke is paywall-locked. Editorial status is `legacy`, `generated`, or `native_reviewed`; generated records do not imply a human review. `/sitemap.xml` omits `generated` jokes until an editor changes their status.

`GET /api/v1/countries/` is an unpaginated editor lookup. Submission/draft input accepts `language` as a code and `countries` as a list of country codes; existing `culture_tags` accepts culture slugs. Omitted language on a new submission defaults to English. A partial update that omits language preserves its current value. Admin publication copies country associations.

## Frontend behavior

The Flow shell exposes “Joke languages” with native language names, independent country and culture choices, and collection shortcuts. `/explore` is public. Browser persistence restores the content selection; explicitly provided `language`, `country`, and `culture_tags` URL parameters take precedence. Blank URL values explicitly select “all.” Changing the selection resets feed pagination and does not reuse cards from the previous language.

For example, `/explore?language=hy&country=AM&culture_tags=armenia-everyday` is a shareable Eastern Armenian collection link. Browser persistence is local to that browser; it is not an account-wide or iOS preference. The application chrome remains English. Joke text carries its language for accessibility.

## Extending the catalogue

`Language` and `Country` name the independent axes. `CultureTag` describes a curated context. `CulturalCollection` stores an exact `(language, country, culture)` triple with a stable slug, preventing accidental Cartesian combinations. Add exact triples in admin or through a validated corpus manifest. Existing cultural associations remain useful picker metadata.

Main collection metadata: `es/ES/spain-everyday`, `fr/FR/france-everyday`, `de/DE/germany-everyday`, `hy/AM/armenia-everyday`, `it/IT/italy-everyday`, and `nb/NO/norway-everyday`. Eastern Armenian `hy` is not a Western Armenian `hyw` edition; Bokmål `nb` is not a Nynorsk `nn` edition. The corpus importer creates additional language/country/culture metadata, so new authored editions do not require schema migrations.

Some jokes involve multiple countries. German content involving Austria has `DE` and `AT` associations; Bokmål neighbour scenes can have `NO` plus `SE` or `FI`. `/jokes/?language=de&country=AT` and `/jokes/?language=nb&country=FI` browse those specific scenes. Country language lists include languages of visible associated jokes as well as declared collection triples. Secondary country tags do not create collection shortcuts or duplicate joke records. Country totals therefore overlap and must not be summed as unique-corpus totals.

The manifest declares 54 primary collection/category targets, each 200. Source research, authoring provenance, strict import options and installed coverage evidence are documented in `jokes/fixtures/international/README.md` and `Docs/Testing/2026-09-27-international-corpus-coverage.json`.
