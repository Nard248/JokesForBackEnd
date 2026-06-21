from django.urls import path

from inbox import views

urlpatterns = [
    path('', views.NotificationListView.as_view(), name='notification-list'),
    path('unread-count/', views.UnreadCountView.as_view(), name='notification-unread-count'),
    path('mark-read/', views.MarkAllReadView.as_view(), name='notification-mark-read'),
]
