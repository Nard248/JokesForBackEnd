from django.apps import AppConfig


class CommunitiesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'communities'
    verbose_name = 'Communities'

    def ready(self):
        from communities import signals  # noqa: F401
