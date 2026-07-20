"""In-request image processing for media-joke uploads (spec §5.1).

Everything is synchronous and cheap by construction (Pillow on a ≤4096px
source): validate → bake orientation → downscale → re-encode to WebP. The
re-encode is ALSO the EXIF strip — no metadata survives a fresh encode. The
original upload is never stored.
"""
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

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
