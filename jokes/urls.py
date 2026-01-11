"""
URL routing for the Jokes API.

Uses DRF's DefaultRouter to automatically generate URLs for all viewsets.
All endpoints are accessible under /api/v1/ (versioned path).
"""
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('jokes', views.JokeViewSet, basename='joke')
router.register('formats', views.FormatViewSet, basename='format')
router.register('age-ratings', views.AgeRatingViewSet, basename='age-rating')
router.register('tones', views.ToneViewSet, basename='tone')
router.register('context-tags', views.ContextTagViewSet, basename='context-tag')
router.register('culture-tags', views.CultureTagViewSet, basename='culture-tag')
router.register('languages', views.LanguageViewSet, basename='language')
router.register('preferences', views.UserPreferenceViewSet, basename='preferences')
router.register('collections', views.CollectionViewSet, basename='collection')
router.register('saved-jokes', views.SavedJokeViewSet, basename='saved-joke')

urlpatterns = router.urls
