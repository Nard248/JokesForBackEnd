"""Default presentation for theme communities. Editable per row in admin."""

PALETTE = ['#6A1CF6', '#FF6B4A', '#1FA97A', '#E8A400', '#2F7DF6', '#D6338A', '#7A5AF8', '#0E9AA7']

EMOJI = {
    'animals': '🐾', 'dating': '💘', 'dinner': '🍝', 'family': '🏡', 'food': '🍕',
    'icebreaker': '🧊', 'mondays': '☕', 'money': '💸', 'party': '🎉', 'presentation': '🎤',
    'puns': '🔤', 'school': '🎒', 'science': '🔬', 'social-media': '📱', 'space': '🚀',
    'tech': '💻', 'travel': '✈️', 'weather': '🌦️', 'wedding': '💍', 'work': '💼',
}


def style_for(slug):
    """Stable emoji/colour for a theme slug (same input, same output)."""
    color = PALETTE[sum(map(ord, slug)) % len(PALETTE)]
    return EMOJI.get(slug, '✨'), color
