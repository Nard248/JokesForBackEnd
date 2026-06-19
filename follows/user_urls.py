from django.urls import path

from follows.views import MyFollowingView

urlpatterns = [
    path('me/following/', MyFollowingView.as_view(), name='my-following'),
]
