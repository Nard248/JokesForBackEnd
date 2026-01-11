from django.apps import AppConfig


class JokesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'jokes'

    def ready(self):
        import jokes.signals  # noqa: F401
