from django.core.exceptions import ValidationError

from follows.models import Follow


def follow(follower, creator):
    """Follow creator. Raises ValidationError on self-follow. Returns (follow, created)."""
    if follower.pk == creator.pk:
        raise ValidationError('You cannot follow yourself.')
    return Follow.objects.get_or_create(follower=follower, creator=creator)


def unfollow(follower, creator):
    """Unfollow creator. Idempotent."""
    Follow.objects.filter(follower=follower, creator=creator).delete()


def follower_count(creator):
    """Return the number of followers for creator."""
    return Follow.objects.filter(creator=creator).count()


def following_count(user):
    """Return the number of creators user follows."""
    return Follow.objects.filter(follower=user).count()


def is_following(follower, creator):
    """Return True if follower follows creator."""
    return Follow.objects.filter(follower=follower, creator=creator).exists()
