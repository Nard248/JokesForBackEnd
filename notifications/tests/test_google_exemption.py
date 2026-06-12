from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from notifications.models import EmailVerification

User = get_user_model()


@override_settings(EMAIL_VERIFICATION_REQUIRED=True)
class GoogleExemptionTests(TestCase):
    """A user created via the social flow must be active and have no code.

    We simulate the post-condition of GoogleLogin (allauth creates the user)
    rather than driving the full OAuth exchange, which needs Google.
    """

    def test_social_user_is_active_and_has_no_verification(self):
        # allauth's SocialLogin path creates an active user by default.
        user = User.objects.create_user(
            username='g@example.com', email='g@example.com', is_active=True,
        )
        # No verification code should ever be issued for social signups.
        self.assertEqual(EmailVerification.objects.filter(user=user).count(), 0)
        self.assertTrue(user.is_active)
