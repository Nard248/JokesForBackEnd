from rest_framework import serializers


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.RegexField(r'^\d{6}$')


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()
