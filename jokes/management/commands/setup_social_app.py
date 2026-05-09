"""
Idempotent provisioning of the Site row and the Google OAuth SocialApp.

Run on every deploy — reconciles DB state with env vars so credential
rotation only requires updating .env and re-running this command.
"""
import os

from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create or update the default Site and the Google OAuth SocialApp from environment variables."

    def handle(self, *args, **options):
        client_id = os.getenv('GOOGLE_CLIENT_ID', '').strip()
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET', '').strip()
        site_domain = os.getenv('SITE_DOMAIN', 'localhost:8000').strip()
        site_name = os.getenv('SITE_NAME', site_domain).strip()

        if not client_id or not client_secret:
            raise CommandError(
                'GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in the environment.'
            )

        site, site_created = Site.objects.update_or_create(
            id=1,
            defaults={'domain': site_domain, 'name': site_name},
        )
        self.stdout.write(
            self.style.SUCCESS(f"Site {'created' if site_created else 'updated'}: {site.domain}")
        )

        app, app_created = SocialApp.objects.update_or_create(
            provider='google',
            defaults={
                'name': 'Google',
                'client_id': client_id,
                'secret': client_secret,
                'key': '',
            },
        )
        # Sites are M2M on SocialApp — set() handles both add and orphan removal.
        app.sites.set([site])
        self.stdout.write(
            self.style.SUCCESS(
                f"SocialApp 'google' {'created' if app_created else 'updated'} "
                f"(client_id={client_id[:20]}…) bound to site '{site.domain}'."
            )
        )
