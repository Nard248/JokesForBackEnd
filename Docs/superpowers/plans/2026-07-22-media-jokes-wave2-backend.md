# Media Jokes Wave 2 — Backend Implementation Plan (video / audio / GIF + watch telemetry)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Video, audio, and GIF jokes on the backend per spec §5.2/§6.1/§9 — ffmpeg normalization in-request, poster/sampled-frame SafeSearch, `video`/`audio` format registry entries, and the `watch` telemetry event feeding creator insights.

**Architecture:** ffmpeg/ffprobe as subprocesses on temp files (single-threaded x264, veryfast, 720p CRF 23, `+faststart`); probe-before-transcode so cheap rejections never pay encode cost; GIF becomes a silent looping MP4 (`is_gif=true`); audio re-muxes to AAC/M4A. Everything else (MediaAsset, locking, publish/takedown/account-delete lifecycle, anon paywall) is format-agnostic from Wave 1 and extends by registry entry.

**Tech Stack:** Django 5.2 + DRF (existing), ffmpeg/ffprobe (new apt deps in Docker), freezegun.

## Global Constraints

- Single Cloud Run app; request-triggered only; NO Celery/cron/workers/threads. ffmpeg runs as a blocking subprocess inside the request.
- Tests: Django runner, NEVER pytest: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test <target> --keepdb`. Video tests generate tiny fixture clips with the local ffmpeg (guard the classes with `@unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg not installed')`).
- Commit messages: plain, descriptive, NO footers/emoji.
- Measured budget (2026-07-22, M-series 1-thread: 60s 1080p→720p = ~19s CPU; Cloud Run ≈ 2-3× slower): keep single-threaded encode, `-preset veryfast`, hard caps below. Cloud Run request timeout is ALREADY 300s; gunicorn `--timeout` must be raised to 300 to match.
- Caps (spec §5.2 amended by the measurement): video upload ≤60MB, duration ≤60s, accepted containers MP4/MOV/WebM (H.264/HEVC/VP8/VP9 in), normalized to H.264/AAC MP4, 720p max, `+faststart`. GIF ≤15MB → silent looping MP4 (`is_gif=true`). Audio ≤10MB, ≤60s, MP3/M4A/AAC in → AAC/M4A out.
- Screening: SafeSearch on the poster + 2 sampled frames (any blocked frame blocks the upload); audio has NO automated screen (human review only — documented residual risk).
- Formats (spec §6.1): `video` = required [setup, media], forbidden [punchline, lines], constraints {media_kind: 'video', min_media: 1, max_media: 1, max_duration_ms: 60000}; `audio` same shape with media_kind 'audio'. GIF is NOT a format — a GIF upload becomes a `video`-kind asset with `is_gif=true`.
- Watch telemetry (spec §9): new `watch` event {joke_id, watch_ms, watch_pct, source} → append-only `JokeWatch` (clamped like dwell); `JokeDwell.scroll_pct` is NOT overloaded. Insights: media jokes gain `avg_watch_seconds` + `watch_completion_rate` (watch_pct ≥ 90); `payoff_rate` stays reveal-based everywhere.
- Wave-1 machinery MUST NOT need changes to accept the new kinds (it was built format-agnostic): publish copy, takedown reap, account-delete media-joke removal (media_slugs derives from FORMAT_RULES — verify it now includes video/audio automatically), locking (serializers already emit poster_url/duration_ms/is_gif), anon paywall. Tasks below only VERIFY these with tests, never rewrite them.
- New tests: `jokes/tests_media_wave2.py` (separate file — tests_media.py is already ~1000 lines).

---

### Task 1: Docker runtime (ffmpeg + gunicorn 300) + probe module

**Files:**
- Modify: `Dockerfile` (runtime apt list L35-40; gunicorn CMD L65-71)
- Create: `jokes/media_probe.py`
- Test: `jokes/tests_media_wave2.py` (create)

**Interfaces:**
- Consumes: nothing project-specific.
- Produces: `probe_media(path: str) -> MediaProbe(container: str, video_codec: str|None, audio_codec: str|None, width: int|None, height: int|None, duration_ms: int|None)`; raises `MediaValidationError` (imported from `jokes.media_processing`) on unparseable input. `FFPROBE_TIMEOUT = 30` (seconds, subprocess timeout).

- [ ] **Step 1: Dockerfile**

Runtime apt list gains `ffmpeg` (after `libpq5`):

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpq5 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
```

gunicorn CMD: `--timeout 60` → `--timeout 300`, with the comment updated:

```dockerfile
# --timeout 300 matches the Cloud Run request timeout: in-request video
# normalization (wave 2) can legitimately run for minutes; gthread heartbeats
# keep the arbiter satisfied while a worker thread encodes.
```

- [ ] **Step 2: Write the failing probe tests**

Create `jokes/tests_media_wave2.py`:

```python
"""Wave 2 media tests: probe, video/audio/GIF pipeline, formats, watch telemetry."""
import io
import shutil
import subprocess
import tempfile
import unittest

from django.test import TestCase

FFMPEG = shutil.which('ffmpeg')

_MEDIA_ROOT = tempfile.mkdtemp()


def make_clip(path, seconds=2, size='320x240', fmt='mp4', audio=True, vcodec=None):
    """Generate a tiny real test clip with the local ffmpeg."""
    cmd = ['ffmpeg', '-y', '-loglevel', 'error',
           '-f', 'lavfi', '-i', f'testsrc2=size={size}:rate=10']
    if audio:
        cmd += ['-f', 'lavfi', '-i', 'sine=frequency=440']
    cmd += ['-t', str(seconds)]
    if vcodec:
        cmd += ['-c:v', vcodec]
    if audio:
        cmd += ['-c:a', 'aac', '-shortest']
    cmd += [path]
    subprocess.run(cmd, check=True, timeout=60)
    return path


def make_audio(path, seconds=2, codec='libmp3lame'):
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', 'sine=frequency=440',
                    '-t', str(seconds), '-c:a', codec, path],
                   check=True, timeout=60)
    return path


def make_gif(path, seconds=1):
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', f'testsrc2=size=160x120:rate=5',
                    '-t', str(seconds), path], check=True, timeout=60)
    return path


@unittest.skipUnless(FFMPEG, 'ffmpeg not installed')
class ProbeTests(TestCase):
    def test_probe_mp4_reports_codecs_dims_duration(self):
        from jokes.media_probe import probe_media
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4')
            info = probe_media(clip)
        self.assertEqual(info.video_codec, 'h264')
        self.assertEqual(info.audio_codec, 'aac')
        self.assertEqual((info.width, info.height), (320, 240))
        self.assertTrue(1500 <= info.duration_ms <= 2600)

    def test_probe_audio_only(self):
        from jokes.media_probe import probe_media
        with tempfile.TemporaryDirectory() as d:
            clip = make_audio(f'{d}/in.mp3')
            info = probe_media(clip)
        self.assertIsNone(info.video_codec)
        self.assertEqual(info.audio_codec, 'mp3')

    def test_probe_garbage_raises_validation_error(self):
        from jokes.media_probe import probe_media
        from jokes.media_processing import MediaValidationError
        with tempfile.NamedTemporaryFile(suffix='.mp4') as f:
            f.write(b'this is not a video')
            f.flush()
            with self.assertRaises(MediaValidationError):
                probe_media(f.name)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media_wave2 --keepdb`
Expected: FAIL — `ModuleNotFoundError: No module named 'jokes.media_probe'`.

- [ ] **Step 4: Implement `jokes/media_probe.py`**

```python
"""ffprobe wrapper — cheap metadata inspection BEFORE any transcode spend.

Runs `ffprobe -print_format json` as a subprocess with a hard timeout.
All failures (missing binary, timeout, unparseable input) surface as
MediaValidationError so callers keep the single-exception contract from
jokes.media_processing.
"""
import json
import subprocess
from dataclasses import dataclass

from .media_processing import MediaValidationError

FFPROBE_TIMEOUT = 30


@dataclass(frozen=True)
class MediaProbe:
    container: str
    video_codec: str | None
    audio_codec: str | None
    width: int | None
    height: int | None
    duration_ms: int | None


def probe_media(path):
    try:
        completed = subprocess.run(
            ['ffprobe', '-v', 'error', '-print_format', 'json',
             '-show_format', '-show_streams', path],
            capture_output=True, timeout=FFPROBE_TIMEOUT, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        raise MediaValidationError({'file': 'Could not read this media file.'})
    if completed.returncode != 0:
        raise MediaValidationError({'file': 'Not a valid media file.'})
    try:
        data = json.loads(completed.stdout or b'{}')
    except ValueError:
        raise MediaValidationError({'file': 'Not a valid media file.'})

    fmt = data.get('format') or {}
    streams = data.get('streams') or []
    if not streams:
        raise MediaValidationError({'file': 'Not a valid media file.'})

    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)

    duration_ms = None
    raw_duration = fmt.get('duration') or (video or audio or {}).get('duration')
    if raw_duration is not None:
        try:
            duration_ms = int(float(raw_duration) * 1000)
        except (TypeError, ValueError):
            duration_ms = None

    return MediaProbe(
        container=(fmt.get('format_name') or '').split(',')[0],
        video_codec=video.get('codec_name') if video else None,
        audio_codec=audio.get('codec_name') if audio else None,
        width=int(video['width']) if video and video.get('width') else None,
        height=int(video['height']) if video and video.get('height') else None,
        duration_ms=duration_ms,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media_wave2 --keepdb`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add Dockerfile jokes/media_probe.py jokes/tests_media_wave2.py
git commit -m "media: ffprobe metadata probe module; ffmpeg in runtime image; gunicorn timeout 300"
```

---

### Task 2: Video / GIF / audio normalization pipeline

**Files:**
- Modify: `jokes/media_processing.py` (append a wave-2 section)
- Test: `jokes/tests_media_wave2.py` (append)

**Interfaces:**
- Consumes: Task 1 `probe_media`/`MediaProbe`; existing `MediaValidationError`, `dhash_hex`.
- Produces:
  - `process_video(uploaded, is_gif=False) -> ProcessedVideo(data: bytes, width: int, height: int, duration_ms: int, poster: bytes, sample_frames: list[bytes], phash: str)` — normalized MP4 (H.264/AAC, ≤720p, faststart; GIF: no audio, same container), poster JPEG at ~1s, 2 more JPEGs at 1/3 and 2/3 duration, `phash` = dHash of the poster.
  - `process_audio(uploaded) -> ProcessedAudio(data: bytes, duration_ms: int)` — AAC in M4A.
  - Constants: `MAX_VIDEO_BYTES = 60*1024*1024`, `MAX_GIF_BYTES = 15*1024*1024`, `MAX_AUDIO_BYTES = 10*1024*1024`, `MAX_MEDIA_DURATION_MS = 60_000`, `FFMPEG_TIMEOUT = 240`.
  - All rejections raise `MediaValidationError`; subprocess timeout ⇒ `MediaValidationError({'file': 'Processing timed out — try a shorter or smaller clip.'})`.

- [ ] **Step 1: Write the failing tests**

Append to `jokes/tests_media_wave2.py`:

```python
from PIL import Image


@unittest.skipUnless(FFMPEG, 'ffmpeg not installed')
class VideoPipelineTests(TestCase):
    def _upload_from(self, path):
        with open(path, 'rb') as f:
            buf = io.BytesIO(f.read())
        buf.name = path.rsplit('/', 1)[-1]
        return buf

    def test_mp4_normalized_with_poster_and_samples(self):
        from jokes.media_probe import probe_media
        from jokes.media_processing import process_video
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', seconds=3)
            result = process_video(self._upload_from(clip))
            out_path = f'{d}/out.mp4'
            with open(out_path, 'wb') as f:
                f.write(result.data)
            info = probe_media(out_path)
        self.assertEqual(info.video_codec, 'h264')
        self.assertEqual(info.audio_codec, 'aac')
        self.assertEqual(len(result.sample_frames), 2)
        self.assertEqual(len(result.phash), 16)
        poster = Image.open(io.BytesIO(result.poster))
        self.assertEqual(poster.format, 'JPEG')
        self.assertTrue(2500 <= result.duration_ms <= 3600)

    def test_downscales_above_720p(self):
        from jokes.media_processing import process_video
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', seconds=2, size='1920x1080')
            result = process_video(self._upload_from(clip))
        self.assertEqual(result.height, 720)
        self.assertEqual(result.width, 1280)

    def test_overlong_rejected_before_transcode(self):
        from jokes.media_processing import MAX_MEDIA_DURATION_MS, MediaValidationError, process_video
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', seconds=2)
            # Fake an overlong probe so we don't generate a >60s fixture.
            from jokes.media_probe import MediaProbe
            long_probe = MediaProbe('mov', 'h264', 'aac', 320, 240,
                                    MAX_MEDIA_DURATION_MS + 5000)
            with patch('jokes.media_processing.probe_media', return_value=long_probe), \
                 patch('jokes.media_processing._run_ffmpeg') as encode:
                with self.assertRaises(MediaValidationError):
                    process_video(self._upload_from(clip))
                encode.assert_not_called()

    def test_oversize_video_rejected(self):
        from jokes.media_processing import MAX_VIDEO_BYTES, MediaValidationError, process_video
        buf = io.BytesIO(b'x')
        buf.size = MAX_VIDEO_BYTES + 1
        buf.name = 'big.mp4'
        with self.assertRaises(MediaValidationError):
            process_video(buf)

    def test_gif_becomes_silent_mp4(self):
        from jokes.media_probe import probe_media
        from jokes.media_processing import process_video
        with tempfile.TemporaryDirectory() as d:
            gif = make_gif(f'{d}/in.gif')
            result = process_video(self._upload_from(gif), is_gif=True)
            out_path = f'{d}/out.mp4'
            with open(out_path, 'wb') as f:
                f.write(result.data)
            info = probe_media(out_path)
        self.assertEqual(info.video_codec, 'h264')
        self.assertIsNone(info.audio_codec)

    def test_garbage_rejected(self):
        from jokes.media_processing import MediaValidationError, process_video
        buf = io.BytesIO(b'not a video at all')
        buf.name = 'x.mp4'
        with self.assertRaises(MediaValidationError):
            process_video(buf)


@unittest.skipUnless(FFMPEG, 'ffmpeg not installed')
class AudioPipelineTests(TestCase):
    def test_mp3_remuxed_to_m4a_aac(self):
        from jokes.media_probe import probe_media
        from jokes.media_processing import process_audio
        with tempfile.TemporaryDirectory() as d:
            src = make_audio(f'{d}/in.mp3')
            with open(src, 'rb') as f:
                buf = io.BytesIO(f.read())
            buf.name = 'in.mp3'
            result = process_audio(buf)
            out = f'{d}/out.m4a'
            with open(out, 'wb') as f:
                f.write(result.data)
            info = probe_media(out)
        self.assertEqual(info.audio_codec, 'aac')
        self.assertIsNone(info.video_codec)
        self.assertTrue(1500 <= result.duration_ms <= 2600)

    def test_video_container_rejected_as_audio(self):
        from jokes.media_processing import MediaValidationError, process_audio
        with tempfile.TemporaryDirectory() as d:
            clip = make_clip(f'{d}/in.mp4', seconds=2)
            with open(clip, 'rb') as f:
                buf = io.BytesIO(f.read())
            buf.name = 'in.mp4'
            with self.assertRaises(MediaValidationError):
                process_audio(buf)
```

- [ ] **Step 2: Run to verify failure**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media_wave2.VideoPipelineTests jokes.tests_media_wave2.AudioPipelineTests --keepdb`
Expected: FAIL — ImportError (`process_video` undefined).

- [ ] **Step 3: Implement (append to `jokes/media_processing.py`)**

```python
# =============================================================================
# Wave 2: video / GIF / audio normalization (spec §5.2)
# =============================================================================
# ffmpeg as a subprocess on temp files. Probe first so cheap rejections
# (wrong kind, overlong) never pay transcode cost. Single-threaded x264 on
# purpose: one encode must not starve the other gthread request handlers on
# Cloud Run's single vCPU. Measured 2026-07-22: 60s 1080p→720p ≈ 19s CPU on
# an M-series core ⇒ well inside the 300s gunicorn/Cloud Run ceiling even at
# 2-3× slower per-core.
import os
import shutil
import subprocess
import tempfile

from .media_probe import probe_media

MAX_VIDEO_BYTES = 60 * 1024 * 1024
MAX_GIF_BYTES = 15 * 1024 * 1024
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_MEDIA_DURATION_MS = 60_000
FFMPEG_TIMEOUT = 240   # hard subprocess ceiling; leaves headroom under 300s

_VIDEO_CONTAINERS = {'mov', 'mp4', 'm4a', 'matroska', 'webm', 'gif'}
_AUDIO_CODECS_IN = {'mp3', 'aac', 'alac', 'pcm_s16le', 'vorbis', 'opus', 'flac'}


@dataclass(frozen=True)
class ProcessedVideo:
    data: bytes
    width: int
    height: int
    duration_ms: int
    poster: bytes
    sample_frames: list
    phash: str


@dataclass(frozen=True)
class ProcessedAudio:
    data: bytes
    duration_ms: int


def _enforce_size(uploaded, cap, label):
    size = getattr(uploaded, 'size', None)
    if size is None:
        uploaded.seek(0, 2)
        size = uploaded.tell()
        uploaded.seek(0)
    if size > cap:
        raise MediaValidationError(
            {'file': f'{label} exceeds the {cap // (1024 * 1024)}MB limit.'}
        )


def _spool_to_disk(uploaded, suffix):
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    uploaded.seek(0)
    shutil.copyfileobj(uploaded, handle)
    handle.flush()
    handle.close()
    return handle.name


def _run_ffmpeg(args):
    try:
        completed = subprocess.run(
            ['ffmpeg', '-y', '-loglevel', 'error'] + args,
            capture_output=True, timeout=FFMPEG_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        raise MediaValidationError(
            {'file': 'Processing timed out — try a shorter or smaller clip.'}
        )
    except OSError:
        raise MediaValidationError({'file': 'Media processing is unavailable.'})
    if completed.returncode != 0:
        raise MediaValidationError({'file': 'Could not process this media file.'})


def _extract_frame(src, at_seconds, out_path):
    _run_ffmpeg(['-ss', f'{max(0.0, at_seconds):.2f}', '-i', src,
                 '-frames:v', '1', '-q:v', '4', out_path])
    with open(out_path, 'rb') as fh:
        return fh.read()


def process_video(uploaded, is_gif=False):
    """Normalize one video/GIF upload to H.264/AAC progressive MP4 ≤720p."""
    _enforce_size(uploaded, MAX_GIF_BYTES if is_gif else MAX_VIDEO_BYTES,
                  'GIF' if is_gif else 'Video')
    workdir = tempfile.mkdtemp(prefix='media-video-')
    try:
        src = _spool_to_disk(uploaded, '.gif' if is_gif else '.bin')
        info = probe_media(src)
        if info.video_codec is None:
            raise MediaValidationError({'file': 'No video track found.'})
        if info.container not in _VIDEO_CONTAINERS:
            raise MediaValidationError(
                {'file': 'Only MP4, MOV, WebM, or GIF uploads are supported.'}
            )
        if info.duration_ms is None or info.duration_ms > MAX_MEDIA_DURATION_MS:
            raise MediaValidationError(
                {'file': f'Clips must be {MAX_MEDIA_DURATION_MS // 1000} seconds or shorter.'}
            )

        out = os.path.join(workdir, 'out.mp4')
        args = ['-i', src,
                '-vf', "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2",
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                '-threads', '1', '-movflags', '+faststart', '-fps_max', '30']
        if is_gif or info.audio_codec is None:
            args += ['-an']
        else:
            args += ['-c:a', 'aac', '-b:a', '128k']
        args += [out]
        _run_ffmpeg(args)

        out_info = probe_media(out)
        duration_ms = out_info.duration_ms or info.duration_ms
        seconds = duration_ms / 1000.0
        poster = _extract_frame(out, min(1.0, seconds / 2), os.path.join(workdir, 'poster.jpg'))
        samples = [
            _extract_frame(out, seconds / 3, os.path.join(workdir, 's1.jpg')),
            _extract_frame(out, 2 * seconds / 3, os.path.join(workdir, 's2.jpg')),
        ]
        phash = dhash_hex(Image.open(io.BytesIO(poster)))
        with open(out, 'rb') as fh:
            data = fh.read()
        return ProcessedVideo(
            data=data, width=out_info.width, height=out_info.height,
            duration_ms=duration_ms, poster=poster, sample_frames=samples,
            phash=phash,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        try:
            os.unlink(src)
        except (OSError, UnboundLocalError):
            pass


def process_audio(uploaded):
    """Re-encode one audio upload to AAC/M4A."""
    _enforce_size(uploaded, MAX_AUDIO_BYTES, 'Audio')
    workdir = tempfile.mkdtemp(prefix='media-audio-')
    try:
        src = _spool_to_disk(uploaded, '.bin')
        info = probe_media(src)
        if info.video_codec is not None:
            raise MediaValidationError(
                {'file': 'This looks like a video — upload it as a video joke.'}
            )
        if info.audio_codec not in _AUDIO_CODECS_IN:
            raise MediaValidationError(
                {'file': 'Only MP3, M4A/AAC, or common audio formats are supported.'}
            )
        if info.duration_ms is None or info.duration_ms > MAX_MEDIA_DURATION_MS:
            raise MediaValidationError(
                {'file': f'Clips must be {MAX_MEDIA_DURATION_MS // 1000} seconds or shorter.'}
            )
        out = os.path.join(workdir, 'out.m4a')
        _run_ffmpeg(['-i', src, '-vn', '-c:a', 'aac', '-b:a', '128k', out])
        out_info = probe_media(out)
        with open(out, 'rb') as fh:
            data = fh.read()
        return ProcessedAudio(data=data, duration_ms=out_info.duration_ms or info.duration_ms)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        try:
            os.unlink(src)
        except (OSError, UnboundLocalError):
            pass
```

(`dataclass`, `io`, `Image` are already imported at the top of the module from Wave 1 — verify, don't duplicate.)

- [ ] **Step 4: Run to verify green, then commit**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media_wave2 --keepdb` → PASS (11 tests).

```bash
git add jokes/media_processing.py jokes/tests_media_wave2.py
git commit -m "media: in-request video/GIF/audio normalization with probe-first rejection and frame extraction"
```

---

### Task 3: Upload endpoint accepts video / audio / GIF + frame screening

**Files:**
- Modify: `jokes/views.py` (`MediaUploadView.post`)
- Test: `jokes/tests_media_wave2.py` (append)

**Interfaces:**
- Consumes: Task 2 pipeline; existing `screen_image`, `get_matcher`, `MediaAsset`, `record_audit`, `_sweep_orphan_assets`.
- Produces: `POST /media/uploads/` accepts `kind` in {image, video, audio}; a `.gif`/`image/gif` file POSTed with kind `image` OR `video` is routed to `process_video(is_gif=True)` and stored as kind `video` with `is_gif=true`. Video assets store `file` (MP4), `poster` (JPEG), width/height/duration_ms/phash/safesearch (poster + 2 frames verdicts: `{'status': ..., 'frames': [v1, v2, v3]}` — blocked if ANY frame blocked). Audio assets store file/duration_ms only (safesearch `{'status': 'not_applicable'}`). Response shape unchanged (Wave-1 serializer already carries all fields).

- [ ] **Step 1: Failing tests** (append; class `MediaUploadWave2Tests`, `@unittest.skipUnless(FFMPEG, ...)`, `override_settings(MEDIA_ROOT=_MEDIA_ROOT)`, authenticated APIClient like Wave 1's upload tests — import helpers from `jokes.tests_media`):

```python
# Key cases (write them all as real tests):
# 1. POST kind=video with a small real mp4 → 201; asset.kind == 'video';
#    poster file exists; duration_ms set; response has poster_url and is_gif False.
# 2. POST kind=video with a GIF file → 201; kind == 'video'; is_gif True; silent.
# 3. POST kind=image with a GIF file → routed the same as (2) (backwards-friendly).
# 4. POST kind=audio with an mp3 → 201; kind == 'audio'; no poster; duration_ms set.
# 5. Screening: patch jokes.views.screen_image to return blocked for the SECOND
#    frame only → 422, no asset row (assert screen_image called 3 times for video).
# 6. POST kind=video with a text file → 400.
# 7. Oversize video (fake .size attr) → 400 before any ffmpeg call
#    (patch jokes.media_processing._run_ffmpeg, assert not called).
```

- [ ] **Step 2: Verify failure, implement**

Rework `MediaUploadView.post`'s kind gate into a dispatcher (keep the image path byte-identical; the audit calls, hash-matcher, sweep, and DB-failure cleanup pattern from Wave 1 apply to ALL kinds):

```python
        kind = (request.data.get('kind') or 'image').strip()
        if kind not in ('image', 'video', 'audio'):
            return Response({'kind': ["Unsupported kind."]}, status=400)
        uploaded = request.FILES.get('file')
        if uploaded is None:
            return Response({'file': ['This field is required.']}, status=400)

        content_type = (uploaded.content_type or '').lower()
        name = (uploaded.name or '').lower()
        is_gif = content_type == 'image/gif' or name.endswith('.gif')

        if kind == 'image' and not is_gif:
            # ... existing Wave-1 image path unchanged ...
        elif kind == 'audio':
            processed = process_audio(uploaded)          # MediaValidationError → 400
            verdict = {'status': 'not_applicable'}       # no visual to screen
            asset = MediaAsset(owner=request.user, kind='audio',
                               duration_ms=processed.duration_ms,
                               safesearch=verdict)
            asset.file.save('audio.m4a', ContentFile(processed.data), save=False)
        else:   # video, or GIF submitted under either kind
            processed = process_video(uploaded, is_gif=is_gif)
            frame_verdicts = [screen_image(processed.poster)] + [
                screen_image(frame) for frame in processed.sample_frames
            ]
            if any(v.get('status') == 'blocked' for v in frame_verdicts):
                record_audit(request, 'safesearch_block', outcome='blocked',
                             actor=request.user, target_type='media_upload', target_id='')
                return Response({'file': ['This clip was rejected by automated content screening.']},
                                status=422)
            hit = get_matcher().match(processed.phash)
            if hit:
                # ... same as Wave 1's hash-hit branch ...
            verdict = {'status': 'ok' if all(v.get('status') in ('ok', 'skipped') for v in frame_verdicts) else 'error',
                       'frames': frame_verdicts}
            asset = MediaAsset(owner=request.user, kind='video',
                               width=processed.width, height=processed.height,
                               duration_ms=processed.duration_ms, is_gif=is_gif,
                               phash=processed.phash, safesearch=verdict)
            asset.file.save('video.mp4', ContentFile(processed.data), save=False)
            asset.poster.save('poster.jpg', ContentFile(processed.poster), save=False)
```

then the shared tail (try/except-guarded `asset.save()` with storage cleanup, sweep, audit, serializer response) — REFACTOR the tail into one shared block rather than duplicating it three times. Adapt precisely to the current code (read the whole method first).

- [ ] **Step 3: Green + regression + commit**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media_wave2 jokes.tests_media --keepdb` → all green (Wave-1 upload tests must be untouched).

```bash
git add jokes/views.py jokes/tests_media_wave2.py
git commit -m "media: upload endpoint accepts video, audio, and GIF with poster and sampled-frame screening"
```

---

### Task 4: `video` / `audio` formats — registry, seed, wave-1 machinery verification

**Files:**
- Modify: `jokes/submission_rules.py`
- Create: `jokes/migrations/00XX_seed_video_audio_formats.py`
- Test: `jokes/tests_media_wave2.py` (append)

**Interfaces:**
- Produces: `FORMAT_RULES['video']` and `['audio']` per Global Constraints (incl. `max_duration_ms: 60000` constraint enforced in `validate_per_format` when attrs['media'] items carry durations — extend the attrs contract: `attrs['media']` becomes a list of `{'kind': str, 'duration_ms': int|None}` dicts; UPDATE the wave-1 call sites (serializer + submit view) to pass dicts, and the image rule keeps working (kind check reads `item['kind']`)).
- VERIFIES (tests only, no production edits expected): publish copy, locking (video media emits poster_url/duration_ms when unlocked; dims-only when locked — poster_url must NOT leak when locked), account-delete media_slugs now includes video/audio automatically, takedown reap, draft attach of a video asset to a video-format draft, submit gate rejecting a video asset on an image draft (kind mismatch).

- [ ] **Step 1: Failing tests** — rule-level tests mirroring Wave 1's `ImageFormatRuleTests` for both new slugs (required/forbidden/kind-mismatch/duration-cap), plus integration tests: create video-format draft via API, attach a video asset (`make_asset(user, kind='video', duration_ms=5000)` — extend the Wave-1 helper import or build locally), submit → pending; publish via admin → JokeMedia copied; serialize locked → `{kind,width,height}` ONLY (explicitly assert `poster_url` absent); account-delete removes an emptied video joke (media_slugs auto-derivation).

- [ ] **Step 2: Implement** — FORMAT_RULES entries; `validate_per_format` media block: kind check via `item.get('kind')`, plus:

```python
            max_duration = constraints.get('max_duration_ms')
            if max_duration is not None and 'media' not in errors:
                for item in media:
                    if item.get('duration_ms') and item['duration_ms'] > max_duration:
                        errors['media'] = (
                            f'Clips must be {max_duration // 1000} seconds or shorter.'
                        )
                        break
```

Update the two wave-1 attrs call sites to emit `[{'kind': a.kind, 'duration_ms': a.duration_ms}]`, and change the wave-1 kind check from string comparison to `item.get('kind')`. **This is a deliberate contract change: Wave 1's `ImageFormatRuleTests` (and any other test passing `{'media': ['image']}` string lists) MUST be updated to the dict shape — update those assertions and say so in the report; they are pinning the retired contract, not a regression.** Seed migration follows the 0031 pattern (two rows: Video, Audio; reverse deletes only unreferenced).

- [ ] **Step 3: Green + full wave-1 file + commit**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media_wave2 jokes.tests_media jokes.tests --keepdb` → all green.

```bash
git add jokes/submission_rules.py jokes/serializers.py jokes/views.py jokes/migrations jokes/tests_media_wave2.py
git commit -m "media: video and audio format rules with duration constraint; seed rows; wave-1 machinery verified"
```

---

### Task 5: Watch telemetry — `JokeWatch` + ingest + insights

**Files:**
- Modify: `jokes/models.py` (append `JokeWatch`), `jokes/views.py` (`TelemetryIngestView`), `creator_insights/services.py`
- Create: migration (makemigrations)
- Test: `jokes/tests_media_wave2.py` (append) + extend `creator_insights` tests only if its suite has a natural home (report if not)

**Interfaces:**
- Produces: `JokeWatch(user FK, joke FK, watch_ms int clamped [0, 600000], watch_pct int clamped [0,100] null, source, watched_at)` append-only (no dedupe — mirrors JokeDwell); `watch` joins the telemetry etype whitelist: `{type:'watch', joke_id, watch_ms, watch_pct?, source}` — drop watch_ms < 500; insights: for jokes whose format requires media AND kind is video/audio, `avg_watch_seconds` (Avg(watch_ms)/1000) and `watch_completion_rate` (watch_pct ≥ 90 over samples carrying watch_pct) appear in the per-joke stats the dashboard serves (mirror how avg_read_seconds/completion_rate are computed and exposed in creator_insights/services.py — read it first; keys sit beside the existing ones, null/absent for text/image jokes).
- `payoff_rate` is untouched.

- [ ] **Step 1: Failing tests** — model clamps; ingest happy path (batch with a watch event → row created, 202 accepted count); sub-500ms dropped; bad joke_id silently skipped (mirror existing ingest behavior); insights aggregation with seeded JokeWatch rows.
- [ ] **Step 2: Implement** — model + migration; ingest branch mirroring the dwell branch (read it and match its validation/clamping style exactly); services additions with correlated-subquery style matching `_annotated_top_jokes_qs` conventions.
- [ ] **Step 3: Green + creator_insights suite + commit**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media_wave2 jokes.tests_telemetry creator_insights --keepdb` → all green.

```bash
git add jokes/models.py jokes/migrations jokes/views.py creator_insights/services.py jokes/tests_media_wave2.py
git commit -m "telemetry: watch events for media jokes with insights watch-time aggregates"
```

---

### Task 6: Full-suite regression

- [ ] Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test --keepdb` → EVERYTHING green (547 wave-1 baseline + wave-2 additions). Fix regressions in production code (or update tests that pin retired behavior, documented). Commit only if fixes were needed.

---

## Deployment notes (owner-visible, not tasks)

- **DEPLOY GATE (final review C1, 2026-07-22): the 1Gi memory bump is REQUIRED, not optional** — `gcloud run services update jokesforbackend --region=us-east1 --project=jokesfor --memory=1Gi`. At 512Mi a single real video upload OOMs the instance (RAM-backed /tmp + ffmpeg working set), killing every in-flight request. The code side adds a 1080p input cap + spool reuse to keep the envelope inside 1Gi. CPU stays 1000m.
- **Caps amended (final review C2): video upload cap is 30MB** — Cloud Run's HTTP/1 ingress rejects >32MiB requests before Django ever sees them, so the spec's 60MB was unreachable. FE copy must say 30MB. Post-deploy smoke MUST include a >32MB upload to confirm the ingress behavior (expect a platform 413).
- Cloud Run request timeout already 300s ✓ (verified 2026-07-22). Dockerfile raises gunicorn to match.
- Deploy order: frontend wave-2 (rendering/editors) first, backend second — same rationale as Wave 1; the FE unknown-format guard already hides `video`/`audio` jokes from old bundles.
- Post-deploy smoke: upload a real phone video (HEVC .mov) — the normalization pipeline's reason for existing.
