# Media Jokes Wave 2 — Frontend Implementation Plan (video / audio / GIF + watch telemetry)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Video, audio, and GIF jokes render, upload, and report watch telemetry across the JokesFor React app, per spec §5.2/§9/§10 — extending the wave-1 machinery (union, renderer, editors, adapters) that was built to grow.

**Architecture:** Every wave-1 seam extends by entry: the union grows to 9, TypeScript forces the keyed maps, `EDITOR_BY_FORMAT` gains two lazy editors that reuse the ImageEditor upload pattern with `kind` parameterized, the renderer gains `video`/`audio` branches behind the same blur-reveal, and a `watch` telemetry type mirrors `dwell`'s client plumbing fired from native media-element events.

**Tech Stack:** unchanged (React 19 + TS, vitest, inline styles, useBreakpoint).

## Global Constraints

- Repo `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend`. Tests `npm test -- --run`; build `npm run build`. Wave-1 suite (664) stays green.
- Commit messages plain, NO footers/emoji.
- Backend contract (wave-2 backend plan): upload accepts `kind` ∈ {image, video, audio} (GIF under image or video → returns `kind:'video', is_gif:true`); video assets carry `poster_url/width/height/duration_ms/is_gif`; audio carry `duration_ms` only; formats `video`/`audio` = setup + exactly 1 media, ≤60s; telemetry gains `watch` events `{type:'watch', joke_id, watch_ms, watch_pct?, source}` (≥500ms, clamps server-side); insights stats gain `avg_watch_seconds`/`watch_completion_rate` on media jokes.
- Locked media jokes: backend serves `{kind,width,height}` only — the wave-1 `LockedBody` placeholder covers video (has dims); audio locked/unrevealed states need a FIXED-HEIGHT placeholder variant (no dims exist).
- Reveal mechanic: video/audio join the reveal-gated set; reveal shows the player (poster + native controls / audio bar) — playback itself is a second, user-initiated act via native controls. GIF-videos (`is_gif`) instead AUTOPLAY muted+looped on reveal, EXCEPT under `prefers-reduced-motion` (then poster + tap-to-play). `playsinline preload="metadata"` on all video elements.
- Watch telemetry fires from native events: accumulate played time; send ONE watch event per (joke, session) on `pause`, `ended`, and component unmount — latest totals win server-side (append-only); `watch_pct = round(currentTime_max / duration * 100)`. Same gating as all telemetry (authed + consent, via the existing client seam — do NOT bypass it).
- Deploy order: this FE wave deploys BEFORE the wave-2 backend push (the wave-1 unknown-format guard already hides video/audio jokes from old bundles; this wave's code must degrade gracefully against the CURRENT prod backend — no video/audio formats served, upload kind param ignored-safe).
- New-format checklist (arrays TS can't force): `FORMAT_SLUGS`, `FALLBACK_FORMATS`, `FORMAT_OPTIONS` (ChangeFormatModal), `FORMAT_ICON`/`FORMAT_EXAMPLE`, `EDITOR_BY_FORMAT`, `FormatIconComponent` switch, legacy `SubmitJokePage` label map.

---

### Task 1: Union + maps + editors' registry chrome for `video` / `audio`

**Files:** `src/components/JokeRenderer.tsx` (union + 5 maps + formatSlugToFlow + tagToneFor), `src/features/create/types.ts` (FORMAT_SLUGS), `src/features/create/editor-state.ts` (`groupOf`: video/audio → 'media' group), the checklist files above (placeholder-free real entries EXCEPT `EDITOR_BY_FORMAT`, which may point video/audio at ImageEditor TEMPORARILY with a `// Task 3 replaces` comment — Task 3 lands the real editors), plus adapter/test fallout surfaced by `npm run build`.
**Produces:** `FlowJokeFormat = ... | 'video' | 'audio'`; SKIN entries (video: white card like image; audio: `#F2E9FF` bg / `#6A1CF6` fg — the purple family, distinct at a glance); labels 'Video'/'Audio'; slugs map 1:1.
**Tests:** extend `JokeRenderer.format.test.tsx` — new slugs resolve, maps complete, unknown still null (regression). TDD; full suite + build; commit `media: video and audio format registration across union, maps, and create chrome`.

### Task 2: Renderer branches — video, GIF autoplay, audio + locked variants

**Files:** `src/components/JokeRenderer.tsx`; test `src/components/JokeRenderer.wave2.test.tsx` (create).
**Interfaces:** `JokePayload.media` items already carry `poster_url/duration_ms/is_gif` (wave-1 type). Branch behavior:
- `video`: setup text; unrevealed → `punch-blur` box (aspect from dims) showing the POSTER img (poster is the teaser-safe frame — it went through SafeSearch; locked → no URLs at all, wave-1 placeholder). Reveal → `<video controls playsinline preload="metadata" poster={poster_url} src={url}>` in the same aspect box; duration chip (`0:37`) bottom-right from `duration_ms`.
- `is_gif`: reveal → `<video autoPlay muted loop playsinline src={url}>` (no controls); under `matchMedia('(prefers-reduced-motion: reduce)')` → poster + tap-to-play (autoPlay off, controls on). Read the media-query ONCE per render via a small `usePrefersReducedMotion()` hook (new, `src/hooks/`, mirrors `useBreakpoint`'s matchMedia pattern).
- `audio`: setup text; unrevealed → blurred fixed-height (88px) player placeholder card; reveal → `<audio controls src={url}>` full-width + duration chip. Locked (no dims): the same 88px placeholder via `LockedBody` — extend its media variant: when the first item's kind is 'audio' use height 88 instead of aspect-ratio.
- `onReveal` fires once via the existing `revealSetup` mechanic for all three.
**Tests (≥7):** video unrevealed shows poster img + blur, no `<video>`; reveal renders `<video>` with controls+playsinline and fires onReveal once; is_gif reveal renders muted looping autoplay video; reduced-motion (mock matchMedia) suppresses autoplay; audio reveal renders `<audio controls>`; locked video → no img/video elements + CTA; locked audio → 88px placeholder + CTA. TDD; full suite + build; commit `media: video, GIF, and audio renderer branches with reduced-motion-aware autoplay`.

### Task 3: VideoEditor + AudioEditor + upload kind parameter

**Files:** `src/features/create/api.ts` (+`kind` param on uploadMedia), `adapter.ts`, `mock.ts` (kind-aware mock DTO: video → fake poster objectURL + duration_ms 5000 + is_gif for .gif files), `mutations.ts` (useUploadMedia passes kind), `editors/VideoEditor.tsx` + `editors/AudioEditor.tsx` (create — mirror ImageEditor: caption textarea → `setField setup`; SINGLE file slot (max_media 1): picker accept `video/mp4,video/quicktime,video/webm,image/gif` / `audio/mpeg,audio/mp4,audio/aac`; upload progress; preview (video: `<video controls>` from DTO url + poster; audio: `<audio controls>`); replace/remove; duration display; friendly limits line "MP4/MOV/WebM or GIF · max 60s · max 60MB" / "MP3 or M4A · max 60s · max 10MB"), `editors/index.ts` (real lazy entries replacing Task 1's temporaries), `validation.ts` (no change expected — max_media generic; verify), plus `FORMAT_EXAMPLE`/icons real copy.
**Tests:** mirror `ImageEditor.test.tsx` for both editors (caption dispatch; pick file → uploadMedia called with the right kind → setMedia dispatched); mock-seam test for kind-aware DTO. TDD; full suite + build; commit `media: VideoEditor and AudioEditor with kind-aware upload`.

### Task 4: Watch telemetry client

**Files:** `src/lib/telemetry.ts` (TelemetryType += 'watch'; `trackWatch(jokeId, source, watchMs, watchPct)` — same enqueue/gating seam as trackReveal, but watch events are NOT deduped by the client seen-set (server is append-only; dedupe would drop legitimate re-watches — mirror how dwell bypasses the dedupe, read the file and follow its dwell precedent EXACTLY)), new `src/features/telemetry/useWatchTracking.ts` hook: takes a media-element ref + jokeId + source; listens `timeupdate` (accumulate max currentTime), `pause`/`ended` → send; unmount → send if unsent-delta ≥ 500ms; guard duration 0/NaN. Wire in JokeRenderer's video/audio branches (revealed states only) — the renderer stays router-free; the hook is telemetry-gated internally so anon/no-consent are no-ops.
**Tests:** hook-level with a fake media element (jsdom: dispatchEvent on a real `<video>` element with mocked currentTime/duration via Object.defineProperty — the wave-1 carousel scroll test set the Object.defineProperty precedent): pause sends with accumulated ms; unmount sends; sub-500ms not sent; watch_pct computed. TDD; full suite + build; commit `telemetry: watch events from media playback`.

### Task 5: Insights watch stats + final suite

**Files:** the creator-insights per-joke stats UI — locate with `grep -rn "avg_read_seconds\|payoff_rate" src/` (the top-jokes/stats components from the analytics feature); add `avg_watch_seconds` ("Avg watch 0:12") and `watch_completion_rate` ("74% watched to end") chips rendered ONLY when the API returns them (absent for text/image jokes and against the current prod backend — graceful-absent, no layout shift). Extend the relevant TS response types optionally (`avg_watch_seconds?: number`).
**Tests:** stats component renders watch chips when fields present, omits when absent. Then the wave close-out: full `npm test -- --run` + `npm run build`. Commit `insights: watch-time stats for media jokes`.

---

## Deployment notes (owner-visible)

- FE wave-2 deploys FIRST (unknown-format guard protects; new UI reads degrade gracefully absent backend fields), backend second — same sequence as Wave 1.
- After both: smoke a real iPhone HEVC `.mov` upload (the normalization pipeline's reason to exist) + a GIF + an audio clip; verify reduced-motion behavior in OS settings.
