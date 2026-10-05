"""Seed initial country/culture associations; content is imported separately."""
from django.db import migrations


LOCALES = [
    ('es', 'Spanish', 'Español', 'ES', 'Spain', 'España',
     'spain-everyday', 'Everyday Spain', 'Vida cotidiana en España',
     'Original Spanish drafts prepared for the Spain-focused everyday collection. Many scenes are general rather than country-specific; no native review is claimed.'),
    ('fr', 'French', 'Français', 'FR', 'France', 'France',
     'france-everyday', 'Everyday France', 'Le quotidien en France',
     'Original French drafts prepared for the France-focused everyday collection. Many scenes are general rather than country-specific; no native review is claimed.'),
    ('de', 'German', 'Deutsch', 'DE', 'Germany', 'Deutschland',
     'germany-everyday', 'Everyday Germany', 'Alltag in Deutschland',
     'Original German drafts prepared for the Germany-focused everyday collection. Many scenes are general rather than country-specific; no native review is claimed.'),
    ('hy', 'Armenian', 'Հայերեն', 'AM', 'Armenia', 'Հայաստան',
     'armenia-everyday', 'Everyday Armenia', 'Առօրյան Հայաստանում',
     'Original Eastern Armenian drafts prepared for the Armenia-focused everyday collection. Many scenes are general rather than country-specific; no native review is claimed.'),
    ('it', 'Italian', 'Italiano', 'IT', 'Italy', 'Italia',
     'italy-everyday', 'Everyday Italy', 'Vita quotidiana in Italia',
     'Original standard Italian drafts prepared for the Italy-focused everyday collection. Many scenes are general rather than country-specific; no native review is claimed.'),
]


def seed_locales(apps, schema_editor):
    Language = apps.get_model('jokes', 'Language')
    Country = apps.get_model('jokes', 'Country')
    CultureTag = apps.get_model('jokes', 'CultureTag')
    for code, name, native, country_code, country_name, country_native, slug, label, native_label, description in LOCALES:
        language, _ = Language.objects.get_or_create(
            code=code, defaults={'name': name, 'native_name': native},
        )
        country, _ = Country.objects.get_or_create(
            code=country_code, defaults={'name': country_name, 'native_name': country_native},
        )
        culture, _ = CultureTag.objects.get_or_create(
            slug=slug, defaults={'name': label, 'native_name': native_label, 'description': description},
        )
        culture.languages.add(language)
        culture.countries.add(country)


class Migration(migrations.Migration):
    dependencies = [('jokes', '0039_international_discovery')]
    operations = [migrations.RunPython(seed_locales, migrations.RunPython.noop)]
