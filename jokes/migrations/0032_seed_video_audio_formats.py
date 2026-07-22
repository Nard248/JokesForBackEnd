from django.db import migrations


def seed_video_audio_formats(apps, schema_editor):
    Format = apps.get_model('jokes', 'Format')
    Format.objects.update_or_create(
        slug='video',
        defaults={
            'name': 'Video',
            'description': 'A setup caption with a short video clip as the punchline.',
        },
    )
    Format.objects.update_or_create(
        slug='audio',
        defaults={
            'name': 'Audio',
            'description': 'A setup caption with a short audio clip as the punchline.',
        },
    )


def unseed_video_audio_formats(apps, schema_editor):
    Format = apps.get_model('jokes', 'Format')
    Format.objects.filter(slug__in=['video', 'audio'], jokes__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('jokes', '0031_seed_image_format'),
    ]
    operations = [
        migrations.RunPython(seed_video_audio_formats, unseed_video_audio_formats),
    ]
