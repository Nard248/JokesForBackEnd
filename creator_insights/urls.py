from django.urls import path

from billing.views import CreatorTipsSummaryView
from creator_insights.views import CreatorInsightsView, CreatorProfileView
from creator_insights.workbench_views import CreatorContentExportView, CreatorContentView

urlpatterns = [
    path('me/insights/', CreatorInsightsView.as_view(), name='creator-insights'),
    path('me/content/', CreatorContentView.as_view(), name='creator-content'),
    path('me/content/export/', CreatorContentExportView.as_view(), name='creator-content-export'),
    path('<int:creator_id>/profile/', CreatorProfileView.as_view(), name='creator-profile'),
    path('<int:creator_id>/tips/summary/', CreatorTipsSummaryView.as_view(), name='creator-tips-summary'),
]
