from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from dj_rest_auth.jwt_auth import set_jwt_cookies

from . import verification
from .serializers import VerifyEmailSerializer, ResendVerificationSerializer
from .throttles import ResendThrottle

User = get_user_model()

# Maps verify_code() error strings to user-facing field errors.
_VERIFY_ERRORS = {
    'no_active_code': ('code', 'No active code. Request a new one.'),
    'expired': ('code', 'This code has expired. Request a new one.'),
    'too_many_attempts': ('code', 'Too many attempts. Request a new code.'),
    'incorrect': ('code', 'Incorrect code.'),
}


class VerifyEmailView(APIView):
    """POST /auth/verify-email/ {email, code} -> activate user + set JWT cookies."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        code = serializer.validated_data['code']

        # Uniform 400 on unknown email (anti-enumeration: same shape as wrong code).
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return Response({'code': ['Incorrect code.']},
                            status=status.HTTP_400_BAD_REQUEST)

        ok, err = verification.verify_code(user, code)
        if not ok:
            field, msg = _VERIFY_ERRORS[err]
            return Response({field: [msg]}, status=status.HTTP_400_BAD_REQUEST)

        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        response = Response(
            {'user': {'id': user.id, 'email': user.email}},
            status=status.HTTP_200_OK,
        )
        set_jwt_cookies(response, access, refresh)
        return response


class ResendVerificationView(APIView):
    """POST /auth/resend-verification/ {email} -> new code if the account exists."""

    permission_classes = [AllowAny]
    throttle_classes = [ResendThrottle]

    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        # Only send for an existing, not-yet-active account. Always return the
        # same response (anti-enumeration).
        user = User.objects.filter(email__iexact=email, is_active=False).first()
        if user is not None:
            verification.issue_and_send(user)

        return Response(
            {'detail': 'If that email needs verification, a new code has been sent.'},
            status=status.HTTP_200_OK,
        )
