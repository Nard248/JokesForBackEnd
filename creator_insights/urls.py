from django.urls import path

from creator_insights.views import CreatorInsightsView

urlpatterns = [
    path('me/insights/', CreatorInsightsView.as_view(), name='creator-insights'),
]
