# Creator Content Authoring — Backend Design

**Date:** 2026-05-19
**Status:** Draft, awaiting review
**Author:** brainstormed via superpowers:brainstorming
**Scope:** backend-only (Django REST API + admin); frontend out of scope

---

## 1. Problem

Each joke format the platform supports has a distinctive UI rendering. Knock-knocks render as alternating dialogue bubbles. Setup-punchlines use a tap-to-reveal. Stories render as long-form prose. Observational jokes use italic-quote treatment. Anti-jokes show a "*That's it. That's the joke." footer.

The renderer reads these differences from the `Joke` model:

- `format` (FK) — which renderer to use
- `text` / `setup` / `punchline` — text fields the renderer reads selectively
- `lines` (JSONField) — knock-knock dialogue array

**The gap:** the user-facing `JokeSubmission` model only exposes `text` / `setup` / `punchline` to creators. There is no way for a creator to submit:

- a knock-knock with its `lines` array (the renderer needs this)
- a `culture_tags` selection (parity with `Joke`)
- a payload that gets validated against the format's actual requirements (today, a creator can submit a knock-knock with empty `lines` and the system accepts it)

**The second gap** (uncovered during exploration): the publish pipeline is incomplete. `JokeSubmission.published_joke` is declared and referenced in admin and analytics queries, but no code path actually creates a `Joke` from an approved submission. Moderators can mark a submission `published` and the field stays null forever. The creator content system is currently write-only.

## 2. Goals and non-goals

### Goals
- Bring `JokeSubmission` to renderer-parity with `Joke` for every value the format-specific UI consumes.
- Make per-format validation explicit and serializer-enforced.
- Expose the per-format input contract via the existing `/formats/` endpoint so the editor can render conditional inputs without hardcoding rules client-side.
- Wire the missing approval-to-publish step as a Django admin action.

### Non-goals (explicitly deferred)
- Per-joke presentation styling overrides (colors, fonts, reveal pacing) — separate feature
- Rich media attachments (image / audio / GIF) — separate feature, own compliance lift
- Block-based composition (Notion-style) — separate feature
- Per-format admin-editable rule tables — overkill for 6 stable formats
- Moderator API endpoints — Django admin is the moderator UI
- Adding new joke formats beyond the 6 currently seeded

## 3. Constraints

- **YAGNI**: smallest change that closes the stated gap. See [[feedback_yagni_scope]].
- **Single Cloud Run app, no async workers, no cron.** Everything request-triggered. See [[feedback_no_celery_single_app]].
- **No destructive migrations.** Existing drafts/submissions/jokes are preserved as-is.
- **Single serializer surface.** Don't introduce a new endpoint when an existing one can carry the richer payload.

## 4. Architecture

### Component responsibilities

| Component | Responsibility |
|---|---|
| `JokeSubmission` model | Storage for all creator-supplied content fields (extended to include `lines` and `culture_tags`); workflow status; link to published `Joke` on approval |
| `FORMAT_RULES` constant (in `jokes/submission_rules.py`) | Single source of truth for per-format required fields, forbidden fields, and constraints |
| `JokeSubmissionCreateSerializer.validate()` | Looks up the submitted format's rule and enforces required / forbidden / constraint checks, returning DRF-standard field-level errors |
| `FormatSerializer` (extended) | Exposes `required_fields`, `forbidden_fields`, and `constraints` per format slug so the editor renders conditional inputs |
| Admin action `approve_and_publish` (on `JokeSubmissionAdmin`) | Atomic `JokeSubmission` → `Joke` conversion: copies all content fields including `lines` and `culture_tags`, sets `published_joke`, sets `status='published'` |
| Frontend Handout entry | Per-format input contract + sample request/response payloads |

### Data flow (creator submit → moderator publish)

```
1. Editor loads /formats/.
   Response now includes per-format schema:
     [{ slug: "knock", name: "Knock-knock",
        required_fields: ["lines"],
        forbidden_fields: ["text","setup","punchline"],
        constraints: { min_lines: 4, max_lines: 8, max_line_chars: 200 } },
      ...]
   Editor renders the correct input set for the selected format.

2. Creator POSTs to /jokes/submit/ with format-appropriate payload.
   Serializer validate() looks up FORMAT_RULES[format.slug] and enforces it.
   On pass: row saved as status='pending'.
   On fail: 400 with DRF-standard field errors.

3. Creator can PATCH /jokes/my-drafts/{id}/ while status in {draft, rejected}.
   Same validation pipeline.

4. Moderator opens Django admin, filters to status='pending'.
   Selects rows, runs "Approve & publish" action.
   For each: atomic block creates Joke (mirrors all fields), sets
   submission.published_joke and status='published'.
   On Joke create:
     - pgtrigger updates search_vector automatically (no extra wiring)
     - Joke.save() auto-generates share_image (no extra wiring)
```

### The rule table

```python
# jokes/submission_rules.py
FORMAT_RULES = {
    'oneliner': {
        'required':  ['text'],
        'forbidden': ['setup', 'punchline', 'lines'],
    },
    'setup': {
        'required':  ['setup', 'punchline'],
        'forbidden': ['text', 'lines'],
    },
    'knock': {
        'required':  ['lines'],
        'forbidden': ['text', 'setup', 'punchline'],
        'constraints': {
            'min_lines': 4,
            'max_lines': 8,
            'max_line_chars': 200,
        },
    },
    'story': {
        'required':  ['text'],
        'forbidden': ['setup', 'punchline', 'lines'],
        'constraints': {
            'min_text_words': 30,
        },
    },
    'anti': {
        'required':  ['setup', 'punchline'],
        'forbidden': ['text', 'lines'],
    },
    'observ': {
        'required':  ['text'],
        'forbidden': ['setup', 'punchline', 'lines'],
    },
}
```

`lines` value shape — list of non-empty strings, alternating speakers by index parity (matches the existing comment on `Joke.lines`):

```json
["Knock, knock.", "Who's there?", "Olive.", "Olive who?", "Olive you and I miss you!"]
```

## 5. Data model changes

### Migration `0022_submission_creator_parity.py`

Single migration. Two operations:

1. `AddField` `JokeSubmission.lines` — `JSONField(null=True, blank=True)`
2. `AddField` `JokeSubmission.culture_tags` — `ManyToManyField(CultureTag, blank=True, related_name='submissions')`

No data backfill. Existing rows get `lines=None` and empty `culture_tags`. Existing draft round-trips continue to work — the new fields are optional in PATCH.

### Why no rules-on-Format

Considered: adding `Format.required_fields = JSONField` so an admin could tune rules without code. Rejected because:
- Only 6 stable formats; the taxonomy is not changing
- Validation logic still has to live in Python (constraints like `min_text_words`); the JSON-on-model variant becomes "declarative for some rules, code for others", which is worse than "all in code"
- One source of truth in `submission_rules.py` is easier to grep, test, and reason about than DB-stored config

If the format taxonomy ever opens up to admin-defined formats, revisit.

## 6. API surface

No new endpoints. Three existing endpoints carry richer payloads.

### `GET /api/v1/formats/`

Response shape (per format):
```json
{
  "id": 3,
  "slug": "knock",
  "name": "Knock-knock",
  "description": "Multi-line call-and-response format",
  "required_fields": ["lines"],
  "forbidden_fields": ["text", "setup", "punchline"],
  "constraints": { "min_lines": 4, "max_lines": 8, "max_line_chars": 200 }
}
```

The three new keys come from `FORMAT_RULES` via a serializer helper.

### `POST /api/v1/jokes/submit/`

Accepts the new fields. Validation enforces the format rule.

**Valid knock-knock submission:**
```json
{
  "format": "knock",
  "age_rating": "kid-safe",
  "language": "en",
  "lines": [
    "Knock, knock.",
    "Who's there?",
    "Lettuce.",
    "Lettuce who?",
    "Lettuce in, it's cold out here!"
  ],
  "tones": ["wholesome", "dad"],
  "context_tags": ["family"],
  "culture_tags": ["universal"],
  "source": "original"
}
```

**Invalid (knock-knock with empty lines):**
Response 400:
```json
{ "lines": ["This field is required for knock-knock format."] }
```

**Invalid (knock-knock with text filled):**
Response 400:
```json
{ "text": ["Not allowed for knock-knock format."] }
```

### `PATCH /api/v1/jokes/my-drafts/{id}/`

Same payload shape and validation as POST. Existing rule (`status in {draft, rejected}` only) stays.

### `GET /api/v1/jokes/my-drafts/` and `/{id}/`

List/detail serializers extended to include `lines` and `culture_tags` so editors can resume a draft with full state.

## 7. Validation behavior

`JokeSubmissionCreateSerializer.validate(attrs)`:

1. Resolve `format` from `attrs` (or `self.instance` on PATCH).
2. Look up `rule = FORMAT_RULES.get(format.slug)`. If missing → 400 `{"format": ["Unknown format slug."]}`.
3. For each field in `rule['required']`: if missing or empty → field error.
4. For each field in `rule['forbidden']`: if present and non-empty → field error.
5. For each constraint key:
   - `min_lines` / `max_lines` / `max_line_chars`: validate the `lines` JSON array structure and length.
   - `min_text_words`: split on whitespace, count tokens, compare.
6. Return validated attrs.

The helper `validate_per_format(format_slug, attrs)` lives next to `FORMAT_RULES` in `submission_rules.py` so it can be unit-tested without DRF context.

## 8. Admin "Approve & publish" action

In `jokes/admin.py`, attached to the existing `JokeSubmissionAdmin`:

```python
@admin.action(description='Approve and publish selected submissions')
def approve_and_publish(self, request, queryset):
    pending = queryset.filter(status='pending')
    created = 0
    skipped = 0
    for submission in pending:
        try:
            with transaction.atomic():
                source_obj, _ = Source.objects.get_or_create(
                    name=submission.source or 'original'
                )
                joke = Joke.objects.create(
                    text=submission.text,
                    setup=submission.setup,
                    punchline=submission.punchline,
                    lines=submission.lines,
                    format=submission.format,
                    age_rating=submission.age_rating,
                    language=submission.language,
                    source=source_obj,
                    content_tier='tier_1',  # moderator can adjust on Joke after publish
                )
                joke.tones.set(submission.tones.all())
                joke.context_tags.set(submission.context_tags.all())
                joke.culture_tags.set(submission.culture_tags.all())
                submission.published_joke = joke
                submission.status = 'published'
                submission.save(update_fields=['published_joke', 'status', 'updated_at'])
                created += 1
        except Exception as exc:
            self.message_user(request, f'Skipped {submission.id}: {exc}', level='WARNING')
            skipped += 1
    self.message_user(request, f'Published {created} submission(s); skipped {skipped}.')
```

**Side effects handled automatically:**
- `search_vector` populated by existing `pgtrigger` on `Joke` insert
- `share_image` generated by `Joke.save()` existing logic
- Top-jokesters query already counts `joke_submissions__status='published'`, so the user's punchline count updates immediately

**Moderator-visible safety:**
- Only `status='pending'` rows in the selection are processed; drafts/rejected/already-published are skipped silently
- Each conversion is its own atomic block; partial failures don't roll back the whole batch
- Errors are surfaced as admin messages, not silent

## 9. Frontend Handout update

Add a "Creator authoring" section to `Docs/API/Frontend_Integration_Handout.md`:

1. Editor flow diagram (load formats → pick format → conditional inputs)
2. Per-format example payloads (all 6 formats)
3. Error catalog (every field-error string defined in `FORMAT_RULES`)
4. Draft lifecycle (`draft` → `pending` → `published` | `rejected`; PATCH allowed in `draft`/`rejected`)

## 10. Testing

### Unit (jokes/tests.py or a new tests/test_submission_rules.py)
- For each of the 6 formats: one passing case + one missing-required + one forbidden-present + one constraint-violation
- `lines` shape validation: non-array, empty array, entry too long, count too low, count too high
- `format` slug not in `FORMAT_RULES` → graceful 400

### Integration (jokes/tests.py)
- Full submit (knock-knock with valid `lines`) → row created with `status='pending'`
- PATCH draft → resubmit → still valid
- Admin `approve_and_publish` action → `Joke` created with all fields mirrored → appears in `GET /api/v1/jokes/?format=knock` with correct `lines`
- Top-jokesters punchline count includes the newly published submission

### Smoke
- Existing pre-migration drafts load via `GET /jokes/my-drafts/` without error
- Existing pre-migration drafts editable via PATCH (the new fields stay null on the response)

## 11. Migration / deploy risk

| Risk | Mitigation |
|---|---|
| Existing drafts have invalid format combinations under the new rules (e.g. knock-knock saved with text but no lines) | Validation only fires on POST/PATCH. Existing rows untouched. If a creator edits an old broken draft, they'll be forced to fix it before resubmitting — acceptable. |
| New `culture_tags` M2M creates an empty join table | Harmless; standard Django M2M migration |
| Admin action runs in a request → long-running batch | Mitigation: process `queryset.filter(status='pending')` only; each conversion is its own transaction so timeout on row 50 doesn't roll back rows 1–49. If batches grow huge, paginate the admin selection. |

## 12. Open questions (none blocking)

- **Source attribution.** `JokeSubmission.source` is a CharField; `Joke.source` is an FK to `Source`. The admin action `get_or_create(name=submission.source)` handles this, but it means every distinct submitter-typed string becomes a new `Source` row. Acceptable for MVP; if the `Source` table starts looking spammy, add an admin reconciliation tool later.
- **Should drafts be auto-validated on PATCH?** Today, drafts can be PATCHed with incomplete content (no validation until `submit/`). Decision: yes, validate on PATCH too — same rule table. This catches bad payloads sooner and aligns with the new conditional-input UX.

## 13. Out-of-scope follow-ups (for future asks, not this implementation)

- Per-joke presentation styling overrides
- Rich media attachments (image / audio / GIF) — compliance addendum dependency
- Block-based composition
- Admin-editable per-format rule tables
- Versioning of submissions (currently PATCH overwrites in place)
- Co-author / collaborative authoring
- Scheduled publishes
