"""ffprobe wrapper — cheap metadata inspection BEFORE any transcode spend.

Runs `ffprobe -print_format json` as a subprocess with a hard timeout.
All failures (missing binary, timeout, unparseable input) surface as
MediaValidationError so callers keep the single-exception contract from
jokes.media_processing.
"""
import json
import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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
    # Imported here, not at module level: jokes.media_processing imports
    # probe_media from this module at ITS module level, so a top-level
    # `from .media_processing import MediaValidationError` here would form
    # a circular import that raises ImportError whenever media_probe is the
    # first of the two modules to be imported in a fresh interpreter.
    from .media_processing import MediaValidationError

    try:
        completed = subprocess.run(
            ['ffprobe', '-v', 'error', '-print_format', 'json',
             '-show_format', '-show_streams', path],
            capture_output=True, timeout=FFPROBE_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning('ffprobe timed out after %ss', FFPROBE_TIMEOUT)
        raise MediaValidationError({'file': 'Could not read this media file.'})
    except OSError:
        raise MediaValidationError({'file': 'Could not read this media file.'})
    if completed.returncode != 0:
        logger.warning(
            'ffprobe failed (rc=%s): %s',
            completed.returncode, (completed.stderr or b'')[-500:],
        )
        raise MediaValidationError({'file': 'Not a valid media file.'})
    try:
        data = json.loads(completed.stdout or b'{}')
    except ValueError:
        raise MediaValidationError({'file': 'Not a valid media file.'})

    fmt = data.get('format') or {}
    streams = data.get('streams') or []
    if not streams:
        raise MediaValidationError({'file': 'Not a valid media file.'})

    # Skip attached-picture streams when picking the video stream: iTunes/ID3
    # cover art on an MP3 reports as an mjpeg/png "video" stream, which would
    # otherwise make an audio upload look like a video (spec: cover art must
    # not block audio uploads).
    video = next(
        (s for s in streams
         if s.get('codec_type') == 'video' and not (s.get('disposition') or {}).get('attached_pic')),
        None,
    )
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
