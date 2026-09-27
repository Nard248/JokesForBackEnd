# Creator content workbench

Implementation contract, 2026-09-27. These routes extend `creator_insights`; the
existing basic `/api/v1/creators/me/insights/` remains free. Feature-branch work is
not a production deployment.

## Content explorer

`GET /api/v1/creators/me/content/`

Requires authentication and `creator_content_explorer`. The seeded Creator Pro
plan gains this capability; free/canceled accounts get 403. A creator with no
published content receives an empty inventory. Ownership uses the same direct
creator/published-submission attribution as basic insights; the client cannot
choose another creator. Removed and tier-3 content is excluded. Full content and
CSV also honor the owner's age and mature-content preference; ownership is not
an age-gate exemption.

| Query | Values / behavior |
|---|---|
| `period` | `week`, `month` (default), `quarter`, `year`: 7/30/90/365 inclusive dates |
| `start`, `end` | Optional ISO dates. End defaults to today UTC; start defaults from period. Maximum 366 days; future/reversed dates rejected |
| `joke_format`, `language` | Format slug, language code |
| `theme`, `category` | Existing taxonomy slugs; combined with other filters using AND |
| `q` | Own text/setup/punchline search, maximum 200 characters |
| `sort` | `newest` (default), `oldest`, `views`, `reactions`, `saves`, `shares`; ID breaks ties |
| `page`, `page_size` | Positive page; default 25 rows, maximum 100 |

Activity dates filter metrics, not which published jokes exist in the inventory.
A quiet joke stays visible with zero observations. Text, format, language and tags
describe the current content version; there is no historical metadata snapshot.

The response contains `count`, `next`, `previous`, `results`, `window` and
`measurement_notes`. Each row contains:

```json
{
  "id": 123,
  "text": "A creator's own material",
  "setup": "",
  "punchline": "",
  "format": {"slug": "oneliner", "name": "One-liner"},
  "language": {"code": "en", "name": "English"},
  "themes": [{"slug": "work", "name": "Work"}],
  "categories": [],
  "created_at": "2026-09-27T10:00:00+00:00",
  "views": 0,
  "reactions": 0,
  "saves": 0,
  "share_initiations": 0,
  "metadata_missing": ["categories"],
  "metadata_completeness": 75,
  "recommendation": {
    "kind": "complete_metadata",
    "detail": "Add categories to make this material easier to find.",
    "sample_size": 0
  }
}
```

The completeness percentage checks four discovery dimensions: format, language,
at least one theme and at least one category. It is not a rating of humor quality,
originality, rights, safety or virality. Recommendations currently identify missing
discovery tags or request feedback; no model-generated content or growth forecast
is implied. The inventory is read-only; it does not bypass published-content review.

## Measurement population

Counts include users who currently opt in to share analytics and have a recorded
adult date of birth, excluding the creator's own activity. View rows record opens
or reveals, not completed reads. Reaction/save counts are currently existing
relationships created in the window, not event-sourced history. Share events are
initiations, not proof of a received share, click or downstream view. Anonymous and
unmeasured client activity is absent. No individual audience identifiers are returned.

The `window` response provides exact start/end and `timezone: "UTC"`. The server's
measurement notes must be visible in the UI. Consent at the time of a historical
operational event is not versioned yet; current opt-in determines inclusion. Do not
use these counts to assert whole-audience coverage or demographic representativeness.

## CSV export

`GET /api/v1/creators/me/content/export/` uses the same filters and additionally
requires `creator_exports`. It exports the entire matching inventory up to 1,000
jokes; larger matches return 422 requesting narrower filters. It does not silently
truncate or treat the current page as the entire dataset.

The CSV includes own content, metadata, metric counts and explicit UTC window
columns. User-controlled formula-prefixed cells are neutralized. The response is
an attachment and both routes use `Cache-Control: private, no-store`.

## Verification

`creator_insights/tests/test_workbench.py` covers owner isolation, no-audience
metadata value, auth/paid boundaries, canceled subscriptions, consent withdrawal,
minors/self activity, removal, date validation, CSV entitlements, row caps and
spreadsheet-formula protection, mature-content access and early-date underflow.
The 16-test suite passes. A rolled-back local PostgreSQL query-plan check with
100 owned jokes confirms pagination counts execute no metric subqueries; the
25-row default page uses three queries and evaluates metrics for those 25 rows.
Sorting by a metric necessarily evaluates that metric across the matching set.
Run with production URLs explicitly disabled:

```bash
DATABASE_URL='' DB_HOST=localhost DB_NAME=jokesfor DEBUG=True \
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
  .venv/bin/python manage.py test creator_insights.tests.test_workbench --keepdb --noinput
```
