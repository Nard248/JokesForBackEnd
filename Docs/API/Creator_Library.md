# Creator library API

Implemented 2026-09-27 on the creator business model branch. All routes below are relative to `/api/v1/creators/me/` and use existing cookie JWT + CSRF or Bearer authentication. Every response, including errors, uses `Cache-Control: private, no-store`.

The workspace stores private preparation notes and ordered collections independently of viewer saves. Taxonomy requests enter a human review queue. They do not modify public jokes when submitted.

## Access and ownership

- POST/PATCH require the existing `creator_content_explorer` entitlement. Free publishing and basic analytics are unchanged.
- GET and DELETE remain available to the authenticated owner after subscription cancellation. Reading the public jokes remains free.
- Public joke selection uses direct creator attribution, with the existing published-submission fallback for legacy jokes. Foreign, removed, prohibited, and maturity-inaccessible jokes cannot be added or edited.
- A batch containing any unavailable joke fails atomically with a generic 404; it does not identify whether an unavailable ID exists.
- Notes and collection descriptions are private. These models are not registered in Django admin and do not appear in public joke/profile serializers.
- Rate limiting reuses `CreatorInsightsThrottle`. List endpoints use `{count,next,previous,results}`, page size 25, with validated `page` and `page_size` (maximum 100).

## Private notes

`GET content/{joke_id}/workspace/` returns:

```json
{"joke_id": 42, "private_note": "Try a longer pause before the reveal.", "updated_at": "2026-09-27T12:00:00Z"}
```

An accessible joke without a saved note returns an empty string and `updated_at: null`.

`PATCH content/{joke_id}/workspace/` accepts exactly `{"private_note":"..."}`, with a maximum of 5,000 characters. Empty strings are valid. The update returns the same shape. There is one note per owner/joke; later saves replace the note.

`GET content/workspace-notes/` lists saved, currently accessible notes with the same shape, plus top-level `unavailable_count`. This remains useful when the paid content explorer is no longer available. Notes belonging to inaccessible jokes are excluded from the list; the count explains their absence without returning content or IDs.

`DELETE content/{joke_id}/workspace/` returns 204. The owner can erase a stored note even after a takedown, maturity-preference change, or ownership reassignment. It never returns hidden content.

## Series and set lists

`GET/POST collections/` lists or creates collections. Creation requires `name` (1–100 characters) and `kind` (`series` or `set_list`); optional `description` is limited to 1,000 characters, and optional `joke_ids` is an ordered array of up to 100 distinct positive IDs.

`GET/PATCH/DELETE collections/{id}/` retrieves, updates, or deletes an owned collection. PATCH is partial; omitted fields remain unchanged. DELETE returns 204, including when some members are no longer accessible.

```json
{
  "id": 7,
  "name": "Five-minute opening set",
  "kind": "set_list",
  "description": "Open slowly; keep the final callback.",
  "joke_ids": [42, 19],
  "items": [
    {"joke_id": 42, "display_text": "A recognizable excerpt of the first joke."},
    {"joke_id": 19, "display_text": "A recognizable excerpt of the second joke."}
  ],
  "unavailable_count": 1,
  "updated_at": "2026-09-27T12:00:00Z"
}
```

`items` follows the same order as `joke_ids` and includes only accessible owned content. Its `display_text` is at most 180 characters. Inaccessible members remain stored, but are omitted from both arrays. `unavailable_count` reports their count.

**Supplying `joke_ids` replaces all membership, including hidden members.** A UI must not silently resubmit the filtered visible array. Preserve membership by omitting the field when editing a title/description, and require an explicit user decision before removing unavailable members. The initial web UI disables membership replacement while unavailable members exist.

There are at most 100 collections per owner. Database row locks serialize concurrent creation and reordering; database constraints prevent duplicate membership or positions. Collection names need not be unique.

## Metadata review

`POST content/metadata-requests/` accepts:

```json
{
  "joke_ids": [42, 19],
  "themes": ["work", "family"],
  "categories": ["puns"],
  "reason": "These topics describe the published material more accurately."
}
```

- One to 50 distinct joke IDs.
- At least one of `themes` or `categories`; each is an array of at most 30 distinct existing slugs.
- Omitting a taxonomy leaves it unchanged. An empty array explicitly requests clearing it.
- Optional reason is limited to 1,000 characters.
- Themes map to `ContextTag`; categories map to `Tone`. Reuse `/api/v1/context-tags/` and `/api/v1/tones/` for choices.
- Unknown input fields are rejected, including public text, media, format, age rating, content tier, ownership and workflow status.
- Existing pending requests produce a 409 for the entire batch. No partial creation occurs.

A successful response is 201 with `{"results":[...]}`. Each row has `id`, `joke_id`, `changes`, `reason`, `status` (`pending`, `approved`, or `rejected`), `decision_reason`, `created_at`, and nullable `reviewed_at`.

`GET content/metadata-requests/` returns paginated own request history, available after cancellation. Requests for currently inaccessible jokes are excluded. There is no client API to approve a proposal or mutate a submitted proposal.

### Moderator workflow

The existing Django admin contains a **Creator metadata requests** queue. A staff account with the `creator_insights.change_creatormetadatarequest` permission can explicitly approve or reject selected pending requests. Proposal data, ownership, status, review fields and snapshots are read-only; requests cannot be manually created or deleted in admin. Rejection currently supplies a standard reason; a customized rejection-reason form is a later enhancement.

Approval runs under database locks, checks ownership, takedown/prohibited status, and compares current themes/categories/culture tags with the stored baseline hash. A stale baseline, unavailable joke, or deleted requested tag causes rejection without applying any part of the proposal. Repeating an action cannot apply a decision twice.

An approval only changes requested theme/category relationships and the joke's modification timestamp. It does not create another published joke, modify text/media/age classification, or send automatic email. Moderator audit records contain request/joke IDs and outcome; proposal reasons and private preparation notes are excluded.

The request stores immutable before/after taxonomy snapshots for that decision. **This is not complete publication versioning** and does not reconstruct historical joke text or changes made elsewhere in admin.

## Export and deletion

`export_creator_library(user)` supplies `creator_library` for the existing authenticated account ZIP export. It includes all the owner's private notes, ordered collections and metadata request history, including inaccessible targets, without requiring a subscription. It contains IDs and the owner's own private data; it does not copy public joke text or media URLs.

Owner relations cascade on account deletion. Hard deletion of a joke removes associated notes, collection entries, and requests. Moderation takedown is different: private rows remain available for account export/erasure while creator-library content reads enforce visibility restrictions.

## Error conventions

- 400: invalid shape, unknown field/tag, duplicate IDs/tags, size limit, or collection cap.
- 401: authentication missing.
- 403: write entitlement or CSRF missing.
- 404: unavailable/foreign target or collection.
- 409: an affected joke already has a pending metadata request.

Concurrent note edits currently use last successful save; there is no collaborative editing or optimistic-version token. Collections organize published jokes only; unpublished variants, performance dates, rehearsal timing, rights management and full publication history remain separate future work.
