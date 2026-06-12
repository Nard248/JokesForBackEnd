from django.urls import path

from .views import VerifyEmailView, ResendVerificationView

urlpatterns = [
    path('verify-email/', VerifyEmailView.as_view(), name='verify-email'),
    path('resend-verification/', ResendVerificationView.as_view(), name='resend-verification'),
]
