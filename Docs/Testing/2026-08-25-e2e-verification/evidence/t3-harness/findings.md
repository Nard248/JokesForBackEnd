
---

# Findings

## F1 · P0 — the public share page hands out the punchline the paywall just withheld

**Test:** `T3-O02b` · **Files:** `jokes/templates/jokes/share.html`, `jokes/views.py::joke_share_page`

`joke_share_page` applies **only** the content-tier gate (`allowed_tiers`). It never consults
`jokes/paywall.paywall_state`, and the template renders the whole joke:

```html
<p class="joke-text">{{ joke.text }}</p>
```

For `setup` / `anti` jokes `Joke.text` is the backfilled `"<setup> <punchline>"`; for `knock` it is
the joined dialogue; for text-only formats it is the entire joke. So a single unauthenticated GET
returns the exact payoff `JokeSerializer.to_representation` had just stripped server-side. The view's
own docstring says the teaser is "NEVER the punchline — this page advertises the joke, it must not
spoil it", so this also contradicts the stated intent of the 56e4945 spoiler fix (which only scrubbed
the *meta tags*). It is additionally an SEO spoiler: crawler-indexed body text still contains the
punchline.

**Reproduction**

```
# 1. free user is over the 10-reads/day cap
GET /api/v1/jokes/500/            (authenticated free user, cap consumed)
    -> 200 {"is_locked": true, "punchline": null, "text": "T3SETUP… regression "}

# 2. same joke, no auth, no cookies
GET http://localhost:8010/jokes/500/share/
    -> 200 …<p class="joke-text">T3SETUP1787654282 why does the share page need a regression test?
             T3PUNCH1787654282 because the punchline is the whole product.</p>…
```

Because joke ids are sequential, the entire catalogue's payoff is scriptable from this route.

**Proposed fix** — in `jokes/templates/jokes/share.html`, render the teaser the view already computes
instead of the raw model field: replace `{{ joke.text }}` with `{{ description }}` (which is
`Truncator(joke.setup or joke.text).chars(160)` — already punchline-free), or drop the paragraph
entirely and keep only the CTA, since the docstring calls this "a crawler-facing shell", not the joke
experience. If a body preview is wanted for text-only formats, gate it in
`jokes/views.py::joke_share_page` on `paywall_state(request).over is False`.

## F2 · P1 — GDPR account deletion is impossible for any user who has ever logged in

**Test:** `T3-S07c` · **Files:** `jokes/views.py::UserAccountDeleteView.delete` (line ~2485),
`audit/models.py::AuditLog`, `audit/signals.py::on_user_logged_in`

`user.delete()` must `SET_NULL` the `AuditLog.actor` FK, but `AuditLog.Meta.triggers` installs
`pgtrigger.Protect(operation=Update | Delete, name='append_only')`. Postgres therefore raises on the
cascade's `UPDATE audit_auditlog SET actor_id = NULL`:

```
django.db.utils.InternalError: pgtrigger: Cannot update or delete rows from audit_auditlog table
CONTEXT: PL/pgSQL function pgtrigger_append_only_e464f() line 11 at RAISE
```

`AuditLog.actor`'s own comment says *"NULL after account deletion (SET_NULL)"* — the append-only
trigger directly contradicts it. `audit/signals.on_user_logged_in` writes an `AuditLog` row on every
successful login, so **every real account** is permanently undeletable. This is a GDPR Art. 17
right-to-erasure failure, not just a 500.

Worse, the failure is **partially destructive**: step 2 of the delete deletes storage objects via
`asset.delete_with_files()`, which is outside the transaction's rollback. After the 500 the account,
the `MediaAsset` rows and every child row survive — but the user's uploaded files are gone from
storage, leaving rows pointing at missing files.

**Reproduction** (controlled experiment, `T3-S07c`, run through `UserAccountDeleteView` directly so
the only variable is one audit row):

```
no audit row  -> HTTP 204
one audit row -> InternalError: pgtrigger: Cannot update or delete rows from audit_auditlog table
audited probe user still exists = True
```

and end-to-end over HTTP:

```
DELETE /api/v1/users/me/ {"password": "<correct>"}   -> 500
GET    /api/v1/users/me/profile/                     -> 200   (session still alive)
DB: user row still present= True | media row survived= True | FILE still on disk= False
```

**Proposed fix** — in `jokes/views.py::UserAccountDeleteView.delete`, anonymise the audit trail
inside the existing `transaction.atomic()` block *before* `user.delete()`, using pgtrigger's own
escape hatch so the append-only guarantee stays on for everyone else:

```python
import pgtrigger
with pgtrigger.ignore('audit.AuditLog:append_only'):
    AuditLog.objects.filter(actor=user).update(actor=None)   # actor_email_hash already preserved
```

Alternatively change `AuditLog.actor` to `on_delete=models.DO_NOTHING` with `db_constraint=False`, so
Django never emits the UPDATE. Either way, move the `asset.delete_with_files()` storage deletes to
*after* the transaction commits (or use `transaction.on_commit`) so a failed delete can no longer
destroy files it did not delete rows for. A regression test belongs in `jokes/tests_compliance.py`:
create a user **with** an `AuditLog` row, then assert `DELETE /api/v1/users/me/` returns 204.

## F3 · P1 — a `setup` / `anti` / `knock` draft can never be submitted from the drafts editor

**Test:** `T3-M01b` · **File:** `jokes/serializers.py::JokeSubmissionCreateSerializer.validate`
(the backfill block, ~line 946) vs `jokes/views.py::JokeDraftSubmitView.post`

The autosave PATCH runs with `skip_format_validation=True` and then **backfills** `data['text']` from
`setup + punchline` (or the joined `lines`). `JokeDraftSubmitView` later re-validates the *stored*
row against `FORMAT_RULES`, where `text` is a **forbidden** field for exactly those three formats — so
submit returns 400 forever:

```
POST /api/v1/jokes/my-drafts/          {"format":"setup"}                       -> 201 (id 85)
PATCH /api/v1/jokes/my-drafts/85/      {"setup":"…","punchline":"…"}            -> 200
   (DB now: text = "Why did the draft cross the road? It never got there.")
POST /api/v1/jokes/my-drafts/85/submit/                                          -> 400
   {"text": "Not allowed for setup format."}
```

Same for `anti` and `knock`. The control path is fine — `POST /api/v1/jokes/submit/` returns 201,
because there validation runs *before* the backfill. The SPA creator editor uses the broken path
(`src/features/create/api.ts` → `my-drafts` create/patch/submit), so setup-punchline, anti-joke and
knock-knock submissions cannot be filed from the product UI. It also produces the spurious
`{"text": "Not allowed for knock format."}` alongside the real error in `T3-M02`.

Why the existing suite misses it: `jokes/tests.py::test_submit_complete_draft_pending` builds the
`JokeSubmission` through the ORM, so `text` stays `''` and the backfill never runs.

**Proposed fix** — in `jokes/views.py::JokeDraftSubmitView.post`, don't feed the derived field back
into the rule check; pass `'text': submission.text if 'text' not in FORMAT_RULES[slug]['forbidden'] else ''`
(or simply omit `text` for formats that forbid it). Cleaner still: stop persisting the backfill on the
draft and compute the display/search text at publish time in
`jokes/admin.py::JokeSubmissionAdmin.approve_and_publish`. Add a test that PATCHes then submits a
`setup` draft over the API.

## F4 · P2 (compliance quirk) — `is_removed` in `JokeAdmin` is a DSA statement-of-reasons bypass

**Test:** `T3-S05` · **Files:** `jokes/admin.py::JokeAdmin` (fieldsets / `readonly_fields`),
`jokes/serializers.py::AppealCreateSerializer`

`JokeAdmin` exposes `is_removed` as an editable field with `removed_at` read-only. A moderator who
ticks it on the change form gets a takedown with **none** of the compliance machinery that
`ContentReportAdmin.take_down_joke` provides: no `joke_removed` notification (statement of reasons +
14-day appeal deadline), no share-card blanking, no media quarantine, and — because `removed_at`
stays `NULL` — the creator's appeal is refused:

```
DB flip: is_removed= True | removed_at= None | share_image= None
GET /api/v1/jokes/493/                       -> 404
notifications for creator: before=19 after=19          (no notice sent)
POST /api/v1/appeals/ {"joke_id":493,…}      -> 400 {"non_field_errors":
                                                 ["This removal is not eligible for appeal."]}
quarantined assets for this joke = 0
```

The behaviour is *deliberately* guarded in the serializer (there is an explicit comment about the
`removed_at is None` case), so this is a known quirk rather than a crash — but the effect is a
one-click, audit-free way for staff to remove content with no appeal right, which is exactly what the
DSA wave was built to prevent.

**Proposed fix** — in `jokes/admin.py::JokeAdmin`, make `is_removed` read-only on the change form and
force removals through the report/takedown action (or through a new `JokeAdmin` action that calls the
same notify + quarantine + share-card path). At minimum, override `save_model` to refuse a
`False → True` transition and point the moderator at the takedown action.

## F5 · P2 (accepted design, worth an alarm) — SafeSearch fails OPEN with no signal

**Test:** `T3-M05` · **File:** `jokes/media_screening.py`

With `SAFESEARCH_ENABLED` false (no Vision credentials) `screen_image()` returns
`{'status': 'skipped'}`, the `blocked` branch in `MediaUploadView` is unreachable, and `get_matcher()`
is the dormant `NullMatcher`. A thrown Vision error yields `{'status': 'error'}` — also non-blocking,
by design (the fail-open hotfix). The upload is stored and fetchable at its URL before any human sees
it. This is documented and intentional (human review is the publish gate), but "screen disabled" and
"screen broken" are both silent, so a mis-configured production deploy would look identical to a
healthy one from the outside.

**Proposed fix** — no behaviour change needed; add observability. In `jokes/media_screening.py`, emit
a `jokesfor.metrics` counter (the pattern `jokes/serving.py` already uses) for
`safesearch_verdict{status=skipped|error|ok|blocked}` and alert on a non-zero `error`/`skipped` rate in
production. Optionally add a `readyz` warning when `SAFESEARCH_ENABLED` is false outside DEBUG.

## F6 · P2 (local-dev only, not a product defect) — `/media/…` URLs 404 on the local stack

**Test:** `T3-M03` (incidental) · **File:** `JokesForProject/urls.py`

`STORAGES['default']` falls back to `FileSystemStorage` when `GS_BUCKET_NAME` is unset, so upload and
share-card URLs are built as `http://localhost:8010/media/…`, but `urls.py` never adds a media-serving
route — every such URL 404s locally (`GET …/media/media-assets/<uuid>/image.webp -> 404`). Production
is unaffected (GCS returns absolute `storage.googleapis.com` URLs). Only relevant for local E2E: any
test that asserts an image actually loads must check the filesystem, not the URL.

**Proposed fix (optional)** — append
`+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)` guarded by `if settings.DEBUG:` in
`JokesForProject/urls.py`.

---

# Things that were verified as correct (highlights)

* **Takedown + reversal is genuinely reversible and leak-free** (`T3-S02`, `T3-S04`): media moves to
  `quarantine/<uuid>/<random-token>/`, the old public path is gone from storage, the share-card PNG is
  deleted and the field blanked, the reports auto-resolve, the creator gets a `joke_removed` notice
  carrying `{'reason': 'offensive', 'appeal_deadline': '…'}`; reversal releases the asset back to
  `media-assets/<uuid>/`, un-removes the joke, and regenerates the card on disk.
* **Appeal window/duplicate/ownership matrix is exactly as documented** (`T3-S03`): 201 once, 400 on a
  duplicate, 400 past 14 days, **404** (not 403) for someone else's joke — no existence leak.
* **Blocks are symmetric and complete** (`T3-S06`): jokes vanish from list/search, `Follow` rows are
  deleted both ways, both profiles 404, and unblocking restores all three.
* **Media validation matches the source limits exactly** (`T3-M04`): 10 MB image cap, JPEG/PNG/WebP
  only, 4096 px source cap, 60 s clip cap, unknown `kind`, missing file — every rejection is a 400 with
  the right field-keyed message and no orphan row.
* **Content-tier derivation at publish** (`T3-M07`, `T3-M07b`): `min_age >= 18` → `tier_2`, otherwise
  `tier_1`, plus exactly one `joke_published` inbox notification.
* **Billing is cleanly dormant** (`T3-B01`, `T3-B04a`, `T3-B04b`): 503
  `{"detail":"Billing is not configured.","code":"billing_unavailable"}` on all three money endpoints,
  a 200 `billing_dormant` no-op webhook that parses nothing, and — proved with dummy keys via
  `override_settings`, no signature forged — a 400 `"Invalid signature."` once billing is enabled.
* **Sitemap visibility mirrors the real anonymous read path** (`T3-O04`): 326 absolute *frontend* URLs,
  the 7 public static routes only, `tier_2` and removed jokes excluded, zero gated routes.
* **CORS** (`T3-O07`): the SPA origin gets `Access-Control-Allow-Origin` + `…-Credentials: true` +
  `x-csrftoken`; a foreign origin gets no ACAO header at all.
