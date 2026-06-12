# Notification Engine (seam) + Registration Code Verification — Design

**Date:** 2026-05-31
**Status:** Draft, awaiting review
**Author:** brainstormed via superpowers:brainstorming
**Scope:** Backend (Django REST). New `notifications` app + registration flow change.

**Companion docs:**
- `Docs/API/Frontend_Integration_Handout.md` — frontend wiring (auth section will need updates after this ships)

---

## 1. Problem

Two gaps, one foundational and one immediate:

1. **No way to send email at all.** `EMAIL_BACKEND='console'` (settings.py:304) prints to stdout; nothing reaches users. `ACCOUNT_EMAIL_VERIFICATION='none'`. No email is sent anywhere in the codebase.
2. **Registration has no verification.** `CookieRegisterView` (jokes/views.py:629) issues JWT cookies *immediately* on signup — a user is fully authenticated before proving they own the email. This enables spam signups and fails the COPPA/age-gate posture the Compliance Addendum requires.

Longer term, the product needs an **engine** reusable for password resets, streak nudges, and marketing campaigns — not a one-off verification hack.

## 2. Goals and non-goals

### Goals
- Stand up a provider-agnostic email-sending **engine** (thin seam) that any feature can call.
- Ship **registration email verification** with a 6-digit code as the first feature on that engine.
- Hard-gate access: an unverified user gets **no session**.
- Keep the design swappable (provider) and extensible (channels, async dispatch, campaigns) without overbuilding.

### Non-goals (deferred; seam supports them)
- Cloud Tasks async dispatch (v1 sends synchronously in-request)
- Campaign/broadcast primitives, audience segmentation
- SMS / push channels
- Template-management admin UI
- Unsubscribe / preference center, open/click tracking webhooks
- Scheduled sends
- Password-reset email (trivial follow-on once the engine exists — explicitly out of this build)
- Cleanup job for abandoned unverified users (manual admin action for now; no cron)

## 3. Constraints

- **Single Cloud Run app, no Celery/workers/cron.** Everything request-triggered. v1 email send is synchronous. See [[feedback_no_celery_single_app]].
- **YAGNI.** Build the thin seam + the one feature; defer the rest. See [[feedback_yagni_scope]].
- **Secrets in GCP Secret Manager**, exposed as env to Cloud Run (consistent with existing `GOOGLE_CLIENT_SECRET`).
- **No destructive migrations.** Existing users/data preserved.

## 4. Architecture — three layers

```
FEATURE LAYER   (callers)
  RegistrationVerification (this build); future: password reset, nudges, campaigns
        │ notifications.send_email(to, template_name, context)
        ▼
ENGINE LAYER    (notifications/ — owns the abstraction)
  • service.send_email(): render template → write EmailMessageLog → dispatch
  • EmailMessageLog (outbox/audit, status field = async seam)
  • templates_registry (name → subject + html/txt)
  • EmailVerification (the feature's code lifecycle)
        │ Django EmailMultiAlternatives / send_mail()
        ▼
TRANSPORT LAYER (django-anymail → Resend)
  EMAIL_BACKEND = anymail.backends.resend.EmailBackend
  swap to SES/Postmark via env + key, no engine change
```

**Boundary contract:** the feature layer never imports Resend or touches templates directly. It calls one function: `notifications.service.send_email(to, template_name, context, user=None)`. The engine renders, logs, and dispatches.

**Dependency direction:** `jokes` → `notifications`, never the reverse. The engine knows nothing about jokes.

## 5. New Django app: `notifications`

```
notifications/
  __init__.py
  apps.py
  models.py            # EmailMessageLog, EmailVerification
  service.py           # send_email() — engine entry point
  templates_registry.py # TEMPLATES dict: name -> (subject, html, txt)
  verification.py      # issue_code(), verify_code(), invalidate_codes()
  views.py             # VerifyEmailView, ResendVerificationView
  serializers.py       # VerifyEmailSerializer, ResendSerializer
  throttles.py         # ResendThrottle, VerifyAttemptThrottle
  urls.py
  admin.py             # EmailMessageLog (read-only), EmailVerification (read-only)
  migrations/
  templates/notifications/email/
      base.html              # shared shell: logo, footer
      verification_code.html
      verification_code.txt
  tests/
      test_engine.py
      test_verification.py
      test_registration_flow.py
      test_throttling.py
```

**Why a separate app, not `jokes/`:** the engine is cross-cutting infrastructure reused by every future feature. Burying it in the joke domain would make campaigns/password-reset read as joke code and tangle the dependency graph.

## 6. Data model

```python
# notifications/models.py
from django.conf import settings
from django.db import models


class EmailMessageLog(models.Model):
    """Outbox + audit trail for every email the system attempts to send."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    to_email = models.EmailField(db_index=True)
    template_name = models.CharField(max_length=80)
    subject = models.CharField(max_length=255)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='pending', db_index=True
    )
    provider_message_id = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='email_logs',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['to_email', '-created_at'])]


class EmailVerification(models.Model):
    """6-digit code lifecycle for registration email verification."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='email_verifications',
    )
    code_hash = models.CharField(max_length=128)  # hashed, never plaintext
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', '-created_at'])]

    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() >= self.expires_at

    @property
    def is_consumed(self):
        return self.consumed_at is not None
```

### Design rationale

- **Code is hashed, never plaintext.** A 6-digit code is low entropy (10^6). Security comes from layering: 10-min expiry + max-5-attempts + resend rate limiting make brute force infeasible within a code's lifetime. Hashing ensures a DB leak exposes no live codes. Use Django's `make_password`/`check_password` (or a fast SHA-256 with the code as input — decision in §7) for constant-time comparison.
- **`EmailMessageLog.status` is the async seam.** v1: written `pending`, flipped to `sent` synchronously in the same request. Future: request writes `pending` + enqueues Cloud Tasks; the task flips to `sent`. No schema change, no caller change.

## 7. The engine: `service.send_email()`

```python
# notifications/service.py
def send_email(to_email, template_name, context, user=None):
    """Render a registered template, log it, and dispatch via the configured backend.

    Returns the EmailMessageLog row. Synchronous in v1.
    Raises EmailSendError on transport failure (caller decides UX).
    """
    subject, html_body, text_body = render_template(template_name, context)

    log = EmailMessageLog.objects.create(
        to_email=to_email, template_name=template_name,
        subject=subject, status='pending', user=user,
    )
    try:
        msg = EmailMultiAlternatives(
            subject=subject, body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL, to=[to_email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send()  # routes through EMAIL_BACKEND (anymail → Resend)
        log.status = 'sent'
        log.sent_at = timezone.now()
        log.save(update_fields=['status', 'sent_at'])
    except Exception as exc:
        log.status = 'failed'
        log.error = str(exc)
        log.save(update_fields=['status', 'error'])
        raise EmailSendError(str(exc)) from exc
    return log
```

**Template registry** (`templates_registry.py`): a dict mapping `template_name → (subject_string_or_fn, html_template_path, text_template_path)`. `render_template()` looks up the entry, renders subject + both bodies with the context via Django's template engine. New email types = a new dict entry + two template files. No engine code change.

### Code hashing decision

Use **SHA-256 of the code** (not `make_password`/PBKDF2). Rationale: PBKDF2 is deliberately slow to resist offline password cracking, but a 6-digit code is short-lived (10 min) and attempt-limited (5), so the threat model is different — we want a fast, constant-time digest, not a slow KDF. SHA-256 with `hmac.compare_digest` is appropriate and keeps verification snappy. (The code is the secret; no per-user salt needed because the code itself is random per issuance.)

## 8. Registration flow (hard gate)

### Before (current)
`POST /registration/` → create active user → JWT cookies in response. Authenticated immediately.

### After
```
1. POST /api/v1/auth/registration/   { email, password1, password2 }
     → create User with is_active=False
     → verification.issue_code(user)  → EmailVerification(6-digit, 10-min)
     → notifications.send_email(user.email, 'verification_code', {'code': ...}, user=user)
     → 201 { "detail": "Verification code sent to your email.", "email": "<email>" }
     → NO tokens, NO cookies

2. POST /api/v1/auth/verify-email/   { email, code }
     → load latest unconsumed EmailVerification for the user
     → reject if: expired / consumed / attempts >= 5 / hash mismatch (increment attempts on mismatch)
     → on success: user.is_active=True; verification.consumed_at=now
     → issue JWT cookies (the deferred login — reuse set_jwt_cookies)
     → 200 { "user": {...} }

3. POST /api/v1/auth/resend-verification/   { email }
     → throttled (see §9)
     → invalidate prior unconsumed codes for the user
     → issue a fresh code + send
     → 200 { "detail": "If that email is registered, a new code has been sent." }
       (same response whether or not the email exists — anti-enumeration)
```

### Enforcement
- `is_active=False` is the hard gate. Django's `ModelBackend` refuses authentication for inactive users automatically — so even if a token were somehow minted, login is refused. Defense in depth, not just a flag.
- `CookieRegisterView` is modified to: create inactive, not set cookies, trigger the code email, return the new 201 shape.

### Google OAuth exemption
Google has already verified the user's email. The `GoogleLogin` social flow creates the user with `is_active=True` and issues **no** verification code. Verifying a Google-verified email is pure friction. (Confirmed with product 2026-05-31.)

## 9. Error handling & abuse controls

| Risk | Control |
|---|---|
| Brute-force the 6-digit code | Max 5 attempts per code (then dead); 10-min expiry. Attempts incremented on each mismatch. |
| Resend spam / email bombing | `ResendThrottle`: 3 resends / 15 min per email + 10 / hour per IP. |
| Registration spam | Per-IP signup throttle (DRF `AnonRateThrottle` already configured at 100/hr; add a tighter scoped throttle on registration). |
| Email send failure (Resend down) | `EmailMessageLog` row marked `failed` with error; endpoint returns 502 + actionable message ("Couldn't send the code — try Resend"). User left in a recoverable state (can resend). |
| Account enumeration | `resend-verification` and `verify-email` return uniform responses regardless of whether the email exists / is already verified. |
| Abandoned unverified accounts | Deferred: a manual admin action to purge `is_active=False` users with no consumed verification older than N days. No cron in v1. |

### Verify-email error responses
- Expired code → 400 `{ "code": ["This code has expired. Request a new one."] }`
- Wrong code → 400 `{ "code": ["Incorrect code."] }` (attempts incremented)
- Too many attempts → 429 `{ "detail": "Too many attempts. Request a new code." }`
- Already verified → 400 `{ "detail": "This email is already verified. Please log in." }`

## 10. Configuration & secrets

```python
# settings.py — environment-driven, defaults safe for local dev
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend'
)
# Production env sets: EMAIL_BACKEND=anymail.backends.resend.EmailBackend
ANYMAIL = {'RESEND_API_KEY': os.getenv('RESEND_API_KEY', '')}
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Jokes For <noreply@localhost>')

EMAIL_VERIFICATION_CODE_TTL_MINUTES = int(os.getenv('EMAIL_VERIFICATION_CODE_TTL_MINUTES', '10'))
EMAIL_VERIFICATION_MAX_ATTEMPTS = int(os.getenv('EMAIL_VERIFICATION_MAX_ATTEMPTS', '5'))
```

- `INSTALLED_APPS += ['anymail', 'notifications']`
- Local dev: console backend (the 6-digit code prints to the terminal — read it from stdout to test).
- Tests: `django.core.mail.backends.locmem.EmailBackend` (no network).
- Prod/staging: `anymail.backends.resend.EmailBackend` + `RESEND_API_KEY` from Secret Manager + a verified sending domain.

### External dependency (operational, not code)
Sending real email requires a **Resend account + API key** and a **verified sending domain** (SPF/DKIM/DMARC DNS records). The frontend's `*.web.app` host cannot hold custom DNS, so a real registered domain is needed before public launch. This has lead time (DNS propagation, possibly domain purchase) but does **not** block development — build and test entirely on console/locmem backends.

## 11. API surface

New endpoints (added under `api/v1/auth/`):

| Method | Path | Auth | Body | Success |
|---|---|---|---|---|
| POST | `/api/v1/auth/registration/` | public | `email, password1, password2` | 201 `{detail, email}` (no tokens) — *modified* |
| POST | `/api/v1/auth/verify-email/` | public | `email, code` | 200 `{user}` + JWT cookies — *new* |
| POST | `/api/v1/auth/resend-verification/` | public | `email` | 200 `{detail}` — *new* |

Existing `GoogleLogin` unchanged except it creates `is_active=True` users (verify it doesn't already; adjust if needed).

## 12. Testing strategy

- **Engine (`test_engine.py`):** `send_email()` writes a `pending`→`sent` log row, renders subject + html + txt, sends via locmem; assert mail.outbox content. Failure path: a backend that raises → row marked `failed`, `EmailSendError` raised.
- **Verification (`test_verification.py`):** issue→verify happy path; expired code rejected; wrong code increments attempts; 6th attempt → blocked; consumed code can't be reused; resend invalidates prior unconsumed codes; code stored hashed (assert plaintext not in DB).
- **Registration flow (`test_registration_flow.py`):** register → 201 with no tokens, user `is_active=False`, one email sent, one EmailVerification row → verify with the code (extracted from the issued row in test) → 200 with JWT cookies, user `is_active=True`.
- **Throttling (`test_throttling.py`):** 4th resend in window → 429.
- **Google exemption:** social signup path → `is_active=True`, zero EmailVerification rows, zero emails. (May live in jokes tests if that's where social tests are.)

## 13. Migration / deploy risk

| Risk | Mitigation |
|---|---|
| Existing active users unaffected | New tables only; no change to existing user rows. The flow change applies to *new* signups. |
| In-flight signups during deploy | Negligible; the change is additive endpoints + one view behavior change. |
| Prod sends before domain verified | Guarded by env: prod won't flip `EMAIL_BACKEND` to Resend until `RESEND_API_KEY` + verified domain are in place. Until then, console backend (no user-facing email) — so don't enable the hard gate in prod until Resend is live, or users can't complete signup. **Sequencing note for the plan:** ship engine + endpoints first (backed by console), flip the gate ON only once Resend + domain are verified. |
| Synchronous send adds request latency | One email (~200-400ms via Resend). Acceptable for a registration request. Async via Cloud Tasks is the documented upgrade path if it becomes a problem. |

## 14. Open questions (none blocking)

1. **Sender identity / domain** — needs a real registered domain for DKIM/SPF. Operational, parallel-trackable. (Owner: product/infra.)
2. **Cleanup of abandoned unverified users** — deferred to a manual admin action; revisit if they accumulate.
3. **Resend webhook for bounce/complaint handling** — deferred; would feed `EmailMessageLog` status from `sent` → `bounced`. Not needed for v1.

## 15. Future extensions the seam enables (not this build)

- **Cloud Tasks async dispatch:** request writes `pending` + enqueues; an internal endpoint drains and flips to `sent`. No schema change.
- **Password reset email:** new template entry + a view calling `send_email`. ~Half a day on top of this engine.
- **Campaigns/broadcasts:** a `Campaign` model + audience query + batched `send_email` calls (rate-limited), reusing the same log + transport.
- **Multi-channel:** add a `channel` field + SMS/push adapters behind the same service interface.
