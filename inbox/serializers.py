from rest_framework import serializers

from jokes.identity import public_display_name, public_handle


class NotificationSerializer(serializers.Serializer):
    """Read serializer for an in-app notification. Actor identity via the shared
    helper (never email)."""
    id = serializers.IntegerField()
    verb = serializers.CharField()
    read = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    data = serializers.JSONField()
    actor = serializers.SerializerMethodField()
    joke = serializers.SerializerMethodField()

    def get_actor(self, obj):
        if obj.actor_id is None:
            return None
        return {
            'id': obj.actor_id,
            'name': public_display_name(obj.actor),
            'username': public_handle(obj.actor),
        }

    def get_joke(self, obj):
        if obj.joke_id is None:
            return None
        text = obj.joke.text or ''
        return {'id': obj.joke_id, 'preview': text[:60]}
