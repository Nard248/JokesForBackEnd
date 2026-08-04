from django.urls import path

from billing.views import MyTipsView
from follows.views import MyFollowingView

urlpatterns = [
    path('me/following/', MyFollowingView.as_view(), name='my-following'),
    path('me/tips/', MyTipsView.as_view(), name='my-tips'),
]
