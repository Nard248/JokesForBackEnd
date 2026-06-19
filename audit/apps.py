"""Audit app configuration.

ready() connects Django auth signal receivers with function-local imports so
migrations, drf-spectacular, and fresh-DB startups don't hit unresolved tables.
"""
from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'audit'
    verbose_name = 'Audit Log'

    def ready(self):
        # Connect signal receivers
        from audit.signals import register_receivers
        register_receivers()
