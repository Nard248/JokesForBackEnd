"""The population eligible to contribute to creator analytics."""
from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.utils import timezone


def eligible_analytics_users():
    return get_user_model().objects.filter(
        is_active=True,
        profile__share_analytics=True,
        profile__date_of_birth__lte=timezone.now().date() - relativedelta(years=18),
    )


def analytics_allowed(user):
    if not user or not user.is_authenticated:
        return False
    return eligible_analytics_users().filter(pk=user.pk).exists()
