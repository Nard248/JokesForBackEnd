from django.urls import path

from community_lab import views

urlpatterns = [
    path("api/v1/community-lab/snapshot/", views.snapshot_view),
    path("api/v1/community-lab/simulate/", views.simulate_view),
    path("api/v1/community-lab/share/", views.share_view),
    path("api/v1/community-lab/membership/", views.membership_view),
    path("api/v1/community-lab/advance/", views.advance_view),
]
