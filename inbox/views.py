from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inbox.models import Notification
from inbox.serializers import NotificationSerializer

# Shape of one NotificationSerializer row. Declared inline (rather than pointing
# the schema at the serializer) because `actor`/`joke` are SerializerMethodFields
# that return a nested object or None — drf-spectacular would otherwise type them
# as plain strings, which is exactly the kind of wrong-but-compiling contract a
# generated client fails on at runtime.
_NOTIFICATION_SCHEMA = {
    'type': 'object',
    'properties': {
        'id': {'type': 'integer'},
        'verb': {
            'type': 'string',
            'enum': [choice for choice, _ in Notification.VERB_CHOICES],
        },
        'read': {'type': 'boolean'},
        'created_at': {'type': 'string', 'format': 'date-time'},
        # Verb-specific payload; empty object for verbs that carry no extra context.
        'data': {'type': 'object', 'additionalProperties': True},
        'actor': {
            'type': 'object',
            'nullable': True,  # null for system events (moderation)
            'properties': {
                'id': {'type': 'integer'},
                'name': {'type': 'string'},
                'username': {'type': 'string'},
            },
        },
        'joke': {
            'type': 'object',
            'nullable': True,
            'properties': {
                'id': {'type': 'integer'},
                'preview': {'type': 'string', 'description': 'First 60 characters of the joke text.'},
            },
        },
    },
}


class NotificationListView(APIView):
    """GET /notifications/ — the current user's notifications, newest first."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description='Page-number paginated, newest first. Fixed page size of 20.',
        parameters=[
            OpenApiParameter(name='page', type=int, description='1-based page number.'),
        ],
        responses={200: {'type': 'object', 'properties': {
            'count': {'type': 'integer'},
            'next': {'type': 'string', 'format': 'uri', 'nullable': True},
            'previous': {'type': 'string', 'format': 'uri', 'nullable': True},
            'results': {'type': 'array', 'items': _NOTIFICATION_SCHEMA},
        }}},
    )
    def get(self, request):
        qs = (
            Notification.objects.filter(recipient=request.user)
            .select_related('actor', 'joke')
        )
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(NotificationSerializer(page, many=True).data)


class UnreadCountView(APIView):
    """GET /notifications/unread-count/ — badge count."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Number of the caller's unread notifications.",
        responses={200: {'type': 'object', 'properties': {
            'count': {'type': 'integer'},
        }}},
    )
    def get(self, request):
        count = Notification.objects.filter(recipient=request.user, read=False).count()
        return Response({'count': count})


class MarkAllReadView(APIView):
    """POST /notifications/mark-read/ — mark all of the user's notifications read."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description='Marks every unread notification read. Takes no request body.',
        request=None,
        responses={200: {'type': 'object', 'properties': {
            'marked': {'type': 'integer', 'description': 'How many rows were flipped to read.'},
        }}},
    )
    def post(self, request):
        marked = Notification.objects.filter(recipient=request.user, read=False).update(read=True)
        return Response({'marked': marked})
