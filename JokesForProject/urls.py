"""
URL configuration for JokesForProject project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from jokes.sitemap import sitemap_view
from jokes.views import CookieRegisterView, GoogleLogin, csrf_token_view, joke_share_page
from JokesForProject.health import healthz, readyz
from notifications.views import EmailUnsubscribeView, RunDigestsView

urlpatterns = [
    # Unauthenticated liveness probe — no DRF auth/versioning/throttling.
    # Process-only: never touches DB/cache (a 200 means "don't recycle me").
    path('healthz', healthz, name='healthz'),
    # Readiness probe — verifies DB + cache; returns 503 if either is down.
    # Point Cloud Monitoring uptime checks here; do NOT use for liveness.
    path('readyz', readyz, name='readyz'),

    # Public XML sitemap of frontend routes — the frontend's build pipeline
    # fetches this at deploy time and writes it to its own
    # public/sitemap.xml (a static, deploy-time snapshot regenerated on each
    # frontend deploy, not a live rewrite/proxy). See jokes/sitemap.py.
    path('sitemap.xml', sitemap_view, name='sitemap'),

    # Admin
    path('admin/', admin.site.urls),

    # Public share pages (before API routes)
    path('jokes/<int:pk>/share/', joke_share_page, name='joke-share'),

    # API v1
    path('api/v1/', include('jokes.urls')),
    path('api/v1/creators/', include('creator_insights.urls')),
    path('api/v1/follows/', include('follows.urls')),
    path('api/v1/users/', include('follows.user_urls')),
    path('api/v1/billing/', include('billing.urls')),
    # Creator Tips — deliberately NOT under api/v1/billing/: matches the
    # spec's resource-oriented paths (creators/{id}/tips/summary, users/me/tips
    # land under creator_insights/follows in a later wave task, same pattern).
    path('api/v1/tips/', include('billing.tip_urls')),

    # Authentication
    # CSRF bootstrap: the cross-site SPA GETs this to obtain the CSRF cookie +
    # token value before issuing any authenticated mutation. Declared before the
    # dj_rest_auth include (no conflict — dj_rest_auth defines no `csrf/` route).
    path('api/v1/auth/csrf/', csrf_token_view, name='csrf-token'),
    path('api/v1/auth/', include('dj_rest_auth.urls')),
    # Override registration root with cookie-setting variant; include still owns
    # sub-paths (verify-email, resend-email, account-confirm-email).
    path('api/v1/auth/registration/', CookieRegisterView.as_view(), name='rest_register'),
    path('api/v1/auth/registration/', include('dj_rest_auth.registration.urls')),
    path('api/v1/auth/google/', GoogleLogin.as_view(), name='google_login'),
    path('api/v1/auth/', include('notifications.urls')),
    path('api/v1/notifications/', include('inbox.urls')),
    # One-click unsubscribe (CAN-SPAM): signed token, no login. See
    # notifications.unsubscribe for the token helper digest emails embed.
    path('api/v1/email/unsubscribe/', EmailUnsubscribeView.as_view(), name='email-unsubscribe'),
    # Internal Cloud Scheduler trigger (Email-Digest-Wave Task 3): no user
    # auth, shared-secret header guard only — see notifications.views.RunDigestsView.
    path('api/v1/internal/run-digests/', RunDigestsView.as_view(), name='run-digests'),

    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
