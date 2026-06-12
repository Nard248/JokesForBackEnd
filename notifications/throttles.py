from rest_framework.throttling import SimpleRateThrottle


class ResendThrottle(SimpleRateThrottle):
    """Per-email throttle for resend-verification: 3 requests per 15 minutes.

    Subclasses SimpleRateThrottle (not ScopedRateThrottle) on purpose:
    ScopedRateThrottle reads its scope from the *view's* `throttle_scope`
    attribute, so a throttle-class-level scope is ignored and the throttle
    silently no-ops. SimpleRateThrottle reads the rate from THROTTLE_RATES
    using this class's `scope`, so it actually engages.
    """

    scope = 'verification_resend'

    def parse_rate(self, rate):
        # DRF's rate strings can't express a 15-minute window (the parser only
        # understands s/m/h/d as the period's first char). Hardcode the window;
        # the settings entry exists only so get_rate() doesn't raise.
        return (3, 15 * 60)

    def get_cache_key(self, request, view):
        # strip() before lower() so padded variants ("a@b.com ", " a@b.com")
        # can't each get their own throttle bucket — the serializer trims the
        # email, so the throttle must normalize identically or it's bypassable.
        email = (request.data.get('email') or '').strip().lower()
        if not email:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': email}
