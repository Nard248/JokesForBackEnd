# Media Jokes (Image / Video / Audio / GIF) — Requirements & Design — 2026-07-20

## 1. Goal

Extend JokesFor beyond text: jokes whose punchline is an image (single or
multi-panel carousel), a video clip, an audio clip, or an animated GIF. Media
jokes are first-class `Joke` rows — same taxonomy (tones/categories, themes,
age rating, language), same creator attribution, same moderation, reactions,
saves, insights, and paywall as text jokes. New `Format` registry entries:
`image`, `video`, `audio`.

## 2. Product decisions (locked with owner, 2026-07-20)

1. **Anatomy: setup text + media punchline.** Every media joke has required
   `setup` text (the teaser) and the media as the blurred, tap-to-reveal
   payoff — the platform's signature curiosity-gap mechanic. This is what
   lets FTS search, share cards, the archive strip, and clipboard share work
   unmodified via the existing setup→`text` backfill.
2. **Phasing: image wave first, then video/audio/GIF wave.** One design doc
   (this one); wave 1 proves the upload→moderation→rendering→paywall
   pipeline, wave 2 reuses it.
3. **Video: constrained self-host on GCS** (no external vendor). With
   in-request ffmpeg normalization (§5.2) so phone-native formats are
   accepted.
4. **Moderation: human pre-publish review + Google Vision SafeSearch
   pre-screen**, plus baseline hardening (EXIF strip, MIME/size validation,
   storage deletion on takedown). CSAM hash matching: pipeline built now,
   vendor activation gated on owner onboarding (§7.3).
5. **Full scope directive:** GIF, audio, multi-image, transcoding, watch
   telemetry, media in daily/JOTD, CSAM pipeline, and the anon paywall are
   IN scope (owner instruction 2026-07-20), distributed across the two waves.

## 3. Requirements

### 3.1 Functional

- Creators upload media in the editor, attach it to a draft, preview it, and
  submit through the existing draft→pending→published/rejected state machine.
- Image jokes: 1–6 ordered images (carousel when >1). Video: single clip
  ≤60s. Audio: single clip ≤60s. GIF: uploaded as `.gif`, delivered as a
  looping muted video.
- Readers see setup text + blurred media; tap reveals. Reveal counts as the
  payoff (creator insights) and consumes a free-tier daily read.
- Locked jokes (free tier over cap, or anon over cap) serve setup + media
  dimensions ONLY — media URLs are withheld server-side.
- Media jokes are eligible for every serving surface: explore, search,
  trending, packs, mystery box, collections, saves, creator profiles,
  **and daily joke / JOTD** (bespoke daily renderers are consolidated onto
  the shared renderer as part of wave 1/2).
- Anonymous readers get the same 10 distinct reveals/day, enforced via a
  signed cookie ledger; over-cap anon sees a "Sign up free" CTA (conversion
  wall), not the Supporter CTA.
- Reporting, takedown, blocks, tier gating (COPPA), data export, and account
  deletion all cover media jokes; takedown and account deletion delete the
  underlying storage objects.

### 3.2 Non-functional

- Everything request-triggered: single Cloud Run app, NO Celery/cron/workers.
  Orphan cleanup, transcoding, screening — all inside request lifecycles.
- Upload processing fits the request ceiling. Image: trivially. Video:
  normalize ≤60s/720p clips in-request; gunicorn `--timeout` raised to 300
  for headroom (gthread heartbeats make this safe); Cloud Run request
  timeout must be ≥300s (deploy-console check, owner-visible in rollout).
- Uploads have a dedicated throttle scope (default 30/hour/user) and strict
  server-side size caps (no cap exists anywhere today — DoS gap).
- No horizontal-scroll/CLS regressions: media cards reserve height via
  backend-supplied dimensions + CSS `aspect-ratio` before load
  (Docs/RESPONSIVE.md conventions apply; `prefers-reduced-motion` respected
  for autoplaying GIF-videos).
- Local dev and PR previews work fully mocked (object-URL mock branch in the
  create adapter); tests run against local Postgres with `--keepdb`.

### 3.3 Compliance

- EXIF stripped from every image (side effect of mandatory re-encode).
- SafeSearch pre-screen at upload for images and for video/GIF poster +
  sampled frames; hard-block at `LIKELY`+ adult/violence, flags surfaced to
  the human reviewer. Audio has no automated screen (human review only) —
  documented residual risk.
- Perceptual hash (PDQ or pHash) computed and stored for every visual asset
  at upload; pluggable matcher interface ships dormant until a CSAM vendor
  (PhotoDNA / NCMEC / Thorn Safer) is onboarded. **Owner action: file the
  vendor application — tracked as a launch-gating fast-follow for open
  registration, not for the demo.**
- ToS revision: current terms declare the platform text-only and forbid
  media uploads (`src/content/legal/terms.ts`, Acceptable Use). Amended text
  ships WITH wave 1; owner sign-off on wording is a deploy gate.
- Pre-moderation assets live at unguessable UUID URLs in the existing public
  bucket (Cloud Run SA cannot V4-sign; signed URLs deliberately avoided
  repo-wide). Accepted trade-off, same exposure class as `share_image_url`;
  revisit if signing infra lands.

## 4. Data model (backend, `jokes` app)

> A separate `media` Django app is NOT used — the repo root already has a
> `media/` directory (MEDIA_ROOT) and the name would collide.

### 4.1 `MediaAsset`

| field | notes |
|---|---|
| `id` | UUIDv4 primary key (unguessable URLs derive from it) |
| `owner` | FK User, CASCADE; used for permission + orphan sweep + account-delete |
| `kind` | `image` \| `video` \| `audio` |
| `file` | FileField `upload_to='media-assets/<uuid>/...'` — the display derivative (re-encoded image / normalized MP4 / audio) |
| `poster` | ImageField, video only (extracted frame; also the SafeSearch subject) |
| `width`, `height` | ints; null for audio |
| `duration_ms` | int, null for images |
| `is_gif` | bool — GIF-sourced video (loop + mute + autoplay presentation) |
| `safesearch` | JSON verdict (per-frame list for video) |
| `phash` | perceptual hash hex; null until computed (audio: null) |
| `created_at` | |

Assets are owned by the **user**, not the draft — uploads may precede draft
creation (solves the editor's draft-id chicken-and-egg; drafts today are
created on first text keystroke).

### 4.2 `JokeMedia` / `JokeSubmissionMedia` (ordered through-models)

`(submission|joke) FK, asset FK (PROTECT), position int` — unique on
(parent, position). Images: 1–6 rows. Video/audio: exactly 1 (enforced by
FORMAT_RULES constraint). `approve_and_publish` copies the submission's
rows to the Joke (extending the existing explicit field-copy — the
silently-dropping-fields trap).

### 4.3 Lifecycle & deletion (request-triggered, no cron)

File deletion happens in exactly one helper (`MediaAsset.delete_with_files()`),
called from: draft DELETE (assets referenced only by that draft), asset
replacement in the editor, admin `take_down_joke` (extended — today it only
flips `is_removed`), account deletion (extended — today it only deletes
avatars), and the **lazy orphan sweep**: each new upload deletes that same
user's unattached assets older than 24h. Data export includes media URLs.

## 5. Upload pipeline

`POST /api/v1/media/uploads` — multipart (DRF default parsers already
active), authenticated, scoped throttle `media-upload: 30/hour`. Body:
`file`, `kind`. Response: `{id, kind, url, poster_url, width, height,
duration_ms}`.

### 5.1 Image (wave 1)

JPEG/PNG/WebP · ≤10MB · ≤4096px. Pillow verify + re-open → re-encode to ONE
display derivative (max 1600px longest edge, quality ~82) — strips EXIF by
construction; original is NOT retained → SafeSearch (in-request; hard-block
`LIKELY`+ adult/violence with a clear 422; store verdict) → pHash → GCS.
Pillow gets pinned in requirements.txt (today it's only a transitive dep of
cairosvg — latent breakage).

### 5.2 Video / audio / GIF (wave 2)

- Accepted containers: MP4/MOV/WebM (video), MP3/M4A/AAC (audio), GIF.
- Caps: ≤60s duration (ffprobe-verified), ≤100MB upload (video), ≤25MB
  (GIF), ≤10MB (audio).
- ffprobe validates; ffmpeg **normalizes in-request** to H.264/AAC
  progressive MP4, 720p max, `+faststart` (accepts iPhone HEVC `.mov`,
  Android WebM). GIF → silent looping MP4 (`is_gif=true`).
- Poster frame + 2 sampled frames extracted; SafeSearch runs on all three.
- Audio: ffprobe validate + re-mux to AAC/M4A; no visual screen (human
  review only).
- ffmpeg/ffprobe join the Docker runtime apt list (same pattern as the
  cairo libs); gunicorn `--timeout 300`.
- **Why no HLS:** for ≤60s/≤720p clips, progressive MP4 served from GCS
  with range requests (seek support) is strictly better than HLS —
  adaptive-bitrate ladders need multiple renditions (minutes of transcode,
  breaking the request ceiling) and buy nothing at this clip length.
  Transcoding = yes; HLS = replaced by progressive MP4, by design.
- **Measured checkpoint at wave-2 start:** upload+normalize wall-time for a
  60s/100MB worst case on prod-shaped CPU; caps lowered if it crowds the
  300s ceiling.

## 6. Format contract

### 6.1 FORMAT_RULES additions (jokes/submission_rules.py)

| slug | required | forbidden | constraints |
|---|---|---|---|
| `image` | `setup`, `media` | `punchline`, `lines` | media kind=image, 1–6 items |
| `video` | `setup`, `media` | `punchline`, `lines` | kind=video (incl. GIF-sourced), 1 item, ≤60s |
| `audio` | `setup`, `media` | `punchline`, `lines` | kind=audio, 1 item, ≤60s |

`media` joins the rules vocabulary; `validate_per_format` checks attached
`JokeSubmissionMedia` rows (count + kind). The existing text backfill sets
`text = setup`, so FTS search, share cards (which render `joke.text` — the
teaser, never the payoff → no paywall leak), and the archive strip work
unchanged. `TEXT_ONLY_FORMATS` auto-derivation (`required == ['text']`)
does not match — no accidental strip. New `Format` rows seeded by data
migration following the 0021 pattern.

### 6.2 Locking contract (explicit branch in `JokeSerializer.to_representation`)

- Unlocked: `media: [{kind, url, poster_url, width, height, duration_ms,
  is_gif}]` in position order.
- Locked (`is_locked=true`): `setup`/`text` teaser kept; `media` reduced to
  `[{kind, width, height}]` — **no URLs**. Client renders an aspect-ratio
  locked placeholder + the existing UnlockCta (or the anon sign-up CTA).
- `JokeListSerializer` (creator public profile) currently has NO stripping —
  it must emit only teaser + dimensions for media (never URLs) to avoid a
  paywall bypass.
- Consumption/reveal semantics are copied from the `setup` format verbatim:
  media formats join the reveal-gated set; reveal telemetry sets
  `revealed_punchline`; `payoff_rate` in creator insights works unchanged.
  The known reveal-ingest lock-check gap is not widened (no auto-fired
  payoffs).

## 7. Moderation & compliance

### 7.1 Review queue

`JokeSubmissionAdmin`: inline thumbnail/player preview + SafeSearch verdict
column + pHash-match flag column. `approve_and_publish` copies media rows;
tier derivation unchanged (age-rating based) but SafeSearch flags are
visible to the reviewer at decision time.

### 7.2 Takedown / reports

`ContentReport` reasons already fit; `take_down_joke` additionally calls
`delete_with_files()` on the joke's assets. Audit actions added:
`media_upload`, `safesearch_block`, `hash_match_hit`, `media_takedown`.

### 7.3 CSAM hash matching (pipeline now, vendor later)

At upload: compute + store pHash/PDQ. A `HashMatcher` interface with a
`NullMatcher` default ships in wave 1; when vendor credentials exist
(PhotoDNA cloud / NCMEC list / Thorn Safer — **owner files the
application**), the real matcher slots in with zero schema change: match →
block upload + audit `hash_match_hit` + surface for mandatory reporting.
Open public registration is gated on this activation; the demo is not.

### 7.4 ToS

Amended Acceptable Use section (drafted during wave 1, owner sign-off
gates deploy): permits user media uploads, states moderation/screening,
retains the ban on unlawful/infringing content.

## 8. Paywall — anonymous readers (wave 1)

- `paywall_state(request)` extended: for anon, the ledger is a signed
  cookie (`jf_anon_reads`, Django signing/HMAC): `{date, count,
  joke_ids[≤10]}`, midnight-UTC reset. Over cap → `is_locked` on
  non-consumed jokes exactly like free users; media URLs withheld.
- Consumption trigger for anon in-feed reveals (anon can't use telemetry —
  consent-gated): new lightweight `POST /api/v1/jokes/{id}/reveal/`
  (AllowAny, throttled) that validates the joke is servable, updates the
  cookie, and returns the new state; the frontend calls it from the reveal
  handler when unauthenticated. Detail-page GET also consumes (cookie
  update on unlocked delivery).
- Cookie clearing evades the wall — accepted (industry-standard soft wall);
  the goal is conversion, not enforcement. Anon locked CTA routes to
  `/register` ("Sign up free"), not billing.
- Free/paid AUTH behavior unchanged.

## 9. Telemetry & insights

- Wave 1: impressions/dwell/reveal work as-is (element-ref hooks are
  format-agnostic).
- Wave 2: new `watch` telemetry event `{joke_id, watch_ms, watch_pct,
  source}` — fired on pause/end/unmount, NOT continuously; new append-only
  `JokeWatch` model (clamped like dwell). `JokeDwell.scroll_pct` is NOT
  overloaded (would corrupt text completion_rate semantics). Creator
  insights: video/audio jokes additionally show avg watch time +
  completion (watch_pct≥90); `payoff_rate` remains reveal-based across all
  formats for comparability.

## 10. Frontend

### 10.1 Rendering

- `FlowJokeFormat` union grows: `'image' | 'video' | 'audio'` — TS forces
  exhaustion of SKIN / FORMAT_LABEL / FLOW_FORMAT_TO_BACKEND_SLUG +
  `formatSlugToFlow`, `tagToneFor`, and `groupOf()`.
- **Unknown-format guard:** unrecognized slugs skip-render (today they
  silently render as garbled one-liners) — makes this and every future
  format deploy-order-safe.
- `JokeRenderer` media branches: setup text + `punch-blur`-wrapped media in
  an `aspect-ratio` box (dimensions from backend → no masonry CLS).
  Image: tap unblurs; carousel (dots + swipe) for multi-image, blur covers
  the whole carousel. Video: tap unblurs to poster + native controls
  (`playsinline preload="metadata"`). GIF-video: reveal → muted looping
  autoplay (suppressed under `prefers-reduced-motion` → tap-to-play).
  Audio: reveal → native `<audio>` player card.
- `LockedBody` media variant: dimensioned placeholder + CTA (Supporter for
  free users, Sign-up for anon).
- Adapters threaded: `jokeToFlowData`, `savedJokeToFlowData` (both copies),
  `trendingToFlowData`; `Joke` TS type gains `media[]`.

### 10.2 Bespoke-surface consolidation (owner-directed in-scope)

`JokeDetailPage` body, FlowCanvas `JotdBody`, and `DailyJokePage` hero are
consolidated onto `JokeRenderer` (the map found four duplicated reveal
implementations — media support everywhere makes consolidation cheaper
than triplicating branches). `SevenDayArchive` strip falls back to
thumbnail-or-text. Daily/JOTD selection does NOT exclude media formats.
LandingPage hero stays static text (marketing copy, untouched).

### 10.3 Create pipeline

- `ImageEditor` (wave 1), `VideoEditor`/`AudioEditor` (wave 2) in the lazy
  `EDITOR_BY_FORMAT` registry: setup textarea + picker/dropzone + upload
  progress (axios `onUploadProgress`) + preview + replace/remove; carousel
  ordering UI for images.
- Upload = dedicated FormData mutation (per-request Content-Type override —
  the axios instance hardcodes JSON; CSRF/Bearer interceptors already
  cover multipart POSTs). Returned `media_asset_id`s ride the normal 800ms
  JSON autosave — **file bytes never enter the autosave loop**.
- `isMeaningful` extended to count attached media, and the media editors
  trigger draft creation before opening the picker (draft-id ordering).
- Editor `changeFormat` gets a `media` format group so switching formats
  correctly detaches (and orphan-sweeps) assets.
- Mock branch: object-URL uploads so local dev / PR previews (mocked create
  seam) remain fully usable.
- Picker/chrome lists extended: FALLBACK_FORMATS, FORMAT_ICON /
  FORMAT_EXAMPLE, ChangeFormatModal FORMAT_OPTIONS, FORMAT_SLUGS (the
  arrays TS can't force — checklist in the plan).

## 11. Waves & rollout order

**Wave 1 — images + platform foundations:** MediaAsset/JokeMedia models +
migrations; image upload pipeline (Pillow, SafeSearch, pHash, throttle,
caps); format registry `image`; locking contract incl. JokeListSerializer
fix; deletion lifecycle (takedown/account-delete/orphan sweep); admin
review preview; anon paywall (cookie ledger + reveal endpoint + CTAs);
frontend: unknown-format guard, image rendering (single+carousel),
ImageEditor, adapter threading, bespoke-surface consolidation (detail +
daily/JOTD image support); ToS amendment; audit actions; tests.

**Wave 2 — video / audio / GIF + watch telemetry:** Docker ffmpeg/ffprobe +
gunicorn timeout; normalization pipeline (MP4/MOV/WebM/HEVC→MP4 720p,
GIF→looping MP4, audio re-mux); poster + sampled-frame SafeSearch; formats
`video`/`audio`; VideoEditor/AudioEditor; video/audio/GIF rendering; watch
telemetry + insights additions; wave-2 measured upload checkpoint.

**Parallel owner-action track:** CSAM vendor application; ToS wording
sign-off; Cloud Run request-timeout ≥300s verification (console).

**Deploy ordering (each wave):** frontend (guard + rendering) → backend
(migrations + formats + endpoints). The unknown-format guard makes
ordering violations degrade to hidden cards, not garbled ones.

## 12. Testing

- Backend (local Postgres, `--keepdb`, no pytest): FORMAT_RULES validation
  per media format; upload caps/MIME/dimension rejections; EXIF-strip
  verification (re-encode drops metadata); SafeSearch block/flag paths
  (mocked client); pHash computed + NullMatcher wiring; locking strip
  contract (both serializers, dimensions-only when locked); anon cookie
  ledger (signed, reset boundary via freezegun, tamper rejection);
  reveal-endpoint consumption; publish media-copy; takedown/account-delete
  file deletion; orphan sweep; data export inclusion. Wave 2: ffprobe/
  ffmpeg validation + normalization (small fixture clips), watch-event
  ingest clamps, insights aggregates.
- Frontend (vitest): editor upload flow (mocked), carousel ordering,
  renderer branches locked/unlocked per format, unknown-format guard,
  adapter threading, anon CTA routing, reduced-motion GIF behavior.

## 13. Risks

| risk | mitigation |
|---|---|
| Public bucket pre-moderation exposure | UUID-unguessable paths; documented accepted trade-off; deletion lifecycle wired |
| In-request video normalize vs. request ceiling | 60s/720p caps, gunicorn 300s, Cloud Run ≥300s, wave-2 measured checkpoint with cap fallback |
| Transcode CPU starving serving workers | ffmpeg as subprocess (no GIL hold), `-threads 1`, upload throttle 30/h; acceptable at current scale, revisit with traffic |
| Paywall leak via list/detail serializers | Locking contract covers BOTH serializers; tests pin URLs-absent-when-locked |
| Old FE bundles meeting new formats | Unknown-format skip-render guard ships before backend rows |
| Orphaned storage (no cron) | Single deletion helper + lazy per-user sweep on upload |
| Audio unscreenable by SafeSearch | Human review only; documented residual risk |
| GCS egress cost if a clip spreads | Accepted at demo scale; CDN noted as future infra |

## 14. Out of scope (v1, both waves)

Live streaming; audio transcription/speech screening; image editing tools
(crop/filters); >6 images per joke; multiple videos per joke; HLS/adaptive
bitrate (superseded by progressive MP4 — see §5.2); server-side share-card
compositing of media thumbnails (share cards stay setup-text-based); CDN in
front of GCS; paid-tier media perks.
