"""
Custom serializers for authentication.
"""
from allauth.account.adapter import get_adapter
from allauth.account.utils import setup_user_email
from dj_rest_auth.serializers import UserDetailsSerializer
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

User = get_user_model()


class JokesForUserDetailsSerializer(UserDetailsSerializer):
    """
    Extends dj-rest-auth's UserDetailsSerializer to expose the user's own
    date_of_birth from their UserProfile.

    GDPR Article 15 grants users the right to access their own personal data,
    so returning the authenticated user their own DOB is both legal and required.
    The frontend uses this field to gate consent-analytics for adults.
    """

    date_of_birth = serializers.DateField(
        source='profile.date_of_birth',
        read_only=True,
        allow_null=True,
    )

    class Meta(UserDetailsSerializer.Meta):
        fields = UserDetailsSerializer.Meta.fields + ('date_of_birth',)


class EmailOnlyRegisterSerializer(serializers.Serializer):
    """
    Registration serializer for email-only authentication.

    Does not require username - uses email as the primary identifier.
    Requires date_of_birth; blocks registrations for users under 13.
    """
    email = serializers.EmailField(required=True)
    password1 = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)
    date_of_birth = serializers.DateField(required=True, write_only=True)

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

    def validate_date_of_birth(self, value):
        today = timezone.now().date()
        if value >= today:
            raise serializers.ValidationError('Enter a valid date of birth.')
        years = today.year - value.year - (
            1 if (today.month, today.day) < (value.month, value.day) else 0
        )
        if years < 13:
            raise serializers.ValidationError(
                'You must be at least 13 years old to use Jokes For.'
            )
        return value

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
            'date_of_birth': self.validated_data.get('date_of_birth'),
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

        # Persist DOB onto the signal-created profile
        profile = user.profile
        profile.date_of_birth = self.cleaned_data['date_of_birth']
        profile.save(update_fields=['date_of_birth', 'updated_at'])

        setup_user_email(request, user, [])
        return user
