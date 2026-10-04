from django.db import migrations

# Frozen copy of communities.styles at the time of this migration.
PALETTE = ['#6A1CF6', '#FF6B4A', '#1FA97A', '#E8A400', '#2F7DF6', '#D6338A', '#7A5AF8', '#0E9AA7']
EMOJI = {
    'animals': '🐾', 'dating': '💘', 'dinner': '🍝', 'family': '🏡', 'food': '🍕',
    'icebreaker': '🧊', 'mondays': '☕', 'money': '💸', 'party': '🎉', 'presentation': '🎤',
    'puns': '🔤', 'school': '🎒', 'science': '🔬', 'social-media': '📱', 'space': '🚀',
    'tech': '💻', 'travel': '✈️', 'weather': '🌦️', 'wedding': '💍', 'work': '💼',
}


def backfill(apps, schema_editor):
    db = schema_editor.connection.alias
    ContextTag = apps.get_model('jokes', 'ContextTag')
    Community = apps.get_model('communities', 'Community')
    existing = set(Community.objects.using(db).values_list('tag_id', flat=True))
    Community.objects.using(db).bulk_create([
        Community(tag=tag, emoji=EMOJI.get(tag.slug, '✨'),
                  color=PALETTE[sum(map(ord, tag.slug)) % len(PALETTE)])
        for tag in ContextTag.objects.using(db).exclude(pk__in=existing)
    ])


class Migration(migrations.Migration):
    dependencies = [('communities', '0001_initial')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
