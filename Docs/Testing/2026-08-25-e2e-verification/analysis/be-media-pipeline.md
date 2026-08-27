# Backend Media Jokes Pipeline — Deep Dive (be-media-pipeline)

Repo: `/Users/narekmeloyan/PycharmProjects/JokesForProject` (Django 5.2 / DRF / Postgres / Cloud Run)
Analysis date: 2026-08-25. All facts below are from code unless labelled "spec". Line numbers are current as of HEAD `56e4945`.

## 0. File map

| Concern | File |
|---|---|
| ffprobe wrapper | `jokes/media_probe.py` (89 lines) |
| Image normalize (Pillow) + video/GIF/audio normalize (ffmpeg) + concurrency guard | `jokes/media_processing.py` (373 lines) |
| Google Vision SafeSearch + dormant CSAM HashMatcher seam | `jokes/media_screening.py` (85 lines) |
| Models: `Joke.share_image` + save() card logic, `MediaAsset`, `JokeSubmissionMedia`, `JokeMedia`, `JokeWatch`, `Appeal` | `jokes/models.py` L101-277, L1201-1235, L1406-1560 |
| Quarantine lazy-expiry sweep | `jokes/quarantine.py` |
| Share-card PNG generation (cairosvg + Pillow) | `jokes/share_cards.py` |
| SVG card templates | `jokes/templates/jokes/share_cards/{base_card,dad_joke,dark_humor,pun,media_card}.svg` |
| OG share page + redirect shell | `jokes/templates/jokes/share.html`, `share_redirect.html`; view `jokes/views.py::joke_share_page` L1352-1428 |
| Upload endpoint | `jokes/views.py::MediaUploadView` L1480-1622, helpers `_sweep_orphan_assets` L1436, `_finalize_media_upload` L1448 |
| Serializers (asset shape, paywall lock/strip, dims-only) | `jokes/serializers.py` L139-406, L813-831 (drafts), L864-991 (attach) |
| Per-format rules incl. media constraints | `jokes/submission_rules.py` |
| Admin: approve/publish, takedown+quarantine, restore, appeal uphold/reverse, media preview, safesearch flags | `jokes/admin.py` L95-165, L255-380, L421-540, L621-760 |
| Storage config, SafeSearch flag, throttles | `JokesForProject/settings.py` L234-286, L312 |
| Template filter used by media card | `jokes/templatetags/mathfilters.py` (`multiply`) — a LOCAL tag lib, NOT the PyPI `django-mathfilters` package |
| Backfill command | `jokes/management/commands/backfill_share_cards.py` |
| Runtime deps | `Dockerfile` (ffmpeg, libcairo2, libpango*), `requirements.txt` (cairosvg 2.9.0, Pillow 12.3.0, django-storages[google] 1.14.6, google-cloud-storage 3.12.0, google-cloud-vision 3.10.2), `.github/workflows/ci.yml` L57-67 (apt installs ffmpeg + cairo for tests) |
| Tests | `jokes/tests_media.py`, `tests_media_wave2.py`, `tests_share_cards.py`, `tests_share_page.py`, `tests_storage.py`, `tests_backfill_share_cards.py`, `tests_appeals.py` (quarantine lifecycle), `tests_compliance.py::ServingLockTests` (share-page tier gating) |
| Specs | `Docs/superpowers/specs/2026-07-20-media-jokes-design.md`, `2026-07-24-media-share-cards-design.md`; plans `Docs/superpowers/plans/2026-07-2{0,2,4}-media-*.md` |

There is **no** `jokes/storage*.py` — storage is configured purely in settings via django-storages.

## 1. Environment variables / flags (complete list touching this pipeline)

| Var | Where read | Effect |
|---|---|---|
| `GS_BUCKET_NAME` | `settings.py` L279 → `build_default_storage()` L241 | Non-empty → `STORAGES['default']` = `storages.backends.gcloud.GoogleCloudStorage` with `default_acl=None`, `querystring_auth=False`, `file_overwrite=True` (stable public `https://storage.googleapis.com/<bucket>/<path>` URLs; no signed URLs). Empty → `FileSystemStorage` at `MEDIA_ROOT = BASE_DIR/'media'`, `MEDIA_URL='/media/'`. |
| `GS_PROJECT_ID` | L264 | Optional `project_id` option for GCS. |
| `GS_LOCATION` | L267 | Optional path prefix inside the bucket. |
| `GOOGLE_APPLICATION_CREDENTIALS` | (google libs, via ADC) | Only for local prod-like testing; Cloud Run uses the attached SA (ADC). Documented in `.env.example` L57-68. |
| `SAFESEARCH_ENABLED` | L286: `os.getenv('SAFESEARCH_ENABLED','').strip().lower() in ('1','true','yes')` | Gates Vision SafeSearch. Default **off** → `screen_image` returns `{'status':'skipped'}`. Memory notes say it is LIVE in prod. |
| `FRONTEND_URL` | L357 (default `https://jokesforfront.web.app`) | Share page redirect/canonical/og:url target; also appended to `CSRF_TRUSTED_ORIGINS`. |
| `BACKEND_URL` | L490 | Not used by the media pipeline (digest unsubscribe links) — share page uses `request.build_absolute_uri`. |
| `PORT`, `K_REVISION`, `GOOGLE_CLOUD_PROJECT` | Dockerfile / logging | Not media-specific. |
| DRF throttle `media-upload: 30/hour` | L312 | Scoped throttle on `MediaUploadView`. Not env-driven. |
| gunicorn `--timeout 300 --workers 2 --threads 4 --worker-class gthread` | `Dockerfile` L69-75 | Request ceiling for in-request transcode. |

Not set: `FILE_UPLOAD_MAX_MEMORY_SIZE` / `DATA_UPLOAD_MAX_MEMORY_SIZE` (Django defaults: 2.5MB → uploads above that arrive as `TemporaryUploadedFile` on disk, which `_source_path()` reuses without copying). Cloud Run HTTP/1 ingress hard-rejects bodies > 32MiB before Django (comment `media_processing.py` L136-139) — this is why `MAX_VIDEO_BYTES` is 30MB.

Hard-coded constants (not env-tunable): `MAX_IMAGE_BYTES=10MB`, `MAX_SOURCE_DIM=4096`, `OUT_MAX_DIM=1600`, `OUT_QUALITY=82` (`media_processing.py` L16-20); `MAX_VIDEO_BYTES=30MB`, `MAX_GIF_BYTES=15MB`, `MAX_AUDIO_BYTES=10MB`, `MAX_MEDIA_DURATION_MS=60_000`, `MAX_VIDEO_PIXELS=1920*1080*1.2`, `FFMPEG_TIMEOUT=240s` (L140-145); `FFPROBE_TIMEOUT=30s` (`media_probe.py` L15); `_ENCODE_SLOTS = BoundedSemaphore(1)` per worker process (L154); orphan sweep cutoff 24h (`views.py` L1439); quarantine purge window 14 days (`quarantine.py` L26); share card 1200x630 and raster `MAX_RASTER_WIDTH=1200` (`share_cards.py` L13).

## 2. Upload endpoint — `POST /api/v1/media/uploads/`

Route: `jokes/urls.py` L32 → `MediaUploadView` (`views.py` L1480). `permission_classes=[IsAuthenticated]`, `parser_classes=[MultiPartParser, FormParser]`, `throttle_classes=[ScopedRateThrottle]`, `throttle_scope='media-upload'` (30/hour/user). No email-verification or creator-role check on this view beyond IsAuthenticated (verify elsewhere if needed).

Request body (multipart): `file` (required) and `kind` ∈ `{'image','video','audio'}` (default `'image'`; any other → 400 `{"kind":["Unsupported kind."]}`; missing file → 400 `{"file":["This field is required."]}`).

GIF routing (L1509-1511): `is_gif = content_type == 'image/gif' or name.endswith('.gif')` — **a GIF is always routed through the video pipeline regardless of `kind`** (even `kind=image` or `kind=audio`… note: `kind=='audio'` branch is checked before the `else` so `kind=audio` + `.gif` goes to `process_audio`, which then fails with "This looks like a video"; only `image`/`video` kinds route GIF to video).

### 2.1 Image branch (`kind=image`, not GIF) — `process_image` (`media_processing.py` L63-116)
1. Size check ≤ 10MB (uses `uploaded.size`, or seeks to measure) → 400 `Image exceeds the 10MB limit.`
2. `Image.open().verify()`; DecompressionBomb/Unidentified/OSError/ValueError → 400 `Not a valid image.`
3. Reopen; `img.format` must be in `{'JPEG','PNG','WEBP'}` → else 400 `Only JPEG, PNG, or WebP images are supported.` (GIF explicitly not here.)
4. Dimensions ≤ 4096 either side → else 400 `Image dimensions exceed 4096px.`
5. `ImageOps.exif_transpose` (bake orientation), `thumbnail((1600,1600), LANCZOS)` if larger, convert RGBA (if alpha/transparency) else RGB, compute `dhash_hex` (64-bit difference hash, 16 hex chars — NOT PhotoDNA), save as **WebP quality 82**. Fresh encode = EXIF strip. Original never stored. Decode errors → 400 `Not a valid image.`
6. Back in view: `screen_image(processed.data)` (§4). `blocked` → audit `safesearch_block` + **422** `{"file":["This image was rejected by automated content screening."]}` and no asset row.
7. `get_matcher().match(phash)` — `NullMatcher` always None; truthy hit would audit `hash_match_hit` + 422 `This image cannot be uploaded.`
8. `MediaAsset(kind='image', width, height, phash, safesearch=verdict)`; `asset.file.save('image.webp', ..., save=False)` → path `media-assets/<uuid>/image.webp` (`media_asset_path` L1406; uuid is assigned at instantiation via `default=uuid.uuid4` so path is stable pre-save).

### 2.2 Video / GIF branch — `process_video(uploaded, is_gif)` (L262-337)
1. Size: video ≤ 30MB (`Video exceeds the 30MB limit.`), GIF ≤ 15MB.
2. `_source_path`: reuse Django temp file path if `TemporaryUploadedFile`, else spool to a NamedTemporaryFile (owned → unlinked in `finally`). Workdir `tempfile.mkdtemp(prefix='media-video-')` removed in `finally`.
3. `probe_media(src)` (ffprobe JSON, 30s timeout). Rejections (all 400): no video stream → `No video track found.`; container not in `{'mov','mp4','m4a','matroska','webm','gif'}` (ffprobe reports mp4/mov/m4a as `mov`) → `Only MP4, MOV, WebM, or GIF uploads are supported.`; duration None or > 60000ms → `Clips must be 60 seconds or shorter.`; `w*h > 1920*1080*1.2` → `Videos larger than 1080p are not supported yet — export at 1080p or lower.` These checks happen **before** any transcode/semaphore.
4. Acquire `_EncodeSlot` (non-blocking; `BoundedSemaphore(1)` per gunicorn worker; 2 workers → 2 concurrent encodes per instance). Exhausted → `MediaBusyError` → **429** `{"detail":"Media processing is busy — try again in a moment."}` with `Retry-After: 30`.
5. ffmpeg: `-vf scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2 -c:v libx264 -preset veryfast -crf 23 -threads 1 -movflags +faststart -fpsmax 30`; `-an` if GIF or no audio stream, else `-c:a aac -b:a 128k`. Timeout 240s → 400 `Processing timed out — try a shorter or smaller clip.`; binary missing (OSError) → 400 `Media processing is unavailable.`; non-zero rc → 400 `Could not process this media file.` (stderr tail logged at WARNING).
6. Re-probe output; if `duration_ms > 62000` (forged metadata) → 400 duration error.
7. Extract poster at `min(1.0, seconds/2)` and two sample frames at 1/3 and 2/3 (JPEG `-q:v 4`) — still inside the encode slot; phash computed from the poster.
8. Returns `ProcessedVideo(data, width, height, duration_ms, poster, sample_frames[2], phash)`.
9. View: screens poster + 2 frames via `screen_image`; **any** `blocked` → audit + 422 `This clip was rejected by automated content screening.`; hash matcher; stored `safesearch = {'status': 'ok' if all frames ok/skipped else 'error', 'frames': [...]}`; `MediaAsset(kind='video', is_gif, width, height, duration_ms, phash)`; files `video.mp4` and poster `poster.jpg` under `media-assets/<uuid>/`.

### 2.3 Audio branch — `process_audio` (L340-373)
Size ≤ 10MB; probe; video stream present → 400 `This looks like a video — upload it as a video joke.`; audio codec must be in `{'mp3','aac','alac','pcm_s16le','vorbis','opus','flac'}` → else 400 `Only MP3, M4A/AAC, or common audio formats are supported.`; duration ≤ 60s. Cover-art (`attached_pic`) streams are ignored by the probe so MP3s with ID3 art pass. Encode slot → `ffmpeg -vn -c:a aac -b:a 128k out.m4a`. No visual screen: `safesearch={'status':'not_applicable'}`. Stored as `audio.m4a`, no poster, no phash.

### 2.4 Shared tail — `_finalize_media_upload` (L1448-1477)
`asset.save()`; on DB exception, delete the just-written file (+poster) then re-raise (500). Then `_sweep_orphan_assets(user)` (delete this user's unattached assets older than 24h via `delete_with_files`), then `purge_lapsed_quarantine()` (§6), then audit `media_upload` (target_type `media_asset`), then 201 with `MediaAssetSerializer` payload: `{id, kind, url, poster_url, width, height, duration_ms, is_gif, created_at}` (URLs made absolute via `request.build_absolute_uri(field.url)`).

Spec vs code: spec §5 says response `{id, kind, url, poster_url, width, height, duration_ms}`; code also emits `is_gif` and `created_at`. Spec §5.2 originally said 100MB/25MB caps; amended and code uses 30MB/15MB/10MB.

## 3. Probing (ffprobe) — `jokes/media_probe.py`
`ffprobe -v error -print_format json -show_format -show_streams <path>`, `timeout=30`. Failures all map to `MediaValidationError` (timeout/OSError → `Could not read this media file.`; non-zero rc / bad JSON / no streams → `Not a valid media file.`). Picks the first `codec_type=='video'` stream **without** `disposition.attached_pic`, first audio stream; container = first token of `format_name`; duration from `format.duration` else stream duration, ms int. Lazy-imports `MediaValidationError` to avoid an import cycle (regression test `ImportCycleRegressionTests`).

## 4. SafeSearch screening — `jokes/media_screening.py`
- Off (`SAFESEARCH_ENABLED` false): `{'status':'skipped'}` — upload proceeds; human review queue is the gate.
- On: `vision.ImageAnnotatorClient().safe_search_detection(image=vision.Image(content=bytes))`. Client construction + call are inside `try/except Exception` → any thrown error (auth/ADC missing, PERMISSION_DENIED, quota, network) → `{'status':'error','detail':...}` and the upload **proceeds (fail-open)**; `response.error.message` non-empty → same. This is the "screening fail-open hotfix" (commit 77e995a per share_cards docstring).
- Verdict: `{adult, violence, racy, medical, spoof}` likelihood names + `status`. `blocked` iff `adult` or `violence` ≥ `LIKELY` (index ≥ 4 in `['UNKNOWN','VERY_UNLIKELY','UNLIKELY','POSSIBLE','LIKELY','VERY_LIKELY']`). `racy`/`medical`/`spoof` never block, only inform the reviewer (`JokeSubmissionAdmin.safesearch_flags` lists `POSSIBLE+` categories, descending into video `frames`).
- Note the module-level `from google.cloud import vision` at L39 is OUTSIDE the try: if the package is missing the upload 500s when enabled (package is pinned, so only a broken env).
- `HashMatcher`/`NullMatcher`/`get_matcher()` — dormant CSAM seam; no vendor wired.

## 5. Storage layout and serving
- Prod: GCS bucket (uniform bucket-level access, public read). Paths: `media-assets/<uuid>/{image.webp|video.mp4|audio.m4a|poster.jpg}`, `share-cards/joke-<pk>.png` (guessable, deliberately public OG), `avatars/…`, quarantine `quarantine/<uuid>/<token_urlsafe(16)>/<basename>`. `file_overwrite=True` means re-saving `share-cards/joke-<pk>.png` reuses the same URL (crawler caches may keep the old bytes).
- Local: `FileSystemStorage` under `./media/` (repo has `media/media-assets/*` and `media/share-cards/joke-*.png` from prior local runs). **No `static(settings.MEDIA_URL, document_root=...)` or `django.views.static.serve` route exists anywhere** (`JokesForProject/urls.py`, `jokes/urls.py`) and WhiteNoise serves only `STATIC_ROOT`. Therefore locally the API returns `http://localhost:8000/media/media-assets/<uuid>/image.webp` URLs that 404 — files are written but not served. Frontend has an object-URL mock branch for previews (spec §3.2).
- Serializer URL exposure is guarded by paywall lock (dims-only), removed-joke guard (`[]`), and quarantine guard in draft list + data export (`url: None`).

## 6. Quarantine / takedown / release / purge lifecycle
Model methods (`models.py` L1438-1517):
- `_move_stored_files(path_for, extra_update_fields)`: for `file` and `poster`: read old bytes via `default_storage.open`, delete pre-existing target, `default_storage.save(new_name, ContentFile)`, set `field_file.name`; ONE `self.save(update_fields=moved+extra)`; THEN delete old objects. Crash-safe (worst case duplicate at new path).
- `quarantine()`: idempotent (no-op if `quarantined_at`), stamps `quarantined_at=now`, moves to `quarantine/<pk>/<secrets.token_urlsafe(16)>/<basename>` (random segment prevents prefix-derivation from the previously public URL).
- `release()`: no-op unless quarantined; clears stamp; moves back to `media-assets/<pk>/<basename>`.
- `purge()` → `delete_with_files()`: delete file+poster from storage, then row (links CASCADE).

Call sites:
- **Takedown** `ContentReportAdmin.take_down_joke` (`admin.py` L421-540): flips `is_removed=True, removed_at=now` on not-yet-removed jokes; **blanks share card** (delete stored PNG, `update(share_image='')`) per joke with isolation + admin warning on failure; notifies creator `joke_removed` with top reason + 14-day appeal deadline; resolves reports; for each asset linked to the removed jokes, skips if `still_shared` with a live joke outside the set, else `quarantine()` (per-asset isolation, warning on failure); audit `media_quarantined`. **JokeMedia links are KEPT** (reversibility). Spec §7.2 said `take_down_joke` calls `delete_with_files()` and audits `media_takedown` — code diverged (appeals wave): quarantine instead, audit action `media_quarantined`.
- **Direct `is_removed` flip via `Joke.save()`** (`models.py` L191-244): a live→removed transition deletes `share_image`; removed jokes never (re)generate a card (`regenerate=False`). Does NOT quarantine media (only the admin action does).
- **Restore** `JokeAdmin.restore_jokes` (L117-165): `release()` all quarantined assets linked to selected jokes (warn on failure), `update(is_removed=False, removed_at=None)`, `regenerate_share_image()` per restored joke (isolated, warns).
- **Appeal uphold** `AppealAdmin.uphold_appeals` (L621-693): for a joke appeal, `purge()` each quarantined asset unless `still_shared` with a live joke or a sibling joke sharing the asset has its own pending appeal; status `upheld`; audit `appeal_upheld`; notify.
- **Appeal reverse** `reverse_appeals` (L695-760): `release()` assets, `Joke.all_objects...update(is_removed=False, removed_at=None)`, `regenerate_share_image()` (isolated), notify, status `reversed`, audit `appeal_reversed`. Rejection appeals → submission back to `draft`.
- **Lazy purge** `purge_lapsed_quarantine()` (`quarantine.py`): candidates `quarantined_at < now-14d`; skip if any linked joke has a `pending` appeal; skip if any linked joke is `is_removed=False` (live-joke guard); else `purge()`; one audit `media_purged` per batch. Triggered from `_finalize_media_upload` (every upload) and `AppealCreateView.create` (`views.py` L2333). No cron.
- **Draft delete** (`JokeDraftDetailView.perform_destroy` L1764-1771): assets referenced by no other submission/joke → `delete_with_files()`.
- **Account delete** (L2445-2482): `delete_with_files()` all owned assets (incl. quarantined), avatar delete, then media-format jokes (formats whose rules require `media`) with no media rows & not removed → `update(is_removed=True, removed_at=now)`; then user cascade.
- **Orphan sweep** on each upload (24h, unattached).

## 7. Share cards — `jokes/share_cards.py`
- `generate_share_card_png(joke)`: tries `media_share_card_png` first; else text card (`get_template_for_joke` by primary tone slug → `dad-jokes`/`dark`/`puns` templates else `base_card.svg`; badge = `'Audio'` if `format.slug=='audio'` else tone name else `'Joke'`). cairosvg `svg2png` 1200x630.
- `media_share_card_png`: primary asset = `joke.media.first()` (position 0). `image` → `asset.file` bytes; `video` → `asset.poster` bytes (never the mp4; test asserts `asset.file` unread); `audio`/no media/no poster → None (text card). Raster downscaled with Pillow to ≤1200px wide JPEG q82 (RGB), embedded as base64 `data:image/jpeg` in `media_card.svg` (`preserveAspectRatio="xMidYMid slice"`, caption = `joke.text` wordwrapped 40 chars, max 3 lines, brand stripe, badge `'GIF' | '▶ Video' | 'Photo'`). **Fail-open**: any exception → log warning → None → text card, so a corrupt raster never 500s `Joke.save()`.
- Trigger points: `Joke.save()` on create, on `text` change, or when `share_image` is blank (and not removed) → `_generate_share_image()` then `Joke.objects.filter(pk).update(share_image=name)` (uses the FILTERED manager — for a removed joke the update would match 0 rows, hence the removed guard). `regenerate_share_image()` public wrapper (no-op if removed) called by `approve_and_publish` after copying `JokeMedia` (ordering trap: the create-time card had no media yet), `restore_jokes`, `reverse_appeals`, and `backfill_share_cards --apply` (dry-run default; `--only-media`, `--limit`; only `Joke.objects` i.e. live jokes with `share_image=''`).
- Template filter `multiply` comes from local `jokes/templatetags/mathfilters.py`; `wordwrap`, `slice`, `add` are Django built-ins.
- Text card caption for media formats = `joke.text` = the setup teaser (backfilled from setup at submission; `serializers.py` L957-965), so the card never contains a punchline (media formats forbid `punchline`).
- Local dev: cairosvg needs libcairo; if missing, importing `jokes.share_cards` inside `Joke.save()` raises ImportError → any Joke create/text-edit 500s (CI installs the libs; Dockerfile too).

## 8. OG share page — `GET /jokes/<pk>/share/` (`views.py` L1352-1428)
- `@require_GET`; joke via `Joke.objects` (default manager hides `is_removed=True`) → removed/missing → 404.
- Tier gate: if `joke.content_tier not in allowed_tiers(request)` (anon/minor for tier_2; tier_3 always) → 200 `share_redirect.html`: only `<meta http-equiv="refresh" 0;url=<FRONTEND_URL>/jokes/<id>>`, `robots noindex`, JS `location.replace`, no OG image/description/JSON-LD/text.
- Otherwise `share.html`: meta-refresh + JS redirect to `FRONTEND_URL/jokes/<id>`, `<link rel=canonical>` → frontend URL, OG (`og:title`, `og:description`, `og:image` = absolute `share_image.url` with 1200x630 dims, `og:type=article`, `og:url` frontend, site_name), Twitter `summary_large_image`, JSON-LD `CreativeWork` (`name/headline` = title, `url` frontend, `author` Organization "JokesFor", `image` if card) serialized with `<`,`>`,`&` escaped to `<` etc. Title = `Truncator(setup or text).chars(60)`, description `.chars(160)` — **never the punchline**. Body shows `{{ joke.text }}` (for two-part jokes `text` contains "setup punchline" — the visible HTML body for a two-part text joke does include the punchline, only meta/JSON-LD are teaser-only; for media formats `text` == setup so no leak). Human vs bot distinction is purely "browsers honor refresh/JS; scrapers don't" — no User-Agent sniffing.
- Media locking does NOT apply to the share page/card: the card is public OG by design (spec decision), showing the image derivative / video poster.

## 9. Paywall media locking (`serializers.py` L254-317, `paywall.py`)
- `paywall_state(request)` computed once per request in views that inject `ctx['paywall_state']` (JokeViewSet list/retrieve/random/trending, favorites, saved, mystery box, recently viewed, packs — coverage tests in `PaywallContextCoverageTests`). Free authed: `used = COUNT(DISTINCT joke_id)` in `JokeView` today (UTC), cap from `entitlements.get_limit(user,'free_joke_reads_per_day',10)`; paid → unlimited; anon → signed cookie `jf_anon_reads` (10/day, midnight UTC, soft wall).
- `is_locked = state.over and joke.id not in consumed_ids`.
- Locked: `punchline=None`, `lines=None`, `text=None` for `TEXT_ONLY_FORMATS` (rules with `required==['text']`: oneliner/story/observ), `setup` kept, and `media` reduced to `[{kind,width,height}]` — **no url/poster_url/duration/is_gif**. Unlocked: `[{kind,url,poster_url,width,height,duration_ms,is_gif}]` in position order.
- `JokeListSerializer` (creator public profile) ALWAYS dims-only (no paywall context there).
- `JokeViewSet.retrieve` does not log a `JokeView` when `is_locked` (no payoff consumed) (`views.py` L184-187); anon unlocked GET → `record_anon_read` cookie update.
- `share_image_url` is NOT stripped by the paywall (public OG) but is `None` for removed jokes.

## 10. Format contract (`submission_rules.py`)
`image`: required `setup`+`media`, forbidden `punchline`/`lines`, media kind=image, 1–6. `video`: kind=video (GIF-sourced included via `is_gif` flag on kind `video`), exactly 1, `max_duration_ms=60000`. `audio`: kind=audio, 1, ≤60s. Attach via `media_asset_ids` on draft create/PATCH (`JokeSubmissionCreateSerializer.validate` L904-936: duplicates → 400, must be owned by the requester else `One or more media assets were not found.`); `_sync_media` rewrites `JokeSubmissionMedia` positions atomically. PATCH skips per-format validation (autosave) — enforced at `JokeDraftSubmitView` and on create. `JokeSubmissionListSerializer.get_media` emits dims-only (`url: None`) for quarantined assets.

## 11. Telemetry hooks
- Audit (`audit.services.record_audit` → `AuditLog` row + `jokesfor.audit` log line): `media_upload`, `safesearch_block` (outcome `blocked`), `hash_match_hit`, `media_quarantined`, `media_purged`, `appeal_upheld`, `appeal_reversed`. Spec's `media_takedown` action does not exist in code.
- Watch telemetry: `POST /api/v1/telemetry/events` with `{"joke", "type":"watch", "watch_ms", "watch_pct", "source"}` → `JokeWatch` rows, append-only; `watch_ms` clamped to `[0, WATCH_MAX_MS]`, below `WATCH_MIN_MS` dropped; `watch_pct` clamped 0–100 or None; `source[:16]`. Migration `0033_jokewatch`.
- No `jokesfor.metrics` log-metric is emitted for uploads/screening (only `content_tier_decision` in `serving.py`). ffmpeg/ffprobe failures log at WARNING with stderr tail.
- Admin visibility: `JokeSubmissionAdmin.media_preview` (poster with ▶ badge / audio link with seconds / image thumbnail) and `safesearch_flags`.

## 12. What breaks locally without GCS / Vision / binaries
| Missing | Effect |
|---|---|
| `GS_BUCKET_NAME` unset | Files go to `./media/`; all `url`/`poster_url`/`share_image_url` values point at `http://<host>/media/...` which **404** (no media-serving route). Storage-level lifecycle (quarantine move, purge) works via `FileSystemStorage`. |
| `SAFESEARCH_ENABLED` unset | `screen_image` → `skipped`; uploads never blocked; video verdict `status:'ok'` (skipped counts as ok). |
| `SAFESEARCH_ENABLED=true` but no ADC creds | Client raises → caught → `status:'error'`, upload proceeds (fail-open), warning logged. |
| `ffmpeg`/`ffprobe` not on PATH | Video/GIF/audio uploads → 400 `Could not read this media file.` (probe OSError). Image uploads unaffected (Pillow only). |
| libcairo/pango missing | `cairosvg` import fails inside `Joke.save()` → every Joke create / text change / restore 500s. |
| Neon unreachable | Standard DB failure; upload cleanup path deletes the stored file on `asset.save()` failure. |

## 13. Divergences: docs vs code
- Spec §7.2 (`take_down_joke` → `delete_with_files`, audit `media_takedown`) superseded by appeals wave: quarantine + `media_quarantined`.
- Spec §5.2 caps (100MB/25MB) amended to 30MB/15MB; ≤1080p input gate added; 2 encodes/instance.
- Spec §5 response shape lacks `is_gif`, `created_at` which code returns.
- `.planning/codebase/*.md` not relied on.

## 14. Notable edge cases / risks found in code
1. `kind=audio` with a `.gif` filename → routed to `process_audio` → 400 "This looks like a video" (is_gif override only applies to image/video kinds). Minor.
2. Share page body renders `{{ joke.text }}` which, for two-part text jokes, equals "setup punchline" → the punchline is present in the HTML body (not in meta/JSON-LD). Scrapers that read body text (rare) could spoil; for media formats there is no punchline.
3. `Joke.save()` persists `share_image` through `Joke.objects.filter(pk).update(...)` (filtered manager) — guarded by `is_removed` check; `regenerate_share_image` same.
4. `_move_stored_files` reads whole file into memory (`fh.read()`) — a 30MB mp4 + poster per quarantined asset in-request; fine at current caps.
5. Video screening runs 3 Vision calls per upload sequentially inside the request (after the encode slot is released).
6. `purge_lapsed_quarantine` runs on every upload (query over all quarantined assets) — cheap while quarantine volume is small.
7. `MediaAsset.quarantine()` inside `take_down_joke` is not wrapped in a DB transaction with the `is_removed` flip; partial failures are surfaced as admin warnings, and serializers gate on `is_removed`/`quarantined_at` defensively.
8. Share-card path `share-cards/joke-<pk>.png` is guessable and public; takedown blanks it, but GCS `file_overwrite=True` + CDN/crawler caches may retain the old bytes until re-fetch.
9. Encode semaphore is per-process; with `--threads 4` a single worker allows only 1 encode at a time; the other 3 threads keep serving.
10. `screen_image` imports `google.cloud.vision` outside the try when enabled — ImportError would 500 (dependency pinned).
