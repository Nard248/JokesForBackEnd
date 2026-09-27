"""Keep the earliest legacy exposure before enforcing daily impression identity."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('jokes', '0036_userprofile_creator_milestone_opt_in_and_more')]
    operations = [
        migrations.RunSQL(
            sql='''DELETE FROM jokes_jokeimpression WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY user_id, joke_id, created_date
                        ORDER BY created_at, id
                    ) AS occurrence
                    FROM jokes_jokeimpression
                ) duplicates WHERE occurrence > 1
            )''',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddConstraint(
            model_name='jokeimpression',
            constraint=models.UniqueConstraint(
                fields=('user', 'joke', 'created_date'), name='joke_impression_user_joke_day_uniq',
            ),
        ),
    ]
