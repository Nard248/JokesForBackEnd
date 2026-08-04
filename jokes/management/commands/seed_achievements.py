from django.core.management.base import BaseCommand

from jokes.models import Achievement

ACHIEVEMENTS = [
    {
        'slug': 'first_save',
        'title': 'First Save',
        'description': 'Saved your first joke',
        'icon': 'bookmark',
        'criteria_type': 'save_count',
        'criteria_value': 1,
    },
    {
        'slug': 'collector_10',
        'title': 'Joke Collector',
        'description': 'Saved 10 jokes to your library',
        'icon': 'library',
        'criteria_type': 'save_count',
        'criteria_value': 10,
    },
    {
        'slug': 'collector_50',
        'title': 'Joke Hoarder',
        'description': 'Saved 50 jokes to your library',
        'icon': 'archive',
        'criteria_type': 'save_count',
        'criteria_value': 50,
    },
    {
        'slug': 'first_favorite',
        'title': 'First Favorite',
        'description': 'Favorited your first joke',
        'icon': 'heart',
        'criteria_type': 'favorite_count',
        'criteria_value': 1,
    },
    {
        'slug': 'first_share',
        'title': 'Spread the Laughs',
        'description': 'Shared your first joke',
        'icon': 'share',
        'criteria_type': 'share_count',
        'criteria_value': 1,
    },
    {
        'slug': 'sharer_10',
        'title': 'Joy Spreader',
        'description': 'Shared 10 jokes with the world',
        'icon': 'megaphone',
        'criteria_type': 'share_count',
        'criteria_value': 10,
    },
    {
        'slug': 'first_rating',
        'title': 'Critic',
        'description': 'Rated your first joke',
        'icon': 'thumbs-up',
        'criteria_type': 'rating_count',
        'criteria_value': 1,
    },
    {
        'slug': 'rater_50',
        'title': 'Comedy Judge',
        'description': 'Rated 50 jokes',
        'icon': 'gavel',
        'criteria_type': 'rating_count',
        'criteria_value': 50,
    },
    {
        'slug': 'streak_7',
        'title': 'Week Warrior',
        'description': 'Visited 7 days in a row',
        'icon': 'flame',
        'criteria_type': 'streak_days',
        'criteria_value': 7,
    },
    {
        'slug': 'streak_30',
        'title': '30-Day Streak',
        'description': 'Visited 30 days in a row',
        'icon': 'diamond',
        'criteria_type': 'streak_days',
        'criteria_value': 30,
    },
    {
        'slug': 'first_submission',
        'title': 'Aspiring Comedian',
        'description': 'Submitted your first joke',
        'icon': 'pen-tool',
        'criteria_type': 'submission_count',
        'criteria_value': 1,
    },
    {
        'slug': 'published_joke',
        'title': 'Published!',
        'description': 'Had a joke published on the platform',
        'icon': 'star',
        'criteria_type': 'published_count',
        'criteria_value': 1,
    },
]


class Command(BaseCommand):
    help = 'Seed achievement definitions'

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for data in ACHIEVEMENTS:
            _, created = Achievement.objects.update_or_create(
                slug=data['slug'],
                defaults={k: v for k, v in data.items() if k != 'slug'},
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Achievements: {created_count} created, {updated_count} updated'
            )
        )
