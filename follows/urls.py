from django.urls import path

from follows.views import FollowersListView, FollowStatusView, FollowView

urlpatterns = [
    path('<int:creator_id>/', FollowView.as_view(), name='follow'),
    path('<int:creator_id>/status/', FollowStatusView.as_view(), name='follow-status'),
    path('<int:creator_id>/followers/', FollowersListView.as_view(), name='follow-followers'),
]
