from rest_framework import serializers


class PublicUserSerializer(serializers.Serializer):
    """Minimal public user identity — id, display name, @handle, avatar_url. Never exposes email."""
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    def get_name(self, obj):
        # Never derive public identifiers from email (PII / enumeration). Use the
        # user's name if set, else an opaque id. A real user-chosen handle field
        # on UserProfile is the proper long-term fix (tracked as a follow-up).
        full = f'{obj.first_name} {obj.last_name}'.strip()
        return full if full else f'user_{obj.pk}'

    def get_username(self, obj):
        return f'@user{obj.pk}'

    def get_avatar_url(self, obj):
        try:
            avatar = obj.profile.avatar
            if avatar:
                request = self.context.get('request')
                if request:
                    return request.build_absolute_uri(avatar.url)
                return avatar.url
        except Exception:
            pass
        return None


class FollowStatusSerializer(serializers.Serializer):
    is_following = serializers.BooleanField()
    follower_count = serializers.IntegerField()
