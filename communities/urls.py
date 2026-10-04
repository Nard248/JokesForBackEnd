from django.urls import path

from communities.views import CommunityDetailView, CommunityDirectoryView, CommunityMembershipView

urlpatterns = [
    path('', CommunityDirectoryView.as_view(), name='community-directory'),
    path('<slug:slug>/', CommunityDetailView.as_view(), name='community-detail'),
    path('<slug:slug>/membership/', CommunityMembershipView.as_view(), name='community-membership'),
]
