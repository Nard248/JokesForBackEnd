from rest_framework.throttling import ScopedRateThrottle


class ResendThrottle(ScopedRateThrottle):
    """Per-email throttle for resend-verification (scope: verification_resend)."""
    scope = 'verification_resend'

    def get_cache_key(self, request, view):
        # strip() before lower() so padded variants ("a@b.com ", " a@b.com")
        # can't each get their own throttle bucket — the serializer trims the
        # email, so the throttle must normalize identically or it's bypassable.
        email = (request.data.get('email') or '').strip().lower()
        if not email:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': email}
