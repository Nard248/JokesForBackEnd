"""
URL routing for the Jokes API.

Uses DRF's DefaultRouter for standard viewsets, with explicit path()
patterns for endpoints that don't fit the router convention.
All endpoints are accessible under /api/v1/ (versioned path).
"""
from django.urls import path
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
router.register('vibes', views.VibeViewSet, basename='vibe')
router.register('packs', views.JokePackViewSet, basename='pack')
router.register('collections', views.CollectionViewSet, basename='collection')
router.register('saved-jokes', views.SavedJokeViewSet, basename='saved-joke')
router.register('daily-jokes', views.DailyJokeViewSet, basename='daily-joke')
router.register('favorites', views.FavoriteViewSet, basename='favorite')

# Explicit URL patterns for non-router endpoints
urlpatterns = [
    # Media uploads (Wave 1)
    path('media/uploads/', views.MediaUploadView.as_view(), name='media-upload'),

    # Joke Submission & Drafts (Phase 2)
    path('jokes/submit/', views.JokeSubmitView.as_view(), name='joke-submit'),
    path('jokes/<int:pk>/reveal/', views.JokeRevealView.as_view(), name='joke-reveal'),
    path('jokes/my-drafts/', views.JokeDraftListView.as_view(), name='joke-drafts-list'),
    path('jokes/my-drafts/<int:pk>/', views.JokeDraftDetailView.as_view(), name='joke-draft-detail'),
    path('jokes/my-drafts/<int:pk>/submit/', views.JokeDraftSubmitView.as_view(), name='joke-draft-submit'),

    # User Profile, Activity, Achievements, Preferences (Phase 4)
    path('users/me/profile/', views.UserProfileView.as_view(), name='user-profile'),
    path('users/me/activity/', views.UserActivityView.as_view(), name='user-activity'),
    path('users/me/achievements/', views.UserAchievementsView.as_view(), name='user-achievements'),
    path('users/me/preferences/', views.UserPreferencesView.as_view(), name='user-preferences'),
    # Vibes (P2 of Pivot Plan) — user's selected humor flavors
    path('users/me/vibes/', views.UserVibesView.as_view(), name='user-vibes'),
    # Mystery Box (P3 of Pivot Plan)
    path('mystery-box/status/', views.MysteryBoxStatusView.as_view(), name='mystery-box-status'),
    path('mystery-box/roll/', views.MysteryBoxRollView.as_view(), name='mystery-box-roll'),
    # Recently viewed (P5 of Pivot Plan)
    path('users/me/recently-viewed/', views.RecentlyViewedView.as_view(), name='recently-viewed'),
    # Streak (P6 of Pivot Plan)
    path('users/me/streak/', views.StreakView.as_view(), name='user-streak'),
    path('users/me/streak/freeze/', views.StreakFreezeView.as_view(), name='user-streak-freeze'),
    path('users/me/streak/freeze/remove/', views.StreakFreezeRemoveView.as_view(), name='user-streak-freeze-remove'),
    # Joke Packs (P7 of Pivot Plan)
    path('packs/<slug:slug>/progress/', views.JokePackProgressView.as_view(), name='pack-progress'),
    path('users/me/packs/in-progress/', views.JokePackInProgressView.as_view(), name='packs-in-progress'),
    # Ritual status (P8 of Pivot Plan)
    path('users/me/today-status/', views.DailyRitualStatusView.as_view(), name='today-status'),
    # Insights (P9 of Pivot Plan)
    path('users/me/taste-profile/', views.TasteProfileView.as_view(), name='taste-profile'),

    # Audience telemetry ingest (Phase 1) — bulk, fire-and-forget
    path('telemetry/events', views.TelemetryIngestView.as_view(), name='telemetry-ingest'),

    # Trending & Discovery (Phase 5) — non-router endpoints
    path('tags/trending/', views.TagsTrendingView.as_view(), name='tags-trending'),
    path('tags/rising/', views.TagsRisingView.as_view(), name='tags-rising'),
    path('users/top-jokesters/', views.TopJokestersView.as_view(), name='top-jokesters'),
    path('themes/popular/', views.ThemesPopularView.as_view(), name='themes-popular'),

    # Compliance & Account Management (Phase 6)
    path('reports/', views.ContentReportView.as_view(), name='content-report'),
    # Appeals (Appeals & Notices wave)
    path('appeals/', views.AppealCreateView.as_view(), name='appeal-create'),
    path('users/me/appeals/', views.MyAppealsView.as_view(), name='my-appeals'),
    path('users/me/blocks/', views.MyBlocksView.as_view(), name='my-blocks'),
    path('users/<int:user_id>/block/', views.UserBlockView.as_view(), name='user-block'),
    path('users/me/', views.UserAccountDeleteView.as_view(), name='user-account-delete'),
    path('users/me/data-export/', views.DataExportView.as_view(), name='data-export'),
] + router.urls
