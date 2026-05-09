"""Seed the 12 canonical vibes from the design package (parts/flow.jsx VIBES).

Idempotent: re-running the migration updates display fields but leaves
curator-edited filter recipes (formats/themes/categories M2M) untouched.

Filter recipes start empty — curators populate them in admin once the
seed Tones / ContextTags / Formats are in place. The vibe is still functional
without a recipe (it just matches the global joke pool).
"""
from django.db import migrations


VIBES = [
    {'slug': 'office',    'label': 'Office',        'subtitle': 'Meetings · Slack',        'icon': '💼', 'swatch_bg': '#6A1CF6', 'swatch_fg': '#FFFFFF', 'order': 1},
    {'slug': 'dad',       'label': 'Dad jokes',     'subtitle': 'Eye-roll guaranteed',     'icon': '🧓', 'swatch_bg': '#FFC965', 'swatch_fg': '#5F4200', 'order': 2},
    {'slug': 'puns',      'label': 'Puns',          'subtitle': 'Wordplay supreme',        'icon': '🎯', 'swatch_bg': '#CAFD00', 'swatch_fg': '#3A4A00', 'order': 3},
    {'slug': 'dark',      'label': 'Dark humor',    'subtitle': 'Black coffee, no sugar',  'icon': '🌑', 'swatch_bg': '#1A1820', 'swatch_fg': '#FFFFFF', 'order': 4},
    {'slug': 'nerd',      'label': 'Nerd',          'subtitle': 'Physics · code · maths',  'icon': '🧪', 'swatch_bg': '#F2E9FF', 'swatch_fg': '#5D00E4', 'order': 5},
    {'slug': 'surreal',   'label': 'Surreal',       'subtitle': 'Logic optional',          'icon': '🌀', 'swatch_bg': '#AC8EFF', 'swatch_fg': '#FFFFFF', 'order': 6},
    {'slug': 'wholesome', 'label': 'Wholesome',     'subtitle': 'For the group chat',      'icon': '🌼', 'swatch_bg': '#FFE6B5', 'swatch_fg': '#5F4200', 'order': 7},
    {'slug': 'observ',    'label': 'Observational', 'subtitle': 'Adulthood is…',           'icon': '👀', 'swatch_bg': '#FBFAF7', 'swatch_fg': '#1A1A1A', 'order': 8},
    {'slug': 'oneliner',  'label': 'One-liners',    'subtitle': 'Hit, run, save',          'icon': '⚡', 'swatch_bg': '#1A1A1A', 'swatch_fg': '#CAFD00', 'order': 9},
    {'slug': 'date',      'label': 'Date night',    'subtitle': 'Charm a stranger',        'icon': '🍷', 'swatch_bg': '#F4E4D7', 'swatch_fg': '#5F2A14', 'order': 10},
    {'slug': 'kids',      'label': 'Kids OK',       'subtitle': 'School-pickup safe',      'icon': '🧃', 'swatch_bg': '#D6F2FF', 'swatch_fg': '#003B5C', 'order': 11},
    {'slug': 'absurd',    'label': 'Absurd',        'subtitle': 'Mostly fruit',            'icon': '🍌', 'swatch_bg': '#FFC965', 'swatch_fg': '#5F4200', 'order': 12},
]


def seed_vibes(apps, schema_editor):
    Vibe = apps.get_model('jokes', 'Vibe')
    for v in VIBES:
        Vibe.objects.update_or_create(
            slug=v['slug'],
            defaults={k: v[k] for k in ('label', 'subtitle', 'icon', 'swatch_bg', 'swatch_fg', 'order')},
        )


def unseed_vibes(apps, schema_editor):
    Vibe = apps.get_model('jokes', 'Vibe')
    Vibe.objects.filter(slug__in=[v['slug'] for v in VIBES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('jokes', '0012_add_vibes'),
    ]
    operations = [
        migrations.RunPython(seed_vibes, reverse_code=unseed_vibes),
    ]
