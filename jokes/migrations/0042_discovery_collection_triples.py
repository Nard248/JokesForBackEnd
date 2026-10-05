"""Represent actual supported collections without inventing Cartesian combinations."""
import django.db.models.deletion
from django.db import migrations, models


INITIAL_COLLECTIONS = [
    ('es-es-everyday', 'es', 'ES', 'spain-everyday'),
    ('fr-fr-everyday', 'fr', 'FR', 'france-everyday'),
    ('de-de-everyday', 'de', 'DE', 'germany-everyday'),
    ('hy-am-everyday', 'hy', 'AM', 'armenia-everyday'),
    ('it-it-everyday', 'it', 'IT', 'italy-everyday'),
]


def seed_collections(apps, schema_editor):
    Collection = apps.get_model('jokes', 'CulturalCollection')
    Language = apps.get_model('jokes', 'Language')
    Country = apps.get_model('jokes', 'Country')
    Culture = apps.get_model('jokes', 'CultureTag')
    alias = schema_editor.connection.alias
    for slug, language, country, culture in INITIAL_COLLECTIONS:
        Collection.objects.using(alias).get_or_create(
            slug=slug,
            defaults={
                'language': Language.objects.using(alias).get(code=language),
                'country': Country.objects.using(alias).get(code=country),
                'culture': Culture.objects.using(alias).get(slug=culture),
            },
        )


class Migration(migrations.Migration):
    dependencies = [('jokes', '0041_unified_joke_search')]
    operations = [
        migrations.CreateModel(
            name='CulturalCollection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(max_length=100, unique=True)),
                ('country', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cultural_collections', to='jokes.country')),
                ('culture', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cultural_collections', to='jokes.culturetag')),
                ('language', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cultural_collections', to='jokes.language')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('language', 'country', 'culture'), name='uniq_cultural_collection_context')],
            },
        ),
        migrations.RunPython(seed_collections, migrations.RunPython.noop),
    ]
