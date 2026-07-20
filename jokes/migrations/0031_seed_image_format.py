from django.db import migrations


def seed_image_format(apps, schema_editor):
    Format = apps.get_model('jokes', 'Format')
    Format.objects.update_or_create(
        slug='image',
        defaults={
            'name': 'Image',
            'description': 'A setup caption with an image (or up to six) as the punchline.',
        },
    )


def unseed_image_format(apps, schema_editor):
    Format = apps.get_model('jokes', 'Format')
    Format.objects.filter(slug='image', jokes__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('jokes', '0030_mediaasset_jokesubmissionmedia_jokemedia'),
    ]
    operations = [
        migrations.RunPython(seed_image_format, unseed_image_format),
    ]
