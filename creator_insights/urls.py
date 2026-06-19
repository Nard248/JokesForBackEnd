from django.urls import path

from creator_insights.views import CreatorInsightsView, CreatorProfileView

urlpatterns = [
    path('me/insights/', CreatorInsightsView.as_view(), name='creator-insights'),
    path('<int:creator_id>/profile/', CreatorProfileView.as_view(), name='creator-profile'),
]
