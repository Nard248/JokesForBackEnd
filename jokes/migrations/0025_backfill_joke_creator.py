from django.db import migrations


def forward(apps, schema_editor):
    Joke = apps.get_model('jokes', 'Joke')
    Sub = apps.get_model('jokes', 'JokeSubmission')
    qs = Sub.objects.filter(
        status='published',
        published_joke__isnull=False,
        published_joke__creator__isnull=True,
    ).iterator()
    for s in qs:
        Joke.objects.filter(pk=s.published_joke_id).update(creator_id=s.user_id)


def reverse(apps, schema_editor):
    apps.get_model('jokes', 'Joke').objects.update(creator=None)


class Migration(migrations.Migration):

    dependencies = [
        ('jokes', '0024_joke_creator_fk'),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
