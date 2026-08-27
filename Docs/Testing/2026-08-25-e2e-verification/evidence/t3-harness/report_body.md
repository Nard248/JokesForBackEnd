| ID | Area | Expected behaviour | Sanity | Result |
| --- | --- | --- | --- | --- |
| `T3-M01` | M | GIVEN an authenticated creator, WHEN they POST /jokes/my-drafts/ {format}, PATCH content into it (autosave, partial payloads accepted) and POST .../submit/, THEN the submission flips to status "pending" and every further PATCH/submit is refused 400 "Can only edit drafts or rejected submissions." | SENSIBLE | **PASS** |
| `T3-M01b` | M | GIVEN a draft in a format whose FORMAT_RULES forbid `text` (setup, anti, knock), WHEN the autosave PATCH runs, THEN JokeSubmissionCreateSerializer.validate() backfills submission.text from setup+punchline / lines, and the later POST .../submit/ re-validates that stored text against FORMAT_RULES and 400s "Not allowed for <format> format." forever — the creator cannot submit a complete, valid joke. | DEFECT-EXPECTED | **CONFIRMED-DEFECT** |
| `T3-M02` | M | GIVEN drafts that violate jokes/submission_rules.FORMAT_RULES, WHEN submitted, THEN 400 with the rule-specific message: knock <4 lines → "Knock format requires at least 4 lines."; story <30 words → "Story must be at least 30 words."; oneliner carrying setup/punchline → "Not allowed for oneliner format." on both fields. | SENSIBLE | **PASS** |
| `T3-M03` | M | GIVEN a valid 800x600 JPEG, WHEN POSTed multipart to /media/uploads/ with kind=image, THEN 201 {id,kind,url,poster_url,width,height,duration_ms,is_gif,created_at}, the URL is the WebP derivative (EXIF stripped by re-encode), a MediaAsset row exists, and the file is on disk under MEDIA_ROOT. | SENSIBLE | **PASS** |
| `T3-M04` | M | GIVEN media violating jokes/media_processing + jokes/media_probe limits (>10MB image, non-JPEG/PNG/WebP source, corrupt bytes, >4096px source, unknown kind, missing file, >60s clip), WHEN uploaded, THEN 400 with the specific {field: message} and no MediaAsset row. | SENSIBLE | **PASS** |
| `T3-M05` | M | GIVEN SAFESEARCH_ENABLED is false (no Vision credentials), WHEN an image is uploaded, THEN jokes/media_screening.screen_image returns {"status":"skipped"}, MediaUploadView's "blocked" branch is never reached, the CSAM hash matcher is a NullMatcher that returns None, and the file is stored and publicly readable at its URL before any human review. | QUESTIONABLE | **CONFIRMED-QUIRK** |
| `T3-M06` | M | GIVEN MediaUploadView, THEN it declares throttle_classes=[ScopedRateThrottle] with throttle_scope="media-upload", and settings.REST_FRAMEWORK maps that scope to 30/hour (verified by inspection rather than by firing 30 real uploads). | SENSIBLE | **PASS** |
| `T3-M07` | M | GIVEN a pending submission rated family-friendly (min_age 0), WHEN staff run the JokeSubmissionAdmin "Approve and publish selected submissions" action, THEN a Joke row is created with creator=submitter and content_tier derived from age_rating.min_age (tier_1), the submission flips to status="published" with published_joke set, and exactly one inbox Notification(verb="joke_published") is created for the creator. | SENSIBLE | **PASS** |
| `T3-M07b` | M | GIVEN a pending submission rated "adult" (min_age 18), WHEN approved, THEN the published Joke gets content_tier=tier_2 so jokes/serving.allowed_tiers keeps it away from anonymous and minor viewers. | SENSIBLE | **PASS** |
| `T3-S01` | S | GIVEN a reporter who already has a PENDING ContentReport on a joke, WHEN they POST /api/v1/reports/ for the same joke again, THEN the API returns 200 with the EXISTING report (original reason/description preserved) instead of 201, and no second row is created — the moderation queue cannot be stacked by one user. | SENSIBLE | **PASS** |
| `T3-S05` | S | GIVEN a moderator who ticks Joke.is_removed on the JokeAdmin change form (instead of running the ContentReport "Take down" action), WHEN they save, THEN the joke disappears from every read path, but removed_at stays NULL, no joke_removed notification / statement of reasons is sent, the media is never quarantined, and the creator's later POST /appeals/ is refused 400 "This removal is not eligible for appeal." — a DSA statement-of-reasons and appeal-right bypass reachable from the admin UI. | QUESTIONABLE | **CONFIRMED-QUIRK** |
| `T3-S02` | S | GIVEN a reported media joke, WHEN staff run the ContentReport "Take down reported joke" action, THEN the joke 404s on detail and vanishes from list/search, its public share page 404s, its share card PNG is deleted and the field blanked, its MediaAsset is moved from media-assets/<uuid>/ to quarantine/<uuid>/<random-token>/ (old path gone from storage), the reports are auto-resolved, and the creator gets a joke_removed statement-of-reasons notification carrying the reason and the 14-day appeal deadline. | SENSIBLE | **PASS** |
| `T3-S03` | S | GIVEN a creator whose joke was taken down, WHEN they POST /api/v1/appeals/ {joke_id, reason_text} inside the 14-day window, THEN 201 with a pending appeal; a second POST while that one is open is refused 400 (duplicate); a POST for someone else's joke is 404 (no existence leak); and a POST for a takedown older than 14 days is refused 400 "The 14-day appeal window for this takedown has passed." | SENSIBLE | **PASS** |
| `T3-S04` | S | GIVEN a pending takedown appeal, WHEN staff run the AppealAdmin "Reverse selected appeals" action, THEN the quarantined MediaAsset is moved back to media-assets/<uuid>/ with quarantined_at cleared, the joke flips is_removed=False / removed_at=NULL and serves again (API 200 + share page 200), a fresh share card PNG is written, the appeal becomes "reversed" with a resolver, and the creator gets an appeal_resolved notification. | SENSIBLE | **PASS** |
| `T3-S06` | S | GIVEN viewer V following creator C, WHEN V POSTs /users/{C}/block/, THEN C's jokes disappear from V's joke list/search (jokes.moderation.visible_jokes), the Follow rows are deleted in both directions, GET /creators/{C}/profile/ returns 404 for V (and symmetrically for C looking at V), C appears in GET /users/me/blocks/, and DELETE /users/{C}/block/ restores the jokes and the profile. | SENSIBLE | **PASS** |
| `T3-S07a` | S | GIVEN an authenticated user with favorites and a filed report, WHEN they GET /api/v1/users/me/data-export/, THEN 200 application/zip with Content-Disposition attachment containing jokes-for-data-export.json — a single JSON document with account/profile/preferences/collections/saved_jokes/favorites/ratings/reactions/views/streak/submissions/media_assets/reports_filed/blocks/... sections scoped to that user only. | SENSIBLE | **PASS** |
| `T3-S07b` | S | GIVEN an authenticated user with a usable password, WHEN they DELETE /api/v1/users/me/ with no password or the wrong one, THEN 400 with a field error and NOTHING is mutated — the account is still usable afterwards. | SENSIBLE | **PASS** |
| `T3-S07c` | S | GIVEN GDPR Art.17 erasure, WHEN a user DELETEs /api/v1/users/me/ with the correct password, THEN the account should cascade away (204). It does NOT: user.delete() has to SET_NULL AuditLog.actor, and audit.models.AuditLog carries a pgtrigger.Protect(Update\|Delete) "append_only" trigger, so Postgres raises "pgtrigger: Cannot update or delete rows from audit_auditlog table" and the request 500s. Every user acquires an AuditLog row on their first successful login (audit/signals.on_user_logged_in), so erasure is impossible for every real account. The transaction rolls the DB back, but the storage deletes in step 2 happen outside it — the user's uploaded media files are destroyed while their account and DB rows survive. | DEFECT-EXPECTED | **CONFIRMED-DEFECT** |
| `T3-B01` | B | GIVEN STRIPE_SECRET_KEY is unset so billing.stripe_gateway.is_enabled() is False, WHEN an authenticated user POSTs /billing/checkout-session, /billing/portal-session or /tips/checkout/, THEN each returns 503 with exactly {"detail":"Billing is not configured.","code":"billing_unavailable"} and no Stripe call is attempted — the dormant check runs before any argument validation. | SENSIBLE | **PASS** |
| `T3-B02` | B | GIVEN a user with no Subscription row, WHEN they GET /billing/plans (public), /billing/entitlements and /billing/my-subscription, THEN plans lists the active public plans unauthenticated; entitlements resolves plan="free" with limits.free_joke_reads_per_day=10 (the paywall cap), features.creator_analytics=true and the paid-only features false; my-subscription synthesizes {plan_slug:"free", status:"free", current_period_end:null}; and entitlements requires auth (401 for anon). | SENSIBLE | **PASS** |
| `T3-B04a` | B | GIVEN blank Stripe keys, WHEN an unauthenticated caller POSTs /billing/webhook with a missing or garbage Stripe-Signature, THEN the view short-circuits BEFORE signature verification and returns 200 {"detail":"billing_dormant"} (deliberate: Stripe must stop retrying a dormant endpoint) — no event is parsed, no handler runs, no ProcessedStripeEvent row is written. | SENSIBLE | **PASS** |
| `T3-B04b` | B | GIVEN STRIPE_SECRET_KEY/STRIPE_WEBHOOK_SECRET are configured, WHEN a webhook arrives with a missing or forged Stripe-Signature header, THEN construct_event raises SignatureVerificationError and the view returns 400 {"detail":"Invalid signature."} — billing.webhooks.handle_event is never reached and no ProcessedStripeEvent is written. (Proved with dummy keys via override_settings; no signature was forged.) | SENSIBLE | **PASS** |
| `T3-B05` | B | GIVEN billing is dormant, WHEN a user POSTs /tips/checkout/ with an off-tier amount or with themselves as the creator, THEN the response is still 503 billing_unavailable — is_enabled() is checked first, so the amount-tier and self-tip guards (which would return 400 invalid_amount / self_tip once Stripe is live) are unreachable and cannot be exercised here. | SENSIBLE | **PASS** |
| `T3-O01` | O | GIVEN a public tier_1 joke, WHEN /jokes/<id>/share/ is fetched, THEN a 200 HTML shell is returned carrying per-joke og:title/og:description/og:url/og:image, twitter:card=summary_large_image, <link rel=canonical> to the SPA joke URL and a schema.org CreativeWork JSON-LD block; the human bounce is a <meta http-equiv="refresh"> plus location.replace() rather than a 3xx. NOTE: jokes.views.joke_share_page does NOT branch on User-Agent — bot and browser get byte-identical responses; scrapers simply ignore the refresh/JS while browsers act on it. | SENSIBLE | **PASS** |
| `T3-O02` | O | GIVEN a two-part joke, WHEN its share page is scraped, THEN the teaser used for <title>, og:title, og:description, twitter:* and the JSON-LD name/headline is joke.setup ONLY — the punchline appears in none of them (the spoiler regression fixed in 56e4945 stays fixed). AND GIVEN a tier_2 (mature) joke fetched by an anonymous/minor requester, THEN share_redirect.html is rendered: robots=noindex, no og:description, no og:image, no JSON-LD, no joke text. | SENSIBLE | **PASS** |
| `T3-O02b` | O | GIVEN the paywall strips the punchline SERVER-SIDE for a free user over the 10-reads/day cap (JokeSerializer.to_representation), WHEN that same joke is fetched at the public, unauthenticated /jokes/<id>/share/ URL, THEN jokes/templates/jokes/share.html renders <p class="joke-text">{{ joke.text }}</p> — and Joke.text for a setup/anti/knock joke is the backfilled "setup punchline" (or the joined knock lines), i.e. the complete payoff. The share page applies only the content_tier gate, never paywall_state, so one anonymous GET returns what the API just refused. | DEFECT-EXPECTED | **CONFIRMED-DEFECT** |
| `T3-O03` | O | GIVEN /jokes/<id>/share/, WHEN the joke is removed, THEN get_object_or_404 on Joke.objects (whose manager already excludes is_removed) returns a bare 404 — byte-identical to the 404 for an id that never existed, so a scraper cannot tell "taken down" from "never existed". WHEN the joke merely exceeds the requester's content tier, THEN it is NOT a 404 (that would be a dead link for a real joke) but a 200 content-free share_redirect.html shell. | SENSIBLE | **PASS** |
| `T3-O04` | O | GIVEN an anonymous crawler, WHEN it GETs /sitemap.xml, THEN 200 application/xml with a sitemaps.org <urlset>; every <loc> is an absolute FRONTEND_URL route (never the backend host); the static section is exactly the 7 public marketing/legal routes; jokes are the tier_1 non-removed set an anonymous API caller can actually fetch (tier_2 excluded); creator and pack routes follow the same anonymous-visibility rule; and no authenticated / gated route (/library, /onboarding, /create, /settings, /inbox, ...) appears. | SENSIBLE | **PASS** |
| `T3-O07` | O | GIVEN CORS_ALLOWED_ORIGINS contains the SPA origin and CORS_ALLOW_CREDENTIALS is on, WHEN the browser sends OPTIONS with Origin: http://localhost:5273 and Access-Control-Request-Method: POST, THEN the response echoes Access-Control-Allow-Origin: http://localhost:5273, Access-Control-Allow-Credentials: true and allows the x-csrftoken header the cookie-JWT CSRF scheme depends on; WHEN the Origin is not allow-listed, THEN NO Access-Control-Allow-Origin header is returned and the browser blocks the request. | SENSIBLE | **PASS** |

@@SECTIONS@@

### T3-M01 — draft create → PATCH autosave → submit flips to pending and locks the draft

**Expected behaviour** — GIVEN an authenticated creator, WHEN they POST /jokes/my-drafts/ {format}, PATCH content into it (autosave, partial payloads accepted) and POST .../submit/, THEN the submission flips to status "pending" and every further PATCH/submit is refused 400 "Can only edit drafts or rejected submissions."

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
create id=99 keys=['age_rating', 'categories', 'context_tags', 'created_at', 'culture_tags', 'format', 'id', 'last_edited_at', 'likes', 'lines', 'media', 'punchline', 'rejection_reason', 'setup', 'status', 'text', 'themes', 'tones']; PATCH#1=200; PATCH#2=200; submit=200 {'id': 99, 'status': 'pending'}; re-PATCH=400 {'detail': 'Can only edit drafts or rejected submissions.'}; re-submit=400 {'detail': 'Can only submit drafts or rejected submissions for review.'}; GET.status=pending text='T3 autosave: a one-liner that made it all the way to review.'
```

---

### T3-M01b — a setup/anti/knock draft edited through the drafts editor can NEVER be submitted

**Expected behaviour** — GIVEN a draft in a format whose FORMAT_RULES forbid `text` (setup, anti, knock), WHEN the autosave PATCH runs, THEN JokeSubmissionCreateSerializer.validate() backfills submission.text from setup+punchline / lines, and the later POST .../submit/ re-validates that stored text against FORMAT_RULES and 400s "Not allowed for <format> format." forever — the creator cannot submit a complete, valid joke.

**Sanity verdict:** DEFECT-EXPECTED &nbsp;&nbsp; **Result:** **CONFIRMED-DEFECT**

**Evidence**

```
setup: draft=100 PATCH=200 submit=400 {'text': 'Not allowed for setup format.'} stored_text/status='Why did the draft cross the road? It never got there.' draft || anti: draft=101 PATCH=200 submit=400 {'text': 'Not allowed for anti format.'} stored_text/status='Two creators walk into a bar. Nothing happens.' draft || knock: draft=102 PATCH=200 submit=400 {'text': 'Not allowed for knock format.'} stored_text/status="Knock, knock. Who's there? Olive. Olive who?" draft || control POST /jokes/submit/ (no backfill re-read) = 201 {'id': 103, 'status': 'pending', 'created_at': '2026-08-25T10:42:13.825276Z'}
```

**Note.** Affects exactly the 3 formats that forbid `text`. Not caught by jokes/tests.py because test_submit_complete_draft_pending builds the JokeSubmission through the ORM (text stays "") instead of through the PATCH serializer. The SPA creator editor uses this exact path (src/features/create/api.ts).

---

### T3-M02 — per-format submit validation (knock/story/oneliner)

**Expected behaviour** — GIVEN drafts that violate jokes/submission_rules.FORMAT_RULES, WHEN submitted, THEN 400 with the rule-specific message: knock <4 lines → "Knock format requires at least 4 lines."; story <30 words → "Story must be at least 30 words."; oneliner carrying setup/punchline → "Not allowed for oneliner format." on both fields.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
knock/3-lines: 400 {'text': 'Not allowed for knock format.', 'lines': 'Knock format requires at least 4 lines.'}; story/29-words: 400 {'text': 'Story must be at least 30 words.'}; oneliner/forbidden-fields: 400 {'setup': 'Not allowed for oneliner format.', 'punchline': 'Not allowed for oneliner format.'}
```

**Note.** knock case also carries a spurious {"text": "Not allowed for knock format."} — the same autosave backfill proven in T3-M01b.

---

### T3-M03 — image upload normalizes to WebP + MediaAsset row + file on disk

**Expected behaviour** — GIVEN a valid 800x600 JPEG, WHEN POSTed multipart to /media/uploads/ with kind=image, THEN 201 {id,kind,url,poster_url,width,height,duration_ms,is_gif,created_at}, the URL is the WebP derivative (EXIF stripped by re-encode), a MediaAsset row exists, and the file is on disk under MEDIA_ROOT.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
HTTP 201 body={"id": "037c93a6-96bd-4b1e-b8b4-39d3cc39799e", "kind": "image", "url": "http://localhost:8010/media/media-assets/037c93a6-96bd-4b1e-b8b4-39d3cc39799e/image.webp", "poster_url": null, "width": 800, "height": 600, "duration_ms": null, "is_gif": false, "created_at": "2026-08-25T10:42:14.092256Z"} | DB/disk: media-assets/037c93a6-96bd-4b1e-b8b4-39d3cc39799e/image.webp |exists= True |bytes= 946 |safesearch= {'status': 'skipped'} |phash= 0000000000000000 |owner= 698 | GET url -> 404 text/html; charset=utf-8
```

---

### T3-M04 — oversize / wrong-type / over-long media rejected with a clear, field-keyed error

**Expected behaviour** — GIVEN media violating jokes/media_processing + jokes/media_probe limits (>10MB image, non-JPEG/PNG/WebP source, corrupt bytes, >4096px source, unknown kind, missing file, >60s clip), WHEN uploaded, THEN 400 with the specific {field: message} and no MediaAsset row.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
oversize-11MB=400 {'file': 'Image exceeds the 10MB limit.'}; wrong-format-BMP=400 {'file': 'Only JPEG, PNG, or WebP images are supported.'}; not-an-image=400 {'file': 'Not a valid image.'}; dims-5000px=400 {'file': 'Image dimensions exceed 4096px.'}; bad-kind=400 {'kind': ['Unsupported kind.']}; no-file=400 {'file': ['This field is required.']}; video-65s=400 {'file': 'Clips must be 60 seconds or shorter.'} | assets for t3creator = 8
```

**Note.** all rejections matched the source-derived messages

---

### T3-M05 — SafeSearch with no Vision credentials fails OPEN — upload stored, verdict "skipped"

**Expected behaviour** — GIVEN SAFESEARCH_ENABLED is false (no Vision credentials), WHEN an image is uploaded, THEN jokes/media_screening.screen_image returns {"status":"skipped"}, MediaUploadView's "blocked" branch is never reached, the CSAM hash matcher is a NullMatcher that returns None, and the file is stored and publicly readable at its URL before any human review.

**Sanity verdict:** QUESTIONABLE &nbsp;&nbsp; **Result:** **CONFIRMED-QUIRK**

**Evidence**

```
SAFESEARCH_ENABLED= False | stored verdict= {'status': 'skipped'}
screen_image(any bytes) -> {'status': 'skipped'}
get_matcher() -> NullMatcher | match() -> None
```

**Note.** Deliberate (module docstring + the fail-open hotfix for thrown Vision errors), but it means a mis-configured/broken Vision integration silently disables the NSFW/CSAM pre-screen with no alarm — status "skipped" and status "error" are both stored and both non-blocking. The admin review queue is the only remaining gate, and the asset is already fetchable at its unguessable-but-public URL.

---

### T3-M06 — media-upload throttle scope is wired and rated 30/hour

**Expected behaviour** — GIVEN MediaUploadView, THEN it declares throttle_classes=[ScopedRateThrottle] with throttle_scope="media-upload", and settings.REST_FRAMEWORK maps that scope to 30/hour (verified by inspection rather than by firing 30 real uploads).

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
throttle_scope= media-upload | classes= ['ScopedRateThrottle'] | media-upload rate= 30/hour | appeals= 10/day | tips-checkout= 30/hour | anon= 100/hour | user= 1000/hour
```

---

### T3-M07 — staff approval publishes the joke with a derived tier and notifies the creator

**Expected behaviour** — GIVEN a pending submission rated family-friendly (min_age 0), WHEN staff run the JokeSubmissionAdmin "Approve and publish selected submissions" action, THEN a Joke row is created with creator=submitter and content_tier derived from age_rating.min_age (tier_1), the submission flips to status="published" with published_joke set, and exactly one inbox Notification(verb="joke_published") is created for the creator.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
sub.status= published | joke_id= 501 | content_tier= tier_1 | creator_id= 698 | age_rating= family-friendly | share_image= True
notif_delta= 1 | verb= joke_published | joke= 501 | data= {}
```

---

### T3-M07b — an adult-rated (min_age>=18) submission publishes as tier_2, not universal tier_1

**Expected behaviour** — GIVEN a pending submission rated "adult" (min_age 18), WHEN approved, THEN the published Joke gets content_tier=tier_2 so jokes/serving.allowed_tiers keeps it away from anonymous and minor viewers.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
status= published | joke_id= 502 | content_tier= tier_2
```

---

### T3-S01 — duplicate report by the same reporter returns the existing pending report (200, not 201)

**Expected behaviour** — GIVEN a reporter who already has a PENDING ContentReport on a joke, WHEN they POST /api/v1/reports/ for the same joke again, THEN the API returns 200 with the EXISTING report (original reason/description preserved) instead of 201, and no second row is created — the moderation queue cannot be stacked by one user.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
first=201 {'joke': 493, 'reason': 'offensive', 'description': 'T3-S01 first report'} | second=200 {'joke': 493, 'reason': 'offensive', 'description': 'T3-S01 first report'} | DB rows= 1 [{'id': 13, 'reason': 'offensive', 'status': 'pending', 'description': 'T3-S01 first report'}]
```

---

### T3-S05 — a raw is_removed flip in JokeAdmin hides the joke with NO DSA notice and NO appeal right

**Expected behaviour** — GIVEN a moderator who ticks Joke.is_removed on the JokeAdmin change form (instead of running the ContentReport "Take down" action), WHEN they save, THEN the joke disappears from every read path, but removed_at stays NULL, no joke_removed notification / statement of reasons is sent, the media is never quarantined, and the creator's later POST /appeals/ is refused 400 "This removal is not eligible for appeal." — a DSA statement-of-reasons and appeal-right bypass reachable from the admin UI.

**Sanity verdict:** QUESTIONABLE &nbsp;&nbsp; **Result:** **CONFIRMED-QUIRK**

**Evidence**

```
flip: is_removed= True | removed_at= None | share_image= None | GET joke -> 404 | notifications before=19 after=19 | appeal -> 400 {'non_field_errors': ['This removal is not eligible for appeal.']} | quarantined assets for this joke = 0
```

---

### T3-S02 — staff takedown hides the joke everywhere and quarantines its media to an unguessable path

**Expected behaviour** — GIVEN a reported media joke, WHEN staff run the ContentReport "Take down reported joke" action, THEN the joke 404s on detail and vanishes from list/search, its public share page 404s, its share card PNG is deleted and the field blanked, its MediaAsset is moved from media-assets/<uuid>/ to quarantine/<uuid>/<random-token>/ (old path gone from storage), the reports are auto-resolved, and the creator gets a joke_removed statement-of-reasons notification carrying the reason and the 14-day appeal deadline.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
report=201 | pre file= media-assets/9710fe27-ca90-43da-b23f-f068e51f89bc/image.webp | quarantined= None | share_image= share-cards/joke-499_5q7aC7y.png || after takedown: is_removed= True | removed_at set= True | share_image= ''
asset file= quarantine/9710fe27-ca90-43da-b23f-f068e51f89bc/dTGKpWR2Bsj51LMNtTfFOQ/image.webp | quarantined_at set= True
notice verb= joke_removed | data= {'reason': 'offensive', 'appeal_deadline': '2026-09-08T10:34:08.051321+00:00'}
reports now= ['resolved']
old public path exists= False
new path exists= True || GET detail=404 | search count=0 | share page=404 | old media URL http://localhost:8010/media/media-assets/9710fe27-ca90-43da-b23f-f068e51f89bc/image.webp -> served-from=asset file= quarantine/9710fe27-ca90-43da-b23f-f068e51f89bc/dTGKpWR2Bsj51LMNtTfFOQ/image.webp | quarantined_at set= True
```

---

### T3-S03 — appeal accepted once inside the 14-day window; duplicate 400; lapsed window 400; foreign 404

**Expected behaviour** — GIVEN a creator whose joke was taken down, WHEN they POST /api/v1/appeals/ {joke_id, reason_text} inside the 14-day window, THEN 201 with a pending appeal; a second POST while that one is open is refused 400 (duplicate); a POST for someone else's joke is 404 (no existence leak); and a POST for a takedown older than 14 days is refused 400 "The 14-day appeal window for this takedown has passed."

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
first=201 {'id': 5, 'action_type': 'takedown', 'status': 'pending', 'reason_text': 'T3-S03: this is my own joke, please review.', 'target_type': 'joke', 'target_id': 499, 'target_preview': 'T3MJ1787654044 the moderation wave test image joke', 'created_at': '2026-08-25T1 | duplicate=400 {'non_field_errors': ['An appeal is already pending for this joke.']} | other-user=404 {'detail': 'Joke not found.'} | lapsed(joke 498)=400 {'non_field_errors': ['The 14-day appeal window for this takedown has passed.']} | DB [{'id': 5, 'joke_id': 499, 'status': 'pending', 'action_type': 'takedown'}]
```

---

### T3-S04 — reversing an appeal restores the joke, releases the media, and regenerates the share card

**Expected behaviour** — GIVEN a pending takedown appeal, WHEN staff run the AppealAdmin "Reverse selected appeals" action, THEN the quarantined MediaAsset is moved back to media-assets/<uuid>/ with quarantined_at cleared, the joke flips is_removed=False / removed_at=NULL and serves again (API 200 + share page 200), a fresh share card PNG is written, the appeal becomes "reversed" with a resolver, and the creator gets an appeal_resolved notification.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
appeal.status= reversed | resolver= e2eadmin
joke.is_removed= False | removed_at= None | share_image= 'share-cards/joke-499_GEgzSJq.png' | card on disk= True
asset file= media-assets/9710fe27-ca90-43da-b23f-f068e51f89bc/image.webp | quarantined_at= None | file on disk= True
notice= appeal_resolved {'outcome': 'reversed', 'action_type': 'takedown'} || GET detail=200 | share page=200
```

---

### T3-S06 — blocking a creator hides their jokes, severs follows both ways and 404s their profile; unblocking restores all three

**Expected behaviour** — GIVEN viewer V following creator C, WHEN V POSTs /users/{C}/block/, THEN C's jokes disappear from V's joke list/search (jokes.moderation.visible_jokes), the Follow rows are deleted in both directions, GET /creators/{C}/profile/ returns 404 for V (and symmetrically for C looking at V), C appears in GET /users/me/blocks/, and DELETE /users/{C}/block/ restores the jokes and the profile.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
follow=201 | before: feed=1 profile=200 || block=201 {'status': 'blocked'} | after: feed=0 profile=404 follow rows= 0 | my-blocks=1 | symmetric reverse-profile=404 || unblock=204 | restored: feed=1 profile=200
```

---

### T3-S07a — GET /users/me/data-export/ returns the caller's own data as a downloadable ZIP of JSON

**Expected behaviour** — GIVEN an authenticated user with favorites and a filed report, WHEN they GET /api/v1/users/me/data-export/, THEN 200 application/zip with Content-Disposition attachment containing jokes-for-data-export.json — a single JSON document with account/profile/preferences/collections/saved_jokes/favorites/ratings/reactions/views/streak/submissions/media_assets/reports_filed/blocks/... sections scoped to that user only.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
HTTP 200 ct=application/zip cd=attachment; filename="jokes-for-data-export.zip" bytes=1104 | {"zip_entries": ["jokes-for-data-export.json"], "top_level_keys": ["account", "achievements", "blocks", "collections", "daily_jokes", "email_logs", "export_meta", "favorites", "media_assets", "mystery_rolls", "pack_progress", "preferences", "profile", "ratings", "reactions", "reports_filed", "saved_jokes", "share_events", "streak", "streak_days", "submissions", "vibes", "views"], "account": {"id": 702, "email": "t3.gdpr@e2e.dev", "username": "t3gdpr", "date_joined": "2026-08-25T10:22:26.036Z", "last_login": null, "is_active": true}, "reports_filed": [{"joke_id": 499, "reason": "other", "description": "T3-S07 export probe", "status": "pending", "created_at": "2026-08-25T10:34:10.840Z"}], "favorites_n": 5}
```

---

### T3-S07b — DELETE /users/me/ refuses to act without a correct password (re-authentication gate)

**Expected behaviour** — GIVEN an authenticated user with a usable password, WHEN they DELETE /api/v1/users/me/ with no password or the wrong one, THEN 400 with a field error and NOTHING is mutated — the account is still usable afterwards.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
no-password=400 {'password': ['This field is required.']} | wrong-password=400 {'password': ['Incorrect password.']} | account still usable: GET profile=200
```

---

### T3-S07c — DELETE /users/me/ 500s for any user who has ever logged in — GDPR erasure is unreachable

**Expected behaviour** — GIVEN GDPR Art.17 erasure, WHEN a user DELETEs /api/v1/users/me/ with the correct password, THEN the account should cascade away (204). It does NOT: user.delete() has to SET_NULL AuditLog.actor, and audit.models.AuditLog carries a pgtrigger.Protect(Update|Delete) "append_only" trigger, so Postgres raises "pgtrigger: Cannot update or delete rows from audit_auditlog table" and the request 500s. Every user acquires an AuditLog row on their first successful login (audit/signals.on_user_logged_in), so erasure is impossible for every real account. The transaction rolls the DB back, but the storage deletes in step 2 happen outside it — the user's uploaded media files are destroyed while their account and DB rows survive.

**Sanity verdict:** DEFECT-EXPECTED &nbsp;&nbsp; **Result:** **CONFIRMED-DEFECT**

**Evidence**

```
before: asset file= media-assets/2d2a05bf-32df-4b7c-bd21-55b40321df74/image.webp | on disk= True
audit rows for this user= 15 ['media_upload', 'data_export', 'content_report', 'media_upload', 'data_export', 'content_report', 'media_upload', 'data_export', 'content_report', 'media_upload', 'data_export', 'content_report', 'data_export', 'data_export', 'content_report'] || DELETE (correct password) -> 500 | session still alive afterwards: GET profile=200 || after: user row still present= True
media row survived= True | FILE still on disk= False
favorites left= 5 | reports left= 1 || controlled experiment: no audit row  -> HTTP 204
one audit row -> InternalError: pgtrigger: Cannot update or delete rows from audit_auditlog table
audited probe user still exists = True
```

**Note.** Backend traceback: jokes/views.py:2485 user.delete() -> django/db/models/deletion.py field_updates -> UPDATE audit_auditlog SET actor_id=NULL -> InternalError "pgtrigger: Cannot update or delete rows from audit_auditlog table". The AuditLog.actor docstring literally says "NULL after account deletion (SET_NULL)" — the append-only trigger contradicts it.

---

### T3-B01 — every money-moving endpoint is dormant (503 billing_unavailable) with blank Stripe keys

**Expected behaviour** — GIVEN STRIPE_SECRET_KEY is unset so billing.stripe_gateway.is_enabled() is False, WHEN an authenticated user POSTs /billing/checkout-session, /billing/portal-session or /tips/checkout/, THEN each returns 503 with exactly {"detail":"Billing is not configured.","code":"billing_unavailable"} and no Stripe call is attempted — the dormant check runs before any argument validation.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
checkout=503 {'detail': 'Billing is not configured.', 'code': 'billing_unavailable'} | portal=503 {'detail': 'Billing is not configured.', 'code': 'billing_unavailable'} | tip=503 {'detail': 'Billing is not configured.', 'code': 'billing_unavailable'}
```

---

### T3-B02 — a FREE user sees the free plan, the 10-reads/day limit and a synthetic "free" subscription

**Expected behaviour** — GIVEN a user with no Subscription row, WHEN they GET /billing/plans (public), /billing/entitlements and /billing/my-subscription, THEN plans lists the active public plans unauthenticated; entitlements resolves plan="free" with limits.free_joke_reads_per_day=10 (the paywall cap), features.creator_analytics=true and the paid-only features false; my-subscription synthesizes {plan_slug:"free", status:"free", current_period_end:null}; and entitlements requires auth (401 for anon).

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
plans(anon)=200 [{"slug": "free", "name": "Free", "description": "Get started with JokesFor at no cost.", "interval": "", "amount_cents": null, "currency": "usd", "amount_display": "Free", "features": {"creator_analytics": true, "daily_joke_preview": false, "mature_content_addon": false}, "limits": {"daily_jokes_pe | entitlements=200 {"plan": "free", "features": {"creator_analytics": true, "daily_joke_preview": false, "mature_content_addon": false}, "limits": {"mystery_box_rolls_per_day": 3, "submissions_per_day": 5, "daily_jokes_per_day": 1, "daily_joke_history_days": 30, "free_joke_reads_per_day": 10}} | my-subscription=200 {"plan_slug": "free", "plan_name": "Free", "status": "free", "current_period_end": null, "cancel_at_period_end": false, "stripe_customer_id": ""} | entitlements(anon)=401
```

---

### T3-B04a — while dormant the webhook 200-noops on ANY body/signature and processes nothing

**Expected behaviour** — GIVEN blank Stripe keys, WHEN an unauthenticated caller POSTs /billing/webhook with a missing or garbage Stripe-Signature, THEN the view short-circuits BEFORE signature verification and returns 200 {"detail":"billing_dormant"} (deliberate: Stripe must stop retrying a dormant endpoint) — no event is parsed, no handler runs, no ProcessedStripeEvent row is written.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
no-signature=200 {'detail': 'billing_dormant'} | garbage-signature=200 {'detail': 'billing_dormant'} | DB processed events= 0
```

---

### T3-B04b — with billing enabled, an unsigned/garbage-signed webhook is rejected 400 before any handler

**Expected behaviour** — GIVEN STRIPE_SECRET_KEY/STRIPE_WEBHOOK_SECRET are configured, WHEN a webhook arrives with a missing or forged Stripe-Signature header, THEN construct_event raises SignatureVerificationError and the view returns 400 {"detail":"Invalid signature."} — billing.webhooks.handle_event is never reached and no ProcessedStripeEvent is written. (Proved with dummy keys via override_settings; no signature was forged.)

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
missing -> 400 b'{"detail":"Invalid signature."}'
garbage -> 400 b'{"detail":"Invalid signature."}'
processed events after= 0
```

---

### T3-B05 — the dormant guard short-circuits BEFORE tip amount/creator validation

**Expected behaviour** — GIVEN billing is dormant, WHEN a user POSTs /tips/checkout/ with an off-tier amount or with themselves as the creator, THEN the response is still 503 billing_unavailable — is_enabled() is checked first, so the amount-tier and self-tip guards (which would return 400 invalid_amount / self_tip once Stripe is live) are unreachable and cannot be exercised here.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
bad-amount=503 {'detail': 'Billing is not configured.', 'code': 'billing_unavailable'} | self-tip=503 {'detail': 'Billing is not configured.', 'code': 'billing_unavailable'} | DB tip rows= 0
```

**Note.** Not a defect — just the ordering. Amount-tier / self-tip / not-a-creator guards were read in billing/views.py TipCheckoutView and are only reachable with live keys.

---

### T3-O01 — the share page always renders crawler metadata and bounces humans client-side

**Expected behaviour** — GIVEN a public tier_1 joke, WHEN /jokes/<id>/share/ is fetched, THEN a 200 HTML shell is returned carrying per-joke og:title/og:description/og:url/og:image, twitter:card=summary_large_image, <link rel=canonical> to the SPA joke URL and a schema.org CreativeWork JSON-LD block; the human bounce is a <meta http-equiv="refresh"> plus location.replace() rather than a 3xx. NOTE: jokes.views.joke_share_page does NOT branch on User-Agent — bot and browser get byte-identical responses; scrapers simply ignore the refresh/JS while browsers act on it.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
bot UA -> 200 (4174B), browser UA -> 200 (4174B), identical=True | og:title='T3SETUP1787654282 why does the share page need a regression…' | og:description='T3SETUP1787654282 why does the share page need a regression test?' | og:image='http://localhost:8010/media/share-cards/joke-500_UoCohJf.png' | og:url='http://localhost:5273/jokes/500' | twitter:card='summary_large_image' | canonical='http://localhost:5273/jokes/500' | json-ld={"@context": "https://schema.org", "@type": "CreativeWork", "name": "T3SETUP1787654282 why does the share page need a regression\u2026", "headline": "T3SETUP1787654282 why does the share page need a regression\u2026", "url": "http://localhost:5273/jokes/500", "author": {"@type": "Organization", "name": "JokesFor"}, "image": "http://localhost:8010/media/share-cards/joke-500_UoCohJf.png"} | meta-refresh='http://localhost:5273/jokes/500' | js location.replace=True
```

**Note.** No UA sniffing exists; "redirect for humans" is purely client-side. A crawler that executes JS (Googlebot does) will also follow it to the SPA.

---

### T3-O02 — the punchline never reaches og:title / og:description / <title> / JSON-LD, and a tier-gated share page exposes no content at all

**Expected behaviour** — GIVEN a two-part joke, WHEN its share page is scraped, THEN the teaser used for <title>, og:title, og:description, twitter:* and the JSON-LD name/headline is joke.setup ONLY — the punchline appears in none of them (the spoiler regression fixed in 56e4945 stays fixed). AND GIVEN a tier_2 (mature) joke fetched by an anonymous/minor requester, THEN share_redirect.html is rendered: robots=noindex, no og:description, no og:image, no JSON-LD, no joke text.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
punchline in og:title/description = False; in <title> = False; in JSON-LD = False | tier_2 joke 494 -> HTTP 200, len=1466, og:description=None, og:image=None, json-ld present=False, robots='noindex'
```

---

### T3-O02b — the share page body serves the FULL joke text (punchline included) to anyone, bypassing the server-side paywall strip

**Expected behaviour** — GIVEN the paywall strips the punchline SERVER-SIDE for a free user over the 10-reads/day cap (JokeSerializer.to_representation), WHEN that same joke is fetched at the public, unauthenticated /jokes/<id>/share/ URL, THEN jokes/templates/jokes/share.html renders <p class="joke-text">{{ joke.text }}</p> — and Joke.text for a setup/anti/knock joke is the backfilled "setup punchline" (or the joined knock lines), i.e. the complete payoff. The share page applies only the content_tier gate, never paywall_state, so one anonymous GET returns what the API just refused.

**Sanity verdict:** DEFECT-EXPECTED &nbsp;&nbsp; **Result:** **CONFIRMED-DEFECT**

**Evidence**

```
distinct reads today= 10 | API GET /jokes/500/ as capped free user -> is_locked=True, punchline=None, text='T3SETUP1787654282 why does the share page need a regression ' || anonymous GET /jokes/500/share/ -> 200, <p class="joke-text"> = 'T3SETUP1787654282 why does the share page need a regression test? T3PUNCH1787654282 because the punchline is the whole product.', contains punchline = True
```

**Note.** Also an SEO spoiler: the body text a crawler indexes still contains the punchline even though 56e4945 scrubbed it from the meta tags.

---

### T3-O03 — removed and non-existent share pages are indistinguishable 404s; a tier-gated one is a content-free 200 redirect shell

**Expected behaviour** — GIVEN /jokes/<id>/share/, WHEN the joke is removed, THEN get_object_or_404 on Joke.objects (whose manager already excludes is_removed) returns a bare 404 — byte-identical to the 404 for an id that never existed, so a scraper cannot tell "taken down" from "never existed". WHEN the joke merely exceeds the requester's content tier, THEN it is NOT a 404 (that would be a dead link for a real joke) but a 200 content-free share_redirect.html shell.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
removed joke 499 -> 404 (3094B) | non-existent 99999999 -> 404 (3109B) | tier_2 joke 494 -> 200 (1466B, content-free shell)
```

**Note.** The two 404 bodies are Django DEBUG pages locally; in production DEBUG=False makes them the same generic 404. Neither carries joke content.

---

### T3-O04 — GET /sitemap.xml is valid sitemap XML of crawlable FRONTEND routes with gated routes excluded

**Expected behaviour** — GIVEN an anonymous crawler, WHEN it GETs /sitemap.xml, THEN 200 application/xml with a sitemaps.org <urlset>; every <loc> is an absolute FRONTEND_URL route (never the backend host); the static section is exactly the 7 public marketing/legal routes; jokes are the tier_1 non-removed set an anonymous API caller can actually fetch (tier_2 excluded); creator and pack routes follow the same anonymous-visibility rule; and no authenticated / gated route (/library, /onboarding, /create, /settings, /inbox, ...) appears.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
HTTP 200 ct=application/xml bytes=26577 | urls=326 | statics=['/', '/childrens-privacy', '/cookie-policy', '/daily', '/privacy', '/terms', '/trending'] | jokes=311 | creators=4 | packs=4 | gated routes present=[] | new joke 500 listed=True | tier_2 joke 494 listed=False
```

---

### T3-O07 — CORS preflight from the SPA origin is allowed with credentials; a foreign origin is not

**Expected behaviour** — GIVEN CORS_ALLOWED_ORIGINS contains the SPA origin and CORS_ALLOW_CREDENTIALS is on, WHEN the browser sends OPTIONS with Origin: http://localhost:5273 and Access-Control-Request-Method: POST, THEN the response echoes Access-Control-Allow-Origin: http://localhost:5273, Access-Control-Allow-Credentials: true and allows the x-csrftoken header the cookie-JWT CSRF scheme depends on; WHEN the Origin is not allow-listed, THEN NO Access-Control-Allow-Origin header is returned and the browser blocks the request.

**Sanity verdict:** SENSIBLE &nbsp;&nbsp; **Result:** **PASS**

**Evidence**

```
allowed origin -> 200 ACAO='http://localhost:5273' ACAC='true' ACAH='accept, authorization, content-type, user-agent, x-csrftoken, x-requested-with, x-csrftoken' ACAM='DELETE, GET, OPTIONS, PATCH, POST, PUT' || foreign origin -> 200 ACAO=None
```
