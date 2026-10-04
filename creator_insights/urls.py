from django.urls import path

from billing.views import CreatorTipsSummaryView
from communities.views import CreatorCommunityReachView
from creator_insights.library_views import (
    CreatorCollectionsView,
    CreatorCollectionView,
    CreatorMetadataRequestsView,
    CreatorWorkspaceNotesView,
    CreatorWorkspaceNoteView,
)
from creator_insights.views import CreatorInsightsView, CreatorProfileView
from creator_insights.workbench_views import CreatorContentExportView, CreatorContentView

urlpatterns = [
    path('me/insights/', CreatorInsightsView.as_view(), name='creator-insights'),
    path('me/content/', CreatorContentView.as_view(), name='creator-content'),
    path('me/content/export/', CreatorContentExportView.as_view(), name='creator-content-export'),
    path('me/content/workspace-notes/', CreatorWorkspaceNotesView.as_view(), name='creator-workspace-notes'),
    path('me/content/<int:joke_id>/workspace/', CreatorWorkspaceNoteView.as_view(), name='creator-workspace-note'),
    path('me/content/metadata-requests/', CreatorMetadataRequestsView.as_view(), name='creator-metadata-requests'),
    path('me/communities/', CreatorCommunityReachView.as_view(), name='creator-communities'),
    path('me/collections/', CreatorCollectionsView.as_view(), name='creator-collections'),
    path('me/collections/<int:pk>/', CreatorCollectionView.as_view(), name='creator-collection'),
    path('<int:creator_id>/profile/', CreatorProfileView.as_view(), name='creator-profile'),
    path('<int:creator_id>/tips/summary/', CreatorTipsSummaryView.as_view(), name='creator-tips-summary'),
]
