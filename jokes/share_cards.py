"""Share card generation using SVG templates and CairoSVG."""
import io

import cairosvg
from django.template.loader import render_to_string


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
    """Get badge text based on joke's primary tone."""
    tone = joke.tones.first()
    return tone.name if tone else 'Joke'


def generate_share_card_png(joke):
    """
    Generate share card PNG for a joke.

    Returns BytesIO buffer containing PNG data.
    """
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
