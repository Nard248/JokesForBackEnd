from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_preference(sender, instance, created, **kwargs):
    """Auto-create UserPreference when a new User is created."""
    if created:
        from .models import UserPreference
        UserPreference.objects.create(user=instance)
