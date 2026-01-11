"""
Custom serializers for authentication.
"""
from django.contrib.auth import get_user_model
from rest_framework import serializers

from allauth.account.adapter import get_adapter
from allauth.account.utils import setup_user_email


User = get_user_model()


class EmailOnlyRegisterSerializer(serializers.Serializer):
    """
    Registration serializer for email-only authentication.

    Does not require username - uses email as the primary identifier.
    """
    email = serializers.EmailField(required=True)
    password1 = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)

    def validate_email(self, email):
        email = get_adapter().clean_email(email)
        # Check if email already exists
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                'A user is already registered with this e-mail address.'
            )
        return email

    def validate_password1(self, password):
        return get_adapter().clean_password(password)

    def validate(self, data):
        if data['password1'] != data['password2']:
            raise serializers.ValidationError({
                'password2': "The two password fields didn't match."
            })
        return data

    def get_cleaned_data(self):
        return {
            'email': self.validated_data.get('email', ''),
            'password1': self.validated_data.get('password1', ''),
        }

    def save(self, request):
        adapter = get_adapter()
        user = adapter.new_user(request)
        self.cleaned_data = self.get_cleaned_data()

        # Set email as username (allauth expects this for email-only)
        user.email = self.cleaned_data['email']
        user.username = self.cleaned_data['email']  # Use email as username
        user.set_password(self.cleaned_data['password1'])
        user.save()

        setup_user_email(request, user, [])
        return user
