"""Removing a joke must go through the takedown path, not a raw admin tick.

`is_removed` was an editable field on JokeAdmin. Ticking it hid the joke with
no statement-of-reasons notification, no media quarantine and no share-card
blanking, and left `removed_at` NULL -- so the creator's later appeal was
refused with "This removal is not eligible for appeal." A moderator taking the
obvious admin action silently stripped the creator's DSA appeal right.

The takedown action (ContentReportAdmin.take_down_joke) does all of that
correctly; the field just must not offer a way around it.
"""
from django.contrib.admin.sites import AdminSite
from django.test import TestCase

from jokes.admin import JokeAdmin
from jokes.models import Joke


class IsRemovedIsNotDirectlyEditableTests(TestCase):
    def setUp(self):
        self.admin = JokeAdmin(Joke, AdminSite())

    def test_is_removed_is_read_only_in_the_admin_form(self):
        readonly = self.admin.get_readonly_fields(request=None)
        self.assertIn(
            'is_removed', readonly,
            'ticking is_removed by hand bypasses the DSA notice + appeal right',
        )

    def test_removed_at_stays_read_only_too(self):
        self.assertIn('removed_at', self.admin.get_readonly_fields(request=None))

    def test_the_restore_action_is_still_available(self):
        """Read-only must not remove the supported way back."""
        self.assertIn('restore_jokes', self.admin.actions)
