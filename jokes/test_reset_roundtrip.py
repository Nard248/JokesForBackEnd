"""Full password-reset round-trip: the email link must actually complete a reset.

Guards the uid/token encoding contract between the reset email (built by
FrontendPasswordResetSerializer) and the confirm endpoint that decodes it.
"""
import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordResetRoundTripTest(TestCase):
    def test_email_link_actually_resets_the_password(self):
        User = get_user_model()
        user = User.objects.create_user(
            username='rtuser', email='rt@example.com', password='OldPass123!')
        user.is_active = True
        user.save()

        resp = self.client.post(
            reverse('rest_password_reset'), {'email': 'rt@example.com'},
            content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(mail.outbox), 1)

        body = mail.outbox[0].body
        m = re.search(r'/reset-password\?uid=([^&\s]+)&token=([^\s&]+)', body)
        self.assertIsNotNone(m, f'no frontend reset link in email:\n{body}')
        uid, token = m.group(1), m.group(2)

        confirm = self.client.post(
            reverse('rest_password_reset_confirm'),
            {'uid': uid, 'token': token,
             'new_password1': 'NewPass456!', 'new_password2': 'NewPass456!'},
            content_type='application/json')
        self.assertEqual(confirm.status_code, 200, confirm.content)

        user.refresh_from_db()
        self.assertTrue(user.check_password('NewPass456!'),
                        'password was not actually changed by the reset link')
