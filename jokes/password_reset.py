"""Custom password-reset serializer that emails a FRONTEND link.

dj-rest-auth's default ``AllAuthPasswordResetForm`` builds the reset link with
``default_url_generator``, which calls ``reverse('password_reset_confirm', ...)``
— a URL name this project never registers (only ``rest_password_reset_confirm``
exists). That raises ``NoReverseMatch`` before any email renders, so password
recovery is 100% broken.

We override ``get_email_options()`` to inject a custom ``url_generator`` that
points at the SPA's reset route instead. The allauth email template
(``account/email/password_reset_key_message.txt``) renders ``{{ password_reset_url }}``,
so the emailed link becomes the frontend URL with no reverse() involved.

The frontend (jokes-for-frontend ForgotPasswordPage) reads ``uid`` and ``token``
query params at ``/reset-password`` — matched exactly below.
"""
from django.conf import settings

from allauth.account.utils import user_pk_to_url_str
from dj_rest_auth.serializers import (
    PasswordResetSerializer as BasePasswordResetSerializer,
)


def frontend_reset_url_generator(request, user, temp_key):
    """Build ``<FRONTEND_URL>/reset-password?uid=<uidb64>&token=<token>``.

    Signature matches dj-rest-auth's ``default_url_generator`` so it can be
    dropped in via the form's ``url_generator`` kwarg.
    """
    uid = user_pk_to_url_str(user)
    base = settings.FRONTEND_URL.rstrip('/')
    return f"{base}/reset-password?uid={uid}&token={temp_key}"


class FrontendPasswordResetSerializer(BasePasswordResetSerializer):
    """PasswordResetSerializer that emails an absolute frontend reset link."""

    def get_email_options(self):
        return {'url_generator': frontend_reset_url_generator}
