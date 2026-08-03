"""Share card generation using SVG templates and CairoSVG."""
import base64
import io
import logging

import cairosvg
from django.template.loader import render_to_string
from PIL import Image

logger = logging.getLogger(__name__)

MEDIA_CARD_TEMPLATE = 'jokes/share_cards/media_card.svg'
MAX_RASTER_WIDTH = 1200

# Tone slug to template mapping
TONE_TEMPLATES = {
    'dad-jokes': 'jokes/share_cards/dad_joke.svg',
    'dark': 'jokes/share_cards/dark_humor.svg',
    'puns': 'jokes/share_cards/pun.svg',
}
DEFAULT_TEMPLATE = 'jokes/share_cards/base_card.svg'


def get_template_for_joke(joke):
    """Get the appropriate SVG template based on joke's primary tone."""
    tone = joke.tones.first()
    if tone:
        return TONE_TEMPLATES.get(tone.slug, DEFAULT_TEMPLATE)
    return DEFAULT_TEMPLATE


def get_badge_text(joke):
    """Get badge text based on joke's primary tone.

    Audio-format jokes always get the 'Audio' badge in place of the tone
    badge: audio has no visual to embed (media_share_card_png declines), so
    it renders via the text-card path, and the spec calls for that card's
    badge to read 'Audio' rather than the joke's tone."""
    if joke.format_id and joke.format.slug == 'audio':
        return 'Audio'
    tone = joke.tones.first()
    return tone.name if tone else 'Joke'


def _downscale_raster(raw_bytes):
    """Downscale a raw raster (webp/jpeg/png/...) to a JPEG no wider than
    MAX_RASTER_WIDTH, for embedding in a share-card SVG as a base64 data
    URI. Never upscales. Returns JPEG bytes."""
    img = Image.open(io.BytesIO(raw_bytes))
    img = img.convert('RGB')
    img.thumbnail((MAX_RASTER_WIDTH, MAX_RASTER_WIDTH * 10))
    out = io.BytesIO()
    img.save(out, format='JPEG', quality=82)
    return out.getvalue()


def _primary_media_raster(joke):
    """Return (raw_bytes, asset) for the joke's primary (position 0) media
    asset, or (None, None) if there's no usable raster to embed.

    image kind -> the display derivative (asset.file). video/GIF kind
    (asset.kind == 'video') -> asset.poster, the SafeSearch-screened teaser
    frame -- the raw video file (asset.file) is NEVER read here. audio, or a
    video/GIF asset whose poster hasn't been generated yet -> no raster;
    caller falls back to the text card."""
    link = joke.media.first()
    if link is None:
        return None, None
    asset = link.asset
    if asset.kind == 'image':
        if not asset.file:
            return None, None
        with asset.file.open('rb') as fh:
            return fh.read(), asset
    if asset.kind == 'video':
        if not asset.poster:
            return None, None
        with asset.poster.open('rb') as fh:
            return fh.read(), asset
    return None, None


def _format_badge_for_asset(asset):
    if asset.kind == 'video':
        return 'GIF' if asset.is_gif else '▶ Video'
    return 'Photo'


def media_share_card_png(joke):
    """
    Generate a media share card PNG embedding the joke's primary media
    asset's screened raster (image derivative, or video/GIF poster) as a
    base64 data URI, composited with the caption, brand stripe, and a
    format badge.

    Returns None (caller falls back to the text card) when the joke has no
    usable raster: audio jokes, jokes with no media, or a video/GIF asset
    whose poster hasn't been generated yet. Also returns None -- fail open,
    never propagating -- if the raster is corrupt/unreadable or rasterizing
    the SVG otherwise blows up: a bad embed must never 500 Joke.save() (same
    fail-open policy as media_screening.screen_image, commit 77e995a).
    """
    try:
        raw_bytes, asset = _primary_media_raster(joke)
        if raw_bytes is None:
            return None

        jpeg_bytes = _downscale_raster(raw_bytes)
        data_uri = 'data:image/jpeg;base64,' + base64.b64encode(jpeg_bytes).decode('ascii')

        svg_content = render_to_string(MEDIA_CARD_TEMPLATE, {
            'raster_data_uri': data_uri,
            'joke_text': joke.text,
            'badge_text': _format_badge_for_asset(asset),
        })

        png_buffer = io.BytesIO()
        cairosvg.svg2png(
            bytestring=svg_content.encode('utf-8'),
            write_to=png_buffer,
            output_width=1200,
            output_height=630,
        )
        png_buffer.seek(0)
        return png_buffer
    except Exception as exc:
        logger.warning(
            'media_share_card_png failed for joke %s; falling back to text card: %s',
            joke.pk, str(exc)[:300],
        )
        return None


def generate_share_card_png(joke):
    """
    Generate share card PNG for a joke.

    Dispatches to a media card (embedded poster/image raster) for
    image/video/GIF jokes that have a primary media asset with a usable
    raster; everything else (text jokes, audio, no media, or a video/GIF
    asset with no poster yet) falls through to the existing text card,
    UNCHANGED.

    Returns BytesIO buffer containing PNG data.
    """
    media_png = media_share_card_png(joke)
    if media_png is not None:
        return media_png

    template_name = get_template_for_joke(joke)
    badge_text = get_badge_text(joke)

    # Render SVG with joke data
    svg_content = render_to_string(template_name, {
        'joke_text': joke.text,
        'badge_text': badge_text,
    })

    # Convert to PNG
    png_buffer = io.BytesIO()
    cairosvg.svg2png(
        bytestring=svg_content.encode('utf-8'),
        write_to=png_buffer,
        output_width=1200,
        output_height=630
    )
    png_buffer.seek(0)
    return png_buffer
