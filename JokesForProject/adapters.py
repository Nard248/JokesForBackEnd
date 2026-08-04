"""
Custom allauth adapters.

SocialAccountAdapter enforces the COPPA age gate on the Google OAuth signup
path. The email/password signup path collects and validates ``date_of_birth``
in ``JokesForProject.serializers.EmailOnlyRegisterSerializer`` and rejects
under-13 users. Without this adapter the Google path (a bare SocialLoginView)
would auto-create a live account with ``date_of_birth = NULL``, letting a child
under 13 bypass the gate via "Continue with Google".

The gate runs in ``pre_social_login`` (invoked by allauth *after*
``sociallogin.lookup()`` and *before* any user / social account row is
committed) so a rejection creates no rows. ``save_user`` persists the validated
DOB to the same place the email path stores it: ``user.profile.date_of_birth``.
"""
from datetime import date

from allauth.account.utils import user_email
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.exceptions import APIException

# The raw DOB string is stashed on the underlying Django HttpRequest by the
# GoogleLogin view (see jokes/views.py) because allauth hands the adapter the
# unwrapped request, whose .POST is empty for a JSON body.
DOB_REQUEST_ATTR = 'jokesfor_dob_raw'

# Mirrors EmailOnlyRegisterSerializer.validate_date_of_birth exactly.
MIN_AGE = 13
UNDER_MIN_AGE_MESSAGE = 'You must be at least 13 years old to use Jokes For.'
INVALID_DOB_MESSAGE = 'Enter a valid date of birth.'
DOB_REQUIRED_CODE = 'dob_required'
DOB_REQUIRED_MESSAGE = 'Date of birth is required to continue.'


class DateOfBirthRequired(APIException):
    """400 with a stable machine code the frontend keys on to prompt for DOB.

    Raised (rather than a DRF ValidationError) so the body stays a flat
    ``{"code": "dob_required", "detail": "..."}`` instead of being wrapped into
    serializer field-error lists.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = {'code': DOB_REQUIRED_CODE, 'detail': DOB_REQUIRED_MESSAGE}
    default_code = DOB_REQUIRED_CODE


def _validate_dob(raw):
    """Parse + validate an ISO ``yyyy-mm-dd`` DOB the same way the email path
    does. Returns a ``date`` or raises ``drf.ValidationError``.

    - missing/blank -> ``{"code": "dob_required", ...}`` (machine-detectable)
    - unparseable / future -> ``Enter a valid date of birth.``
    - age < 13 -> the same field-scoped under-13 error the email path returns.
    """
    if raw in (None, ''):
        raise DateOfBirthRequired()

    if isinstance(raw, date):
        value = raw
    else:
        try:
            value = date.fromisoformat(str(raw))
        except (ValueError, TypeError):
            raise drf_serializers.ValidationError({'date_of_birth': [INVALID_DOB_MESSAGE]})

    today = timezone.now().date()
    if value >= today:
        raise drf_serializers.ValidationError({'date_of_birth': [INVALID_DOB_MESSAGE]})

    years = today.year - value.year - (
        1 if (today.month, today.day) < (value.month, value.day) else 0
    )
    if years < MIN_AGE:
        raise drf_serializers.ValidationError({'date_of_birth': [UNDER_MIN_AGE_MESSAGE]})

    return value


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Enforces the COPPA age gate on new Google signups."""

    def pre_social_login(self, request, sociallogin):
        # Case 1: an already-linked social account, OR a local account that
        # already exists for this verified email. Either way this is not a new
        # signup: log in normally, require no DOB, leave any existing DOB
        # untouched. allauth has already run sociallogin.lookup() at this point.
        if sociallogin.is_existing:
            return super().pre_social_login(request, sociallogin)

        email = user_email(sociallogin.user)
        if email and get_user_model().objects.filter(email__iexact=email).exists():
            # A matching local account exists (e.g. registered via the email
            # path). Not a new account -> no DOB gate; allauth / dj-rest-auth
            # own the linking / email-conflict response.
            return super().pre_social_login(request, sociallogin)

        # Cases 2-4: brand-new user. Enforce the gate BEFORE any row commits.
        raw = getattr(request, DOB_REQUEST_ATTR, None)
        dob = _validate_dob(raw)
        # Stash the parsed DOB for save_user (same request object throughout).
        setattr(request, DOB_REQUEST_ATTR + '_parsed', dob)
        return super().pre_social_login(request, sociallogin)

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form=form)
        dob = getattr(request, DOB_REQUEST_ATTR + '_parsed', None)
        if dob is not None:
            # Persist to the same place the email path stores it.
            profile = user.profile
            profile.date_of_birth = dob
            profile.save(update_fields=['date_of_birth', 'updated_at'])
        return user
