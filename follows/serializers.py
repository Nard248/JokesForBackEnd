from rest_framework import serializers

from jokes.identity import public_display_name, public_handle


class PublicUserSerializer(serializers.Serializer):
    """Minimal public user identity — id, display name, @handle, avatar_url. Never exposes email."""
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    def get_name(self, obj):
        return public_display_name(obj)

    def get_username(self, obj):
        return public_handle(obj)

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
