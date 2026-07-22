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
