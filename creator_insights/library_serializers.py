"""Strict inputs: private work cannot smuggle public content or ownership edits."""
from rest_framework import serializers

from creator_insights.models import CreatorCollection, CreatorMetadataRequest, CreatorWorkspaceNote
from jokes.models import ContextTag, Tone


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError(dict.fromkeys(sorted(unknown), 'Unknown field.'))
        return super().to_internal_value(data)


class NoteWriteSerializer(StrictSerializer):
    private_note = serializers.CharField(max_length=5000, allow_blank=True, trim_whitespace=False)


class NoteSerializer(serializers.ModelSerializer):
    joke_id = serializers.IntegerField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = CreatorWorkspaceNote
        fields = ['joke_id', 'private_note', 'updated_at']


class UniqueIDsField(serializers.ListField):
    child = serializers.IntegerField(min_value=1)

    def to_internal_value(self, data):
        values = super().to_internal_value(data)
        if len(set(values)) != len(values):
            raise serializers.ValidationError('Duplicate joke IDs are not allowed.')
        return values


class CollectionWriteSerializer(StrictSerializer):
    name = serializers.CharField(max_length=100)
    kind = serializers.ChoiceField(choices=CreatorCollection.Kind.choices)
    description = serializers.CharField(max_length=1000, allow_blank=True, required=False, trim_whitespace=False)
    joke_ids = UniqueIDsField(max_length=100, allow_empty=True, required=False)


class CollectionItemSerializer(serializers.Serializer):
    joke_id = serializers.IntegerField()
    display_text = serializers.CharField(max_length=180)


class CollectionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=CreatorCollection.Kind.choices)
    description = serializers.CharField()
    joke_ids = serializers.ListField(child=serializers.IntegerField())
    items = CollectionItemSerializer(many=True)
    unavailable_count = serializers.IntegerField()
    updated_at = serializers.DateTimeField()


class MetadataRequestWriteSerializer(StrictSerializer):
    joke_ids = UniqueIDsField(min_length=1, max_length=50)
    themes = serializers.ListField(child=serializers.SlugField(max_length=100), max_length=30, required=False)
    categories = serializers.ListField(child=serializers.SlugField(max_length=50), max_length=30, required=False)
    reason = serializers.CharField(max_length=1000, allow_blank=True, required=False)

    def validate(self, data):
        if not any(key in data for key in ('themes', 'categories')):
            raise serializers.ValidationError('Provide themes or categories to request a change.')
        for key, model in [('themes', ContextTag), ('categories', Tone)]:
            if key not in data:
                continue
            values = data[key]
            if len(set(values)) != len(values):
                raise serializers.ValidationError({key: 'Duplicate tags are not allowed.'})
            if model.objects.filter(slug__in=values).count() != len(values):
                raise serializers.ValidationError({key: 'One or more tags were not found.'})
        return data


class MetadataRequestSerializer(serializers.ModelSerializer):
    joke_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = CreatorMetadataRequest
        fields = ['id', 'joke_id', 'changes', 'reason', 'status', 'decision_reason', 'created_at', 'reviewed_at']
