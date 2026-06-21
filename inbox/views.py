from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inbox.models import Notification
from inbox.serializers import NotificationSerializer


class NotificationListView(APIView):
    """GET /notifications/ — the current user's notifications, newest first."""
    permission_classes = [IsAuthenticated]

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

    def get(self, request):
        count = Notification.objects.filter(recipient=request.user, read=False).count()
        return Response({'count': count})


class MarkAllReadView(APIView):
    """POST /notifications/mark-read/ — mark all of the user's notifications read."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        marked = Notification.objects.filter(recipient=request.user, read=False).update(read=True)
        return Response({'marked': marked})
