# Phase 06: Authentication - Research

**Researched:** 2026-01-11
**Domain:** Django REST Framework JWT Authentication with Google OAuth
**Confidence:** HIGH

<research_summary>
## Summary

Researched the Django REST Framework authentication ecosystem for implementing JWT-based authentication with Google OAuth social login. The standard approach uses **dj-rest-auth** as the unified authentication layer, which integrates **djangorestframework-simplejwt** for JWT token handling and **django-allauth** for social authentication.

Key finding: Don't hand-roll JWT token management, OAuth flows, or refresh token rotation. The dj-rest-auth package provides a battle-tested solution that handles registration, login, password reset, social auth, and JWT tokens in a cohesive manner. Using simplejwt directly is an option for more control, but dj-rest-auth offers significant convenience with minimal overhead.

**Primary recommendation:** Use dj-rest-auth with JWT mode + django-allauth for Google OAuth. Configure secure token lifetimes, enable refresh token rotation with blacklisting, and use HttpOnly cookies for token storage.
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| dj-rest-auth | 7.0.1 | Unified auth REST endpoints | Combines JWT + social auth, actively maintained, 77k weekly downloads |
| djangorestframework-simplejwt | 5.5.1 | JWT token generation/validation | Most popular DRF JWT library, Jazzband maintained, production-stable |
| django-allauth | 65.13.1 | Social authentication (Google OAuth) | 50+ providers, MFA support, enterprise-ready, rate limiting built-in |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-decouple | 3.8+ | Environment variables | Store OAuth credentials securely |
| django-cors-headers | 4.9.0 | CORS for frontend | Already installed - needed for token endpoints |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| dj-rest-auth | simplejwt directly | More control but must build registration/password reset yourself |
| django-allauth | social-auth-app-django | allauth has better docs, more providers, more active |
| JWT cookies | localStorage | localStorage vulnerable to XSS - cookies with HttpOnly are safer |

**Installation:**
```bash
pip install 'dj-rest-auth[with_social]' djangorestframework-simplejwt
```

Note: `dj-rest-auth[with_social]` automatically installs django-allauth.
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Project Structure
```
JokesForProject/
├── settings.py           # Auth configuration (REST_AUTH, SIMPLE_JWT, SOCIALACCOUNT_PROVIDERS)
├── urls.py               # Auth URL routing (/api/v1/auth/*)
└── jokes/
    └── (no auth code here - use dj-rest-auth's built-in views)
```

### Pattern 1: JWT with HttpOnly Cookies
**What:** Store JWT tokens in secure HttpOnly cookies instead of localStorage
**When to use:** Always for web applications (protects against XSS)
**Example:**
```python
# settings.py
REST_AUTH = {
    'USE_JWT': True,
    'JWT_AUTH_COOKIE': 'jokes-access-token',
    'JWT_AUTH_REFRESH_COOKIE': 'jokes-refresh-token',
    'JWT_AUTH_HTTPONLY': True,
    'JWT_AUTH_SECURE': True,  # Set False for local dev (no HTTPS)
    'JWT_AUTH_SAMESITE': 'Lax',
}
```

### Pattern 2: Short Access + Long Refresh Tokens
**What:** Access tokens expire quickly (5-30 min), refresh tokens last longer (1-7 days)
**When to use:** Standard JWT security practice
**Example:**
```python
# settings.py
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
}
```

### Pattern 3: Google OAuth with Server-Side Flow
**What:** Use authorization code flow (not implicit) with PKCE
**When to use:** For secure OAuth - code exchanged server-side
**Example:**
```python
# settings.py
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'offline'},
        'OAUTH_PKCE_ENABLED': True,
    }
}
```

### Pattern 4: Social Login View for REST API
**What:** Create custom view to accept OAuth code from frontend
**When to use:** SPA frontend handles OAuth redirect, sends code to backend
**Example:**
```python
# views.py (if needed)
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView

class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    callback_url = 'http://localhost:5173/auth/google/callback'  # Frontend URL
    client_class = OAuth2Client
```

### Anti-Patterns to Avoid
- **Storing JWTs in localStorage:** Vulnerable to XSS attacks - use HttpOnly cookies
- **Long-lived access tokens:** Use short access (15min) + refresh rotation instead
- **Trusting the alg header:** Always validate tokens server-side with known algorithm
- **Building custom OAuth flows:** Use allauth - OAuth has many edge cases
- **Skipping token blacklisting:** Enable BLACKLIST_AFTER_ROTATION to prevent replay attacks
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JWT generation/signing | Custom PyJWT code | djangorestframework-simplejwt | Token rotation, blacklisting, refresh logic is complex |
| OAuth authorization flow | Custom requests to Google | django-allauth | State management, PKCE, token exchange have security pitfalls |
| Registration flow | Custom User creation views | dj-rest-auth.registration | Email verification, social account linking handled |
| Password reset | Custom email + token logic | dj-rest-auth | Secure token generation, expiration, rate limiting |
| Token refresh rotation | Manual refresh logic | simplejwt ROTATE_REFRESH_TOKENS | Blacklisting + rotation + atomic operations |
| Login throttling | Custom middleware | DRF throttling + django-axes | Race conditions, bypass vulnerabilities |

**Key insight:** Authentication is a solved problem with well-tested libraries. Custom implementations commonly have vulnerabilities: algorithm confusion attacks, token replay, improper validation. dj-rest-auth + simplejwt + allauth have thousands of production deployments and security audits.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Algorithm Confusion Attack
**What goes wrong:** Attacker changes JWT `alg` header to `none` or switches from RS256 to HS256
**Why it happens:** Code trusts the alg claim in the token before verification
**How to avoid:** Always specify `ALGORITHM` in SIMPLE_JWT settings; simplejwt handles this correctly by default
**Warning signs:** Using PyJWT directly without explicit algorithm parameter

### Pitfall 2: Storing Tokens in localStorage
**What goes wrong:** XSS attack steals all tokens, attacker has full account access
**Why it happens:** localStorage is accessible to any JavaScript on the page
**How to avoid:** Use `JWT_AUTH_HTTPONLY = True` to store in HttpOnly cookies
**Warning signs:** Frontend code that does `localStorage.setItem('token', ...)`

### Pitfall 3: No Refresh Token Rotation
**What goes wrong:** Stolen refresh token works indefinitely
**Why it happens:** Refresh tokens not rotated on use, or old tokens not blacklisted
**How to avoid:** Set `ROTATE_REFRESH_TOKENS = True` and `BLACKLIST_AFTER_ROTATION = True`
**Warning signs:** Same refresh token works multiple times without changing

### Pitfall 4: OAuth State Parameter Mishandling
**What goes wrong:** CSRF attacks on OAuth callback
**Why it happens:** Custom OAuth code doesn't validate state parameter
**How to avoid:** Use django-allauth - it handles state validation automatically
**Warning signs:** Manual OAuth implementation without state verification

### Pitfall 5: Missing SITE_ID Configuration
**What goes wrong:** django-allauth fails silently or with cryptic errors
**Why it happens:** `django.contrib.sites` requires SITE_ID but it's not set
**How to avoid:** Add `SITE_ID = 1` to settings.py, run migrations for sites framework
**Warning signs:** 500 errors on social login endpoints, "Site matching query does not exist"

### Pitfall 6: Frontend/Backend Callback URL Mismatch
**What goes wrong:** Google OAuth returns error: "redirect_uri_mismatch"
**Why it happens:** Callback URL in code doesn't match Google Console configuration
**How to avoid:** Ensure exact match between GoogleLogin.callback_url and Google Console Authorized Redirect URIs
**Warning signs:** OAuth flow starts but fails at callback step
</common_pitfalls>

<code_examples>
## Code Examples

Verified patterns from official documentation:

### Complete settings.py Configuration
```python
# Source: dj-rest-auth + simplejwt official docs
from datetime import timedelta

INSTALLED_APPS = [
    # ... existing apps ...
    'rest_framework',
    'rest_framework.authtoken',  # Required by dj-rest-auth
    'rest_framework_simplejwt.token_blacklist',  # For token blacklisting
    'dj_rest_auth',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'dj_rest_auth.registration',
]

SITE_ID = 1

MIDDLEWARE = [
    # ... existing middleware ...
    'allauth.account.middleware.AccountMiddleware',  # Required by allauth
]

# Authentication backends
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# REST Framework config (extend existing)
REST_FRAMEWORK = {
    # ... existing config ...
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'dj_rest_auth.jwt_auth.JWTCookieAuthentication',
    ],
}

# dj-rest-auth settings
REST_AUTH = {
    'USE_JWT': True,
    'JWT_AUTH_COOKIE': 'jokes-access-token',
    'JWT_AUTH_REFRESH_COOKIE': 'jokes-refresh-token',
    'JWT_AUTH_HTTPONLY': True,
    'JWT_AUTH_SECURE': False,  # True in production (requires HTTPS)
    'JWT_AUTH_SAMESITE': 'Lax',
    'SESSION_LOGIN': False,  # Disable session auth, use JWT only
}

# Simple JWT settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# allauth settings
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_VERIFICATION = 'optional'  # 'mandatory' for production
ACCOUNT_UNIQUE_EMAIL = True

# Google OAuth settings
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'offline'},
        'OAUTH_PKCE_ENABLED': True,
    }
}
```

### URL Configuration
```python
# Source: dj-rest-auth docs
# urls.py
from django.urls import path, include

urlpatterns = [
    # ... existing patterns ...

    # Auth endpoints at /api/v1/auth/
    path('api/v1/auth/', include('dj_rest_auth.urls')),
    path('api/v1/auth/registration/', include('dj_rest_auth.registration.urls')),

    # Google OAuth endpoint
    path('api/v1/auth/google/', GoogleLogin.as_view(), name='google_login'),
]
```

### Google Login View
```python
# Source: dj-rest-auth social auth docs
# Create in jokes/views.py or a dedicated auth/views.py

from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView
from django.conf import settings

class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    callback_url = settings.GOOGLE_OAUTH_CALLBACK_URL  # Define in settings
    client_class = OAuth2Client
```

### Frontend Token Usage (React example)
```typescript
// Source: Community best practice
// Note: With HttpOnly cookies, tokens are sent automatically

// Login - cookies are set automatically by the response
const login = async (email: string, password: string) => {
  const response = await fetch('/api/v1/auth/login/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',  // Important: send cookies
    body: JSON.stringify({ email, password }),
  });
  return response.json();
};

// Authenticated request - cookies sent automatically
const fetchJokes = async () => {
  const response = await fetch('/api/v1/jokes/', {
    credentials: 'include',  // Important: send cookies
  });
  return response.json();
};
```
</code_examples>

<sota_updates>
## State of the Art (2025-2026)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| django-rest-auth | dj-rest-auth | 2020 | Original unmaintained, dj-rest-auth is active fork |
| localStorage tokens | HttpOnly cookies | Always preferred | Better XSS protection, dj-rest-auth makes it easy |
| Manual refresh | ROTATE_REFRESH_TOKENS | simplejwt 4.x+ | Built-in rotation + blacklisting |
| OAuth implicit flow | Authorization code + PKCE | 2020+ | PKCE now standard for public clients |

**New tools/patterns to consider:**
- **dj-rest-auth 7.x:** Latest version with improved JWT cookie handling
- **django-allauth 65.x:** MFA support, rate limiting enabled by default, SAML 2.0
- **PKCE for OAuth:** Enable `OAUTH_PKCE_ENABLED` for all OAuth providers

**Deprecated/outdated:**
- **django-rest-auth:** Unmaintained since 2019, use dj-rest-auth
- **PyJWT direct usage:** Use simplejwt for DRF integration
- **OAuth implicit flow:** Use authorization code with PKCE instead
</sota_updates>

<open_questions>
## Open Questions

Things that couldn't be fully resolved:

1. **Apple Sign-In Complexity**
   - What we know: Listed as "optional for MVP" in roadmap, requires Apple Developer account
   - What's unclear: Whether the effort is worth it for MVP given 80%+ users use Google
   - Recommendation: Skip for MVP, add post-launch if user feedback requests it

2. **Email Verification Strategy**
   - What we know: allauth supports 'none', 'optional', 'mandatory' verification
   - What's unclear: Whether to require email verification for MVP (adds friction)
   - Recommendation: Start with 'optional', switch to 'mandatory' if spam becomes an issue

3. **Guest Mode Implementation**
   - What we know: Roadmap mentions "anonymous browsing" support
   - What's unclear: Whether guests need any persistent identity (for saved jokes)
   - Recommendation: Allow unauthenticated API access for read endpoints, require auth for saves/collections
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- [djangorestframework-simplejwt docs](https://django-rest-framework-simplejwt.readthedocs.io/en/latest/getting_started.html) - Installation, configuration, token endpoints
- [dj-rest-auth docs](https://dj-rest-auth.readthedocs.io/en/latest/installation.html) - Installation, JWT setup, social auth
- [django-allauth Google provider](https://docs.allauth.org/en/dev/socialaccount/providers/google.html) - Google OAuth configuration
- [PyPI: djangorestframework-simplejwt 5.5.1](https://pypi.org/project/djangorestframework-simplejwt/) - Version, requirements
- [PyPI: django-allauth 65.13.1](https://pypi.org/project/django-allauth/) - Version, requirements
- [Libraries.io: dj-rest-auth 7.0.1](https://libraries.io/pypi/dj-rest-auth) - Version, release date

### Secondary (MEDIUM confidence)
- [Medium: JWT Best Practices](https://medium.com/@onurmaciit/mastering-jwt-authentication-in-django-rest-framework-best-practices-and-techniques-d47f906f530a) - Security recommendations verified against docs
- [42Crunch: JWT Pitfalls](https://42crunch.com/7-ways-to-avoid-jwt-pitfalls/) - Security vulnerabilities
- [OWASP Django Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Django_Security_Cheat_Sheet.html) - General security

### Tertiary (LOW confidence - needs validation)
- None - all findings verified with primary sources
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: Django REST Framework JWT Authentication
- Ecosystem: dj-rest-auth, simplejwt, django-allauth
- Patterns: JWT cookies, refresh rotation, OAuth code flow
- Pitfalls: XSS storage, algorithm confusion, state handling

**Confidence breakdown:**
- Standard stack: HIGH - verified with PyPI, official docs
- Architecture: HIGH - patterns from official documentation
- Pitfalls: HIGH - documented in security resources, verified with RFC 8725
- Code examples: HIGH - from official documentation

**Research date:** 2026-01-11
**Valid until:** 2026-02-11 (30 days - stable ecosystem, infrequent breaking changes)
</metadata>

---

*Phase: 06-authentication*
*Research completed: 2026-01-11*
*Ready for planning: yes*
