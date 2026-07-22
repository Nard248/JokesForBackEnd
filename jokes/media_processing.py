"""In-request image processing for media-joke uploads (spec §5.1).

Everything is synchronous and cheap by construction (Pillow on a ≤4096px
source): validate → bake orientation → downscale → re-encode to WebP. The
re-encode is ALSO the EXIF strip — no metadata survives a fresh encode. The
original upload is never stored.
"""
import io
import logging
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

ALLOWED_SOURCE_FORMATS = {'JPEG', 'PNG', 'WEBP'}   # GIF is Wave 2 (video-shaped)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_DIM = 4096
OUT_MAX_DIM = 1600
OUT_QUALITY = 82


class MediaValidationError(Exception):
    """Upload rejected. `errors` is a DRF-style {field: message} dict."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__(str(errors))


class MediaBusyError(Exception):
    """The in-process encode-concurrency guard (_ENCODE_SLOTS) rejected a new
    video/audio job — every slot is in use. Single-container, request-triggered
    app: this is per-instance backpressure, not a global limit — Cloud Run
    scaling out adds more instances, each with its own two slots, which is the
    point (no shared state to coordinate)."""


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes            # WebP-encoded display derivative
    width: int
    height: int
    phash: str             # 64-bit difference hash, 16 hex chars


def dhash_hex(img, hash_size=8):
    """64-bit difference hash — adjacent-pixel gradient signs on an 8x9
    grayscale thumbnail. Pure Pillow (no numpy). This is a dedup/audit
    fingerprint; a CSAM vendor SDK computes its own hashes at activation
    (spec §7.3) — this is NOT PhotoDNA."""
    gray = img.convert('L').resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(gray.getdata())
    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f'{bits:016x}'


def process_image(uploaded):
    """Validate + normalize one uploaded image; returns ProcessedImage.

    Raises MediaValidationError with a field-keyed message dict on any
    rejection (size, type, dimensions, corrupt data).
    """
    size = getattr(uploaded, 'size', None)
    if size is None:                         # raw stream (no Django File): measure it
        uploaded.seek(0, 2)
        size = uploaded.tell()
        uploaded.seek(0)
    if size > MAX_IMAGE_BYTES:
        raise MediaValidationError(
            {'file': f'Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit.'}
        )

    try:
        probe = Image.open(uploaded)
        probe.verify()                       # cheap integrity check
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        raise MediaValidationError({'file': 'Not a valid image.'})

    uploaded.seek(0)
    try:
        img = Image.open(uploaded)           # verify() invalidates; reopen
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        raise MediaValidationError({'file': 'Not a valid image.'})
    if img.format not in ALLOWED_SOURCE_FORMATS:
        raise MediaValidationError(
            {'file': 'Only JPEG, PNG, or WebP images are supported.'}
        )
    if img.width > MAX_SOURCE_DIM or img.height > MAX_SOURCE_DIM:
        raise MediaValidationError(
            {'file': f'Image dimensions exceed {MAX_SOURCE_DIM}px.'}
        )

    try:
        img = ImageOps.exif_transpose(img)   # bake orientation BEFORE strip
        if max(img.size) > OUT_MAX_DIM:
            img.thumbnail((OUT_MAX_DIM, OUT_MAX_DIM), Image.LANCZOS)

        has_alpha = img.mode in ('RGBA', 'LA', 'PA') or 'transparency' in img.info
        img = img.convert('RGBA' if has_alpha else 'RGB')

        phash = dhash_hex(img)
        out = io.BytesIO()
        img.save(out, format='WEBP', quality=OUT_QUALITY)   # fresh encode = no EXIF
    except (OSError, ValueError):
        # verify() is a header check, not a decode guarantee — truncated data
        # can still blow up during decode/transform/encode.
        raise MediaValidationError({'file': 'Not a valid image.'})
    return ProcessedImage(
        data=out.getvalue(), width=img.width, height=img.height, phash=phash,
    )


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
import threading

from .media_probe import probe_media

# Cloud Run's HTTP/1 ingress hard-rejects request bodies over 32MiB before
# they ever reach Django (no MediaValidationError, no JSON — just a bare
# gateway error). 30MB leaves ~2MiB of multipart/form overhead headroom under
# that ceiling, so oversize uploads always fail through OUR error path.
MAX_VIDEO_BYTES = 30 * 1024 * 1024
MAX_GIF_BYTES = 15 * 1024 * 1024
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_MEDIA_DURATION_MS = 60_000
MAX_VIDEO_PIXELS = 1920 * 1080 * 1.2   # 20% margin over 1080p for odd sensor AR
FFMPEG_TIMEOUT = 240   # hard subprocess ceiling; leaves headroom under 300s

# Caps in-process encode concurrency to 2 simultaneous ffmpeg jobs. This is
# per-instance backpressure (single Cloud Run container, request-triggered,
# no workers): two single-threaded x264 encodes can share one vCPU without
# starving other gthread request handlers, but a third would. Cloud Run
# scaling out adds more instances — each gets its own 2 slots — which is the
# intended relief valve, not a shared/global limit.
_ENCODE_SLOTS = threading.BoundedSemaphore(2)


class _EncodeSlot:
    """Non-blocking acquire of an encode slot; raises MediaBusyError instead
    of queuing so a caller under load fails fast with a 429 rather than
    tying up a Cloud Run request thread waiting on ffmpeg capacity."""

    def __enter__(self):
        if not _ENCODE_SLOTS.acquire(blocking=False):
            raise MediaBusyError()
        return self

    def __exit__(self, exc_type, exc, tb):
        _ENCODE_SLOTS.release()
        return False

# ffprobe reports the whole QuickTime family (mp4/mov/m4a/3gp) as 'mov' —
# never the literal 'mp4' — so it's the 'mov' entry below that admits mp4
# uploads, not a separate 'mp4' entry.
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


def _source_path(uploaded, suffix):
    """Return (path, owned) for the uploaded object's on-disk bytes.

    Django's TemporaryUploadedFile (the parser's default for multipart bodies
    above FILE_UPLOAD_MAX_MEMORY_SIZE) has ALREADY spooled the upload to a
    real temp file — `temporary_file_path()` hands us that path directly, so
    we skip a second full copy of the payload. Django owns that file and
    cleans it up itself post-request, so `owned=False` here. In-memory
    uploads (InMemoryUploadedFile, bare BytesIO, etc.) have no on-disk path
    yet, so those still go through `_spool_to_disk` and `owned=True` — WE
    created that file, so WE must unlink it.
    """
    temp_path = getattr(uploaded, 'temporary_file_path', None)
    if callable(temp_path):
        return temp_path(), False
    return _spool_to_disk(uploaded, suffix), True


def _run_ffmpeg(args):
    try:
        completed = subprocess.run(
            ['ffmpeg', '-y', '-loglevel', 'error'] + args,
            capture_output=True, timeout=FFMPEG_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning('ffmpeg timed out after %ss', FFMPEG_TIMEOUT)
        raise MediaValidationError(
            {'file': 'Processing timed out — try a shorter or smaller clip.'}
        )
    except OSError:
        raise MediaValidationError({'file': 'Media processing is unavailable.'})
    if completed.returncode != 0:
        logger.warning(
            'ffmpeg failed (rc=%s): %s',
            completed.returncode, (completed.stderr or b'')[-500:],
        )
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
    src, owned = None, False
    try:
        src, owned = _source_path(uploaded, '.gif' if is_gif else '.bin')
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
        if info.width and info.height and info.width * info.height > MAX_VIDEO_PIXELS:
            raise MediaValidationError(
                {'file': 'Videos larger than 1080p are not supported yet — '
                         'export at 1080p or lower.'}
            )

        out = os.path.join(workdir, 'out.mp4')
        # '-fpsmax' (NOT '-fps_max' / '-max_fps') requires ffmpeg >=4.4 —
        # prod (5.1) and dev (8.1) are both safe. Get the spelling wrong and
        # ffmpeg exits non-zero on an unrecognized option, which surfaces to
        # the caller only as the generic "Could not process this media file"
        # (_run_ffmpeg has no argv-specific error path) — there's no other
        # signal to catch a typo here besides this comment and the tests.
        args = ['-i', src,
                '-vf', "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2",
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                '-threads', '1', '-movflags', '+faststart', '-fpsmax', '30']
        if is_gif or info.audio_codec is None:
            args += ['-an']
        else:
            args += ['-c:a', 'aac', '-b:a', '128k']
        args += [out]

        with _EncodeSlot():
            _run_ffmpeg(args)

            out_info = probe_media(out)
            duration_ms = out_info.duration_ms or info.duration_ms
            # Belt-and-suspenders: the pre-encode probe already rejected
            # anything over MAX_MEDIA_DURATION_MS, but metadata can lie
            # (malformed/forged duration atoms) — recheck what ffmpeg
            # actually produced. 2s slack absorbs container rounding.
            if duration_ms > MAX_MEDIA_DURATION_MS + 2000:
                raise MediaValidationError(
                    {'file': f'Clips must be {MAX_MEDIA_DURATION_MS // 1000} seconds or shorter.'}
                )
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
        if owned and src:
            try:
                os.unlink(src)
            except OSError:
                pass


def process_audio(uploaded):
    """Re-encode one audio upload to AAC/M4A."""
    _enforce_size(uploaded, MAX_AUDIO_BYTES, 'Audio')
    workdir = tempfile.mkdtemp(prefix='media-audio-')
    src, owned = None, False
    try:
        src, owned = _source_path(uploaded, '.bin')
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
        with _EncodeSlot():
            _run_ffmpeg(['-i', src, '-vn', '-c:a', 'aac', '-b:a', '128k', out])
            out_info = probe_media(out)
        with open(out, 'rb') as fh:
            data = fh.read()
        return ProcessedAudio(data=data, duration_ms=out_info.duration_ms or info.duration_ms)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        if owned and src:
            try:
                os.unlink(src)
            except OSError:
                pass
