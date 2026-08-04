from django.urls import path

from billing.views import CreatorTipsSummaryView
from creator_insights.views import CreatorInsightsView, CreatorProfileView

urlpatterns = [
    path('me/insights/', CreatorInsightsView.as_view(), name='creator-insights'),
    path('<int:creator_id>/profile/', CreatorProfileView.as_view(), name='creator-profile'),
    path('<int:creator_id>/tips/summary/', CreatorTipsSummaryView.as_view(), name='creator-tips-summary'),
]
