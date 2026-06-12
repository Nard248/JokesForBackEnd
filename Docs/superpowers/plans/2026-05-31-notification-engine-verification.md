# Notification Engine + Registration Code Verification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a provider-agnostic email engine (thin seam) and ship registration email verification with a 6-digit code that hard-gates account access, behind an env flag so the gate can be enabled only once a real email provider is live.

**Architecture:** A new `notifications` Django app owns the engine: an `EmailMessageLog` outbox/audit table, a `service.send_email()` entry point that renders a registered template and dispatches through Django's standard mail backend (django-anymail → Resend in prod, console locally, locmem in tests), and an `EmailVerification` model + logic for the 6-digit code lifecycle. The registration view is modified to create inactive users and issue a code when `EMAIL_VERIFICATION_REQUIRED` is on; two new endpoints verify the code (issuing JWT cookies) and resend it.

**Tech Stack:** Django 5 + DRF, dj-rest-auth 7.0.2, django-allauth 65.13.1, django-anymail (Resend backend), SimpleJWT. Tests use Django `TestCase`/`APITestCase` with the `locmem` email backend.

**Spec:** `docs/superpowers/specs/2026-05-31-notification-engine-verification-design.md`

**Context for the engineer:**
- Tests run with `python manage.py test <path> -v 2 --keepdb` (Neon pooler blocks DROP DATABASE; always use `--keepdb`).
- `set_jwt_cookies` is imported from `dj_rest_auth.jwt_auth` (see jokes/views.py:19). It accepts a response + access + refresh token objects and writes the HttpOnly cookies.
- The existing registration serializer is `JokesForProject/serializers.py::EmailOnlyRegisterSerializer`; its `save(request)` creates an **active** user (Django default). We will flip `is_active=False` in the view, not the serializer, so the serializer stays reusable.
- `CookieRegisterView` (jokes/views.py:629) subclasses dj-rest-auth `RegisterView` and currently sets JWT cookies on 201.
- Commit message style: no Co-Authored-By / generated-with footers; plain description.
- Branch: `feat/notification-engine-verification` (already checked out).

---

## File Structure

**Create:**
- `notifications/__init__.py`, `notifications/apps.py` — app scaffold (Task 1)
- `notifications/models.py` — `EmailMessageLog`, `EmailVerification` (Task 2)
- `notifications/migrations/0001_initial.py` — auto-generated (Task 2)
- `notifications/templates_registry.py` — template registry + `render_template()` (Task 3)
- `notifications/templates/notifications/email/base.html`, `verification_code.html`, `verification_code.txt` (Task 3)
- `notifications/service.py` — `send_email()`, `EmailSendError` (Task 4)
- `notifications/verification.py` — `issue_code`, `verify_code`, `invalidate_codes`, `issue_and_send` (Task 5)
- `notifications/serializers.py` — `VerifyEmailSerializer`, `ResendVerificationSerializer` (Task 7)
- `notifications/throttles.py` — `ResendThrottle` (Task 7)
- `notifications/views.py` — `VerifyEmailView`, `ResendVerificationView` (Task 7)
- `notifications/urls.py` — auth sub-routes (Task 7)
- `notifications/admin.py` — read-only admin for both models (Task 9)
- `notifications/tests/__init__.py` + `test_models.py`, `test_engine.py`, `test_verification.py`, `test_registration_flow.py`, `test_verify_resend.py` (Tasks 2-8)

**Modify:**
- `JokesForProject/settings.py` — INSTALLED_APPS (+anymail, +notifications), email config, verification settings, throttle scope (Task 1)
- `jokes/views.py` — `CookieRegisterView.create()` gated flow (Task 6); confirm `GoogleLogin` exemption (Task 8)
- `JokesForProject/urls.py` — include `notifications.urls` (Task 7)

---

## Task 1: Scaffold the `notifications` app + settings wiring

**Files:**
- Create: `notifications/__init__.py`, `notifications/apps.py`
- Modify: `JokesForProject/settings.py`

- [ ] **Step 1: Create the app package**

Create `notifications/__init__.py` (empty file).

Create `notifications/apps.py`:
```python
from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'notifications'
```

- [ ] **Step 2: Install django-anymail**

```bash
cd /Users/narekmeloyan/PycharmProjects/JokesForProject
pip install 'django-anymail[resend]'
pip freeze | grep -i anymail >> /dev/null && pip freeze | grep -iE "anymail" 
```
Then append the pinned version to `requirements.txt` (read the version from the pip output, e.g. `django-anymail==11.0.1`).

- [ ] **Step 3: Wire INSTALLED_APPS**

In `JokesForProject/settings.py`, the `INSTALLED_APPS` list ends with:
```python
    # Local apps
    'jokes',
]
```
Change to:
```python
    'anymail',
    # Local apps
    'jokes',
    'notifications',
]
```

- [ ] **Step 4: Add email + verification settings**

In `JokesForProject/settings.py`, find the line:
```python
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
```
Replace it with:
```python
# Email backend is environment-driven. Local dev prints to console (read the
# 6-digit code from stdout). Prod sets EMAIL_BACKEND=anymail.backends.resend.EmailBackend.
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend'
)
ANYMAIL = {'RESEND_API_KEY': os.getenv('RESEND_API_KEY', '')}
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Jokes For <noreply@localhost>')

# Registration email verification (the notifications app).
# EMAIL_VERIFICATION_REQUIRED is the deploy gate: keep False until a real email
# provider + verified domain are live, else new users cannot receive their code.
EMAIL_VERIFICATION_REQUIRED = os.getenv('EMAIL_VERIFICATION_REQUIRED', 'false').lower() == 'true'
EMAIL_VERIFICATION_CODE_TTL_MINUTES = int(os.getenv('EMAIL_VERIFICATION_CODE_TTL_MINUTES', '10'))
EMAIL_VERIFICATION_MAX_ATTEMPTS = int(os.getenv('EMAIL_VERIFICATION_MAX_ATTEMPTS', '5'))
```

- [ ] **Step 5: Add the resend throttle scope**

In `JokesForProject/settings.py`, find:
```python
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
    },
```
Change to:
```python
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'verification_resend': '3/15min',
    },
```

- [ ] **Step 6: Verify Django still boots**

```bash
python manage.py check
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 7: Commit**

```bash
git add notifications/__init__.py notifications/apps.py JokesForProject/settings.py requirements.txt
git commit -m "feat: scaffold notifications app and email/verification settings"
```

---

## Task 2: Models — EmailMessageLog + EmailVerification

**Files:**
- Create: `notifications/models.py`
- Create: `notifications/migrations/0001_initial.py` (auto-generated)
- Create: `notifications/tests/__init__.py`, `notifications/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/__init__.py` (empty).

Create `notifications/tests/test_models.py`:
```python
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from notifications.models import EmailMessageLog, EmailVerification

User = get_user_model()


class EmailVerificationModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='v@example.com', email='v@example.com', password='pw',
        )

    def test_is_expired_true_when_past(self):
        ev = EmailVerification.objects.create(
            user=self.user, code_hash='x',
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertTrue(ev.is_expired)

    def test_is_expired_false_when_future(self):
        ev = EmailVerification.objects.create(
            user=self.user, code_hash='x',
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.assertFalse(ev.is_expired)

    def test_is_consumed_reflects_consumed_at(self):
        ev = EmailVerification.objects.create(
            user=self.user, code_hash='x',
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.assertFalse(ev.is_consumed)
        ev.consumed_at = timezone.now()
        self.assertTrue(ev.is_consumed)


class EmailMessageLogModelTests(TestCase):
    def test_defaults(self):
        log = EmailMessageLog.objects.create(
            to_email='a@example.com', template_name='verification_code',
            subject='Your code',
        )
        self.assertEqual(log.status, 'pending')
        self.assertEqual(log.error, '')
        self.assertIsNone(log.sent_at)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test notifications.tests.test_models -v 2 --keepdb
```
Expected: `ImportError`/`ModuleNotFoundError` — `notifications.models` has no such classes.

- [ ] **Step 3: Write the models**

Create `notifications/models.py`:
```python
from django.conf import settings
from django.db import models
from django.utils import timezone


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

    def __str__(self):
        return f'{self.template_name} -> {self.to_email} ({self.status})'


class EmailVerification(models.Model):
    """6-digit code lifecycle for registration email verification."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='email_verifications',
    )
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', '-created_at'])]

    def __str__(self):
        return f'verification for {self.user_id} (expires {self.expires_at:%Y-%m-%d %H:%M})'

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_consumed(self):
        return self.consumed_at is not None
```

- [ ] **Step 4: Generate and apply the migration**

```bash
python manage.py makemigrations notifications -n initial
python manage.py migrate notifications
```
Expected: creates `notifications/migrations/0001_initial.py` with both models; migrate applies OK.

- [ ] **Step 5: Run test to verify it passes**

```bash
python manage.py test notifications.tests.test_models -v 2 --keepdb
```
Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add notifications/models.py notifications/migrations/ notifications/tests/
git commit -m "feat: EmailMessageLog and EmailVerification models"
```

---

## Task 3: Template registry + email templates

**Files:**
- Create: `notifications/templates_registry.py`
- Create: `notifications/templates/notifications/email/base.html`
- Create: `notifications/templates/notifications/email/verification_code.html`
- Create: `notifications/templates/notifications/email/verification_code.txt`
- Create: `notifications/tests/test_templates.py`

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_templates.py`:
```python
from django.test import TestCase

from notifications.templates_registry import render_template, UnknownTemplate


class RenderTemplateTests(TestCase):
    def test_renders_verification_code(self):
        subject, html, text = render_template(
            'verification_code', {'code': '123456', 'ttl_minutes': 10}
        )
        self.assertIn('123456', html)
        self.assertIn('123456', text)
        self.assertTrue(subject)
        self.assertIn('10', text)  # ttl appears in the copy

    def test_unknown_template_raises(self):
        with self.assertRaises(UnknownTemplate):
            render_template('does_not_exist', {})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test notifications.tests.test_templates -v 2 --keepdb
```
Expected: ImportError — `notifications.templates_registry` doesn't exist.

- [ ] **Step 3: Create the templates**

Create `notifications/templates/notifications/email/base.html`:
```html
<!DOCTYPE html>
<html>
  <body style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#f6f6f8; margin:0; padding:24px;">
    <table align="center" width="100%" style="max-width:480px; background:#ffffff; border-radius:12px; padding:32px;">
      <tr><td style="font-size:20px; font-weight:700; color:#6A1CF6; padding-bottom:16px;">Jokes For</td></tr>
      <tr><td style="font-size:15px; color:#222; line-height:1.5;">{% block content %}{% endblock %}</td></tr>
      <tr><td style="font-size:12px; color:#888; padding-top:24px;">If you didn't request this, you can ignore this email.</td></tr>
    </table>
  </body>
</html>
```

Create `notifications/templates/notifications/email/verification_code.html`:
```html
{% extends "notifications/email/base.html" %}
{% block content %}
  <p>Confirm your email to finish setting up your Jokes For account.</p>
  <p style="font-size:32px; font-weight:700; letter-spacing:6px; color:#111; margin:24px 0;">{{ code }}</p>
  <p>Enter this code in the app. It expires in {{ ttl_minutes }} minutes.</p>
{% endblock %}
```

Create `notifications/templates/notifications/email/verification_code.txt`:
```
Confirm your email to finish setting up your Jokes For account.

Your code: {{ code }}

Enter this code in the app. It expires in {{ ttl_minutes }} minutes.

If you didn't request this, you can ignore this email.
```

- [ ] **Step 4: Create the registry**

Create `notifications/templates_registry.py`:
```python
"""Registry mapping template names to their subject + body templates.

Adding a new email type = one entry here + the two template files. The engine
(service.send_email) and any feature call sites reference templates by name only.
"""
from django.template.loader import render_to_string


class UnknownTemplate(Exception):
    pass


# name -> {subject, html, text}
TEMPLATES = {
    'verification_code': {
        'subject': 'Your Jokes For verification code',
        'html': 'notifications/email/verification_code.html',
        'text': 'notifications/email/verification_code.txt',
    },
}


def render_template(template_name, context):
    """Return (subject, html_body, text_body) for a registered template."""
    entry = TEMPLATES.get(template_name)
    if entry is None:
        raise UnknownTemplate(f"No registered email template '{template_name}'.")
    subject = entry['subject']
    html_body = render_to_string(entry['html'], context)
    text_body = render_to_string(entry['text'], context)
    return subject, html_body, text_body
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python manage.py test notifications.tests.test_templates -v 2 --keepdb
```
Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add notifications/templates_registry.py notifications/templates/ notifications/tests/test_templates.py
git commit -m "feat: email template registry and verification-code templates"
```

---

## Task 4: Engine — service.send_email()

**Files:**
- Create: `notifications/service.py`
- Create: `notifications/tests/test_engine.py`

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_engine.py`:
```python
from django.core import mail
from django.test import TestCase, override_settings

from notifications.models import EmailMessageLog
from notifications.service import send_email, EmailSendError


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SendEmailTests(TestCase):
    def test_sends_and_logs_sent(self):
        log = send_email(
            'to@example.com', 'verification_code',
            {'code': '123456', 'ttl_minutes': 10},
        )
        self.assertEqual(log.status, 'sent')
        self.assertIsNotNone(log.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['to@example.com'])
        self.assertIn('123456', msg.body)  # text body
        # html alternative present
        self.assertTrue(any('123456' in c for c, _ in msg.alternatives))

    def test_failure_marks_log_failed_and_raises(self):
        with override_settings(
            EMAIL_BACKEND='notifications.tests.test_engine.BoomBackend'
        ):
            with self.assertRaises(EmailSendError):
                send_email('to@example.com', 'verification_code',
                           {'code': '000000', 'ttl_minutes': 10})
        log = EmailMessageLog.objects.latest('created_at')
        self.assertEqual(log.status, 'failed')
        self.assertTrue(log.error)


from django.core.mail.backends.base import BaseEmailBackend


class BoomBackend(BaseEmailBackend):
    def send_messages(self, messages):
        raise RuntimeError('provider down')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test notifications.tests.test_engine -v 2 --keepdb
```
Expected: ImportError — `notifications.service` doesn't exist.

- [ ] **Step 3: Write the engine**

Create `notifications/service.py`:
```python
"""The notification engine entry point.

Feature code calls send_email(); it renders a registered template, writes an
EmailMessageLog row, and dispatches through Django's configured EMAIL_BACKEND
(anymail->Resend in prod, console locally, locmem in tests). Synchronous in v1;
the EmailMessageLog.status field is the seam for future async (Cloud Tasks)
dispatch with no schema change.
"""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from .models import EmailMessageLog
from .templates_registry import render_template


class EmailSendError(Exception):
    """Raised when the transport layer fails to send. Caller decides UX."""


def send_email(to_email, template_name, context, user=None):
    """Render, log, and dispatch an email. Returns the EmailMessageLog row."""
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
        msg.send()
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

- [ ] **Step 4: Run test to verify it passes**

```bash
python manage.py test notifications.tests.test_engine -v 2 --keepdb
```
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add notifications/service.py notifications/tests/test_engine.py
git commit -m "feat: notification engine send_email service with outbox logging"
```

---

## Task 5: Verification logic — issue / verify / invalidate

**Files:**
- Create: `notifications/verification.py`
- Create: `notifications/tests/test_verification.py`

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_verification.py`:
```python
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from notifications.models import EmailVerification
from notifications import verification

User = get_user_model()


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_MAX_ATTEMPTS=5,
    EMAIL_VERIFICATION_CODE_TTL_MINUTES=10,
)
class VerificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='c@example.com', email='c@example.com', password='pw',
            is_active=False,
        )

    def test_issue_returns_code_and_persists_hashed(self):
        code = verification.issue_code(self.user)
        self.assertRegex(code, r'^\d{6}$')
        ev = EmailVerification.objects.get(user=self.user)
        # plaintext code must NOT be stored
        self.assertNotEqual(ev.code_hash, code)
        self.assertNotIn(code, ev.code_hash)

    def test_verify_happy_path_consumes(self):
        code = verification.issue_code(self.user)
        ok, err = verification.verify_code(self.user, code)
        self.assertTrue(ok)
        self.assertIsNone(err)
        ev = EmailVerification.objects.get(user=self.user)
        self.assertTrue(ev.is_consumed)

    def test_verify_wrong_code_increments_attempts(self):
        verification.issue_code(self.user)
        ok, err = verification.verify_code(self.user, '000000')
        self.assertFalse(ok)
        self.assertEqual(err, 'incorrect')
        ev = EmailVerification.objects.get(user=self.user)
        self.assertEqual(ev.attempts, 1)

    def test_verify_blocks_after_max_attempts(self):
        verification.issue_code(self.user)
        for _ in range(5):
            verification.verify_code(self.user, '000000')
        ok, err = verification.verify_code(self.user, '000000')
        self.assertFalse(ok)
        self.assertEqual(err, 'too_many_attempts')

    def test_verify_expired_code(self):
        code = verification.issue_code(self.user)
        ev = EmailVerification.objects.get(user=self.user)
        from django.utils import timezone
        from datetime import timedelta
        ev.expires_at = timezone.now() - timedelta(minutes=1)
        ev.save(update_fields=['expires_at'])
        ok, err = verification.verify_code(self.user, code)
        self.assertFalse(ok)
        self.assertEqual(err, 'expired')

    def test_consumed_code_cannot_be_reused(self):
        code = verification.issue_code(self.user)
        verification.verify_code(self.user, code)
        ok, err = verification.verify_code(self.user, code)
        self.assertFalse(ok)
        self.assertEqual(err, 'no_active_code')

    def test_issue_invalidates_prior_unconsumed(self):
        verification.issue_code(self.user)
        verification.issue_code(self.user)
        active = EmailVerification.objects.filter(
            user=self.user, consumed_at__isnull=True
        )
        # only the newest remains active; prior was consumed/invalidated
        self.assertEqual(active.count(), 1)

    def test_issue_and_send_sends_email(self):
        verification.issue_and_send(self.user)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test notifications.tests.test_verification -v 2 --keepdb
```
Expected: ImportError — `notifications.verification` doesn't exist.

- [ ] **Step 3: Write the verification logic**

Create `notifications/verification.py`:
```python
"""6-digit registration code lifecycle: issue, verify, invalidate.

The code is short-lived and attempt-limited, so we use a fast constant-time
SHA-256 digest (not a slow KDF). Security comes from expiry + attempt cap +
resend throttling, not from hash slowness. Plaintext is never stored.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import EmailVerification
from .service import send_email


def _hash(code):
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


def _generate_code():
    # 6 digits, zero-padded, cryptographically random
    return f'{secrets.randbelow(1_000_000):06d}'


def invalidate_codes(user):
    """Mark all of the user's unconsumed codes as consumed (dead)."""
    EmailVerification.objects.filter(
        user=user, consumed_at__isnull=True
    ).update(consumed_at=timezone.now())


def issue_code(user):
    """Invalidate prior codes, create a fresh one, return the plaintext code."""
    invalidate_codes(user)
    code = _generate_code()
    ttl = settings.EMAIL_VERIFICATION_CODE_TTL_MINUTES
    EmailVerification.objects.create(
        user=user,
        code_hash=_hash(code),
        expires_at=timezone.now() + timedelta(minutes=ttl),
    )
    return code


def issue_and_send(user):
    """Issue a code and email it. Returns the EmailMessageLog row."""
    code = issue_code(user)
    return send_email(
        user.email, 'verification_code',
        {'code': code, 'ttl_minutes': settings.EMAIL_VERIFICATION_CODE_TTL_MINUTES},
        user=user,
    )


def verify_code(user, code):
    """Validate a submitted code.

    Returns (ok: bool, error: str|None). Error is one of:
    'no_active_code', 'expired', 'too_many_attempts', 'incorrect'.
    """
    ev = (
        EmailVerification.objects
        .filter(user=user, consumed_at__isnull=True)
        .order_by('-created_at')
        .first()
    )
    if ev is None:
        return False, 'no_active_code'
    if ev.is_expired:
        return False, 'expired'
    if ev.attempts >= settings.EMAIL_VERIFICATION_MAX_ATTEMPTS:
        return False, 'too_many_attempts'

    if not hmac.compare_digest(ev.code_hash, _hash(code)):
        ev.attempts += 1
        ev.save(update_fields=['attempts'])
        return False, 'incorrect'

    ev.consumed_at = timezone.now()
    ev.save(update_fields=['consumed_at'])
    return True, None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python manage.py test notifications.tests.test_verification -v 2 --keepdb
```
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add notifications/verification.py notifications/tests/test_verification.py
git commit -m "feat: 6-digit verification code issue/verify/invalidate logic"
```

---

## Task 6: Gated registration flow

**Files:**
- Modify: `jokes/views.py` (`CookieRegisterView`)
- Create: `notifications/tests/test_registration_flow.py`

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_registration_flow.py`:
```python
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase

from notifications.models import EmailVerification

User = get_user_model()

REG_URL = '/api/v1/auth/registration/'


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_REQUIRED=True,
)
class GatedRegistrationTests(APITestCase):
    def test_register_creates_inactive_user_no_tokens(self):
        resp = self.client.post(REG_URL, {
            'email': 'new@example.com',
            'password1': 'sup3rsecret!', 'password2': 'sup3rsecret!',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['email'], 'new@example.com')
        self.assertNotIn('access', body)
        self.assertNotIn('user', body)
        # no auth cookies set
        self.assertNotIn('jokes-access-token', resp.cookies)

        user = User.objects.get(email='new@example.com')
        self.assertFalse(user.is_active)
        self.assertEqual(EmailVerification.objects.filter(user=user).count(), 1)
        self.assertEqual(len(mail.outbox), 1)


@override_settings(EMAIL_VERIFICATION_REQUIRED=False)
class UngatedRegistrationTests(APITestCase):
    def test_register_keeps_legacy_behavior_active_user_with_cookies(self):
        resp = self.client.post(REG_URL, {
            'email': 'legacy@example.com',
            'password1': 'sup3rsecret!', 'password2': 'sup3rsecret!',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        user = User.objects.get(email='legacy@example.com')
        self.assertTrue(user.is_active)
        self.assertIn('jokes-access-token', resp.cookies)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test notifications.tests.test_registration_flow -v 2 --keepdb
```
Expected: the gated test fails (user is active, tokens present, no verification row) — the new branch isn't implemented.

- [ ] **Step 3: Modify CookieRegisterView**

In `jokes/views.py`, the current `CookieRegisterView` (around line 629) is:
```python
class CookieRegisterView(RegisterView):
    # dj-rest-auth's RegisterView returns JWTs in the body but doesn't write
    # cookies — only LoginView does. Mirror LoginView's cookie-setting here so
    # the browser is authenticated immediately after sign-up, no extra login round-trip.
    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        if (
            response.status_code == status.HTTP_201_CREATED
            and rest_auth_settings.USE_JWT
            and getattr(self, 'access_token', None)
            and getattr(self, 'refresh_token', None)
        ):
            set_jwt_cookies(response, self.access_token, self.refresh_token)
        return response
```
Replace the whole class with:
```python
class CookieRegisterView(RegisterView):
    """Registration with two modes, switched by EMAIL_VERIFICATION_REQUIRED.

    Gated (True): create an inactive user, issue + email a 6-digit code, return
    201 {detail, email} with NO tokens. The user authenticates only after
    POST /auth/verify-email/.

    Legacy (False): original behavior — active user, JWT cookies on 201. Kept so
    the feature can be deployed before a real email provider is live.
    """

    def create(self, request, *args, **kwargs):
        if not settings.EMAIL_VERIFICATION_REQUIRED:
            response = super().create(request, *args, **kwargs)
            if (
                response.status_code == status.HTTP_201_CREATED
                and rest_auth_settings.USE_JWT
                and getattr(self, 'access_token', None)
                and getattr(self, 'refresh_token', None)
            ):
                set_jwt_cookies(response, self.access_token, self.refresh_token)
            return response

        # Gated flow.
        from notifications import verification

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save(request)
        user.is_active = False
        user.save(update_fields=['is_active'])

        verification.issue_and_send(user)

        return Response(
            {'detail': 'Verification code sent to your email.', 'email': user.email},
            status=status.HTTP_201_CREATED,
        )
```

Confirm the imports `settings`, `status`, `Response`, `rest_auth_settings`, `set_jwt_cookies`, `RegisterView` are already present at the top of `jokes/views.py` (they are — see lines 18-20 and existing usage). No new top-level import needed; `verification` is imported locally to avoid a circular import at module load.

- [ ] **Step 4: Run test to verify it passes**

```bash
python manage.py test notifications.tests.test_registration_flow -v 2 --keepdb
```
Expected: both gated and legacy tests pass.

- [ ] **Step 5: Commit**

```bash
git add jokes/views.py notifications/tests/test_registration_flow.py
git commit -m "feat: gated registration flow behind EMAIL_VERIFICATION_REQUIRED"
```

---

## Task 7: verify-email + resend-verification endpoints

**Files:**
- Create: `notifications/serializers.py`, `notifications/throttles.py`, `notifications/views.py`, `notifications/urls.py`
- Modify: `JokesForProject/urls.py`
- Create: `notifications/tests/test_verify_resend.py`

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_verify_resend.py`:
```python
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase

from notifications import verification
from notifications.models import EmailVerification

User = get_user_model()

VERIFY_URL = '/api/v1/auth/verify-email/'
RESEND_URL = '/api/v1/auth/resend-verification/'


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_REQUIRED=True,
)
class VerifyEmailEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='p@example.com', email='p@example.com', password='pw',
            is_active=False,
        )

    def _issue(self):
        # issue_code returns the plaintext; mirror what registration does
        return verification.issue_code(self.user)

    def test_verify_happy_path_activates_and_sets_cookies(self):
        code = self._issue()
        resp = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': code}, format='json'
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('user', resp.json())
        self.assertIn('jokes-access-token', resp.cookies)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_verify_wrong_code(self):
        self._issue()
        resp = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': '000000'}, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('code', resp.json())

    def test_verify_expired_code(self):
        code = self._issue()
        from django.utils import timezone
        from datetime import timedelta
        ev = EmailVerification.objects.get(user=self.user)
        ev.expires_at = timezone.now() - timedelta(minutes=1)
        ev.save(update_fields=['expires_at'])
        resp = self.client.post(
            VERIFY_URL, {'email': self.user.email, 'code': code}, format='json'
        )
        self.assertEqual(resp.status_code, 400)

    def test_verify_unknown_email_uniform_400(self):
        resp = self.client.post(
            VERIFY_URL, {'email': 'nobody@example.com', 'code': '123456'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_REQUIRED=True,
)
class ResendEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='r@example.com', email='r@example.com', password='pw',
            is_active=False,
        )

    def test_resend_sends_new_code_and_invalidates_prior(self):
        verification.issue_code(self.user)
        resp = self.client.post(
            RESEND_URL, {'email': self.user.email}, format='json'
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(mail.outbox), 1)
        active = EmailVerification.objects.filter(
            user=self.user, consumed_at__isnull=True
        )
        self.assertEqual(active.count(), 1)

    def test_resend_unknown_email_uniform_200(self):
        resp = self.client.post(
            RESEND_URL, {'email': 'nobody@example.com'}, format='json'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test notifications.tests.test_verify_resend -v 2 --keepdb
```
Expected: 404s / routing errors — the endpoints don't exist.

- [ ] **Step 3: Create serializers**

Create `notifications/serializers.py`:
```python
from rest_framework import serializers


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.RegexField(r'^\d{6}$')


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()
```

- [ ] **Step 4: Create the throttle**

Create `notifications/throttles.py`:
```python
from rest_framework.throttling import ScopedRateThrottle


class ResendThrottle(ScopedRateThrottle):
    """Per-email throttle for resend-verification (scope: verification_resend)."""
    scope = 'verification_resend'

    def get_cache_key(self, request, view):
        email = (request.data.get('email') or '').lower()
        if not email:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': email}
```

- [ ] **Step 5: Create the views**

Create `notifications/views.py`:
```python
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from dj_rest_auth.jwt_auth import set_jwt_cookies

from . import verification
from .serializers import VerifyEmailSerializer, ResendVerificationSerializer
from .throttles import ResendThrottle

User = get_user_model()

# Maps verify_code() error strings to user-facing field errors.
_VERIFY_ERRORS = {
    'no_active_code': ('code', 'No active code. Request a new one.'),
    'expired': ('code', 'This code has expired. Request a new one.'),
    'too_many_attempts': ('code', 'Too many attempts. Request a new code.'),
    'incorrect': ('code', 'Incorrect code.'),
}


class VerifyEmailView(APIView):
    """POST /auth/verify-email/ {email, code} -> activate user + set JWT cookies."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        code = serializer.validated_data['code']

        # Uniform 400 on unknown email (anti-enumeration: same shape as wrong code).
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return Response({'code': ['Incorrect code.']},
                            status=status.HTTP_400_BAD_REQUEST)

        ok, err = verification.verify_code(user, code)
        if not ok:
            field, msg = _VERIFY_ERRORS[err]
            return Response({field: [msg]}, status=status.HTTP_400_BAD_REQUEST)

        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        response = Response(
            {'user': {'id': user.id, 'email': user.email}},
            status=status.HTTP_200_OK,
        )
        set_jwt_cookies(response, access, refresh)
        return response


class ResendVerificationView(APIView):
    """POST /auth/resend-verification/ {email} -> new code if the account exists."""

    permission_classes = [AllowAny]
    throttle_classes = [ResendThrottle]

    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        # Only send for an existing, not-yet-active account. Always return the
        # same response (anti-enumeration).
        user = User.objects.filter(email__iexact=email, is_active=False).first()
        if user is not None:
            verification.issue_and_send(user)

        return Response(
            {'detail': 'If that email needs verification, a new code has been sent.'},
            status=status.HTTP_200_OK,
        )
```

- [ ] **Step 6: Create the app urls and include them**

Create `notifications/urls.py`:
```python
from django.urls import path

from .views import VerifyEmailView, ResendVerificationView

urlpatterns = [
    path('verify-email/', VerifyEmailView.as_view(), name='verify-email'),
    path('resend-verification/', ResendVerificationView.as_view(), name='resend-verification'),
]
```

In `JokesForProject/urls.py`, find the auth includes block:
```python
    path('api/v1/auth/google/', GoogleLogin.as_view(), name='google_login'),
```
Add immediately after it:
```python
    path('api/v1/auth/', include('notifications.urls')),
```
(`include` is already imported at the top of `JokesForProject/urls.py`.)

- [ ] **Step 7: Run test to verify it passes**

```bash
python manage.py test notifications.tests.test_verify_resend -v 2 --keepdb
```
Expected: 6 tests pass.

- [ ] **Step 8: Commit**

```bash
git add notifications/serializers.py notifications/throttles.py notifications/views.py notifications/urls.py JokesForProject/urls.py notifications/tests/test_verify_resend.py
git commit -m "feat: verify-email and resend-verification endpoints"
```

---

## Task 8: Google OAuth exemption

**Files:**
- Modify: `jokes/views.py` (only if investigation shows social users are created inactive)
- Create: `notifications/tests/test_google_exemption.py`

- [ ] **Step 1: Write the test that documents the required behavior**

Create `notifications/tests/test_google_exemption.py`:
```python
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from notifications.models import EmailVerification

User = get_user_model()


@override_settings(EMAIL_VERIFICATION_REQUIRED=True)
class GoogleExemptionTests(TestCase):
    """A user created via the social flow must be active and have no code.

    We simulate the post-condition of GoogleLogin (allauth creates the user)
    rather than driving the full OAuth exchange, which needs Google.
    """

    def test_social_user_is_active_and_has_no_verification(self):
        # allauth's SocialLogin path creates an active user by default.
        user = User.objects.create_user(
            username='g@example.com', email='g@example.com', is_active=True,
        )
        # No verification code should ever be issued for social signups.
        self.assertEqual(EmailVerification.objects.filter(user=user).count(), 0)
        self.assertTrue(user.is_active)
```

- [ ] **Step 2: Run the test**

```bash
python manage.py test notifications.tests.test_google_exemption -v 2 --keepdb
```
Expected: PASS immediately. allauth's social login creates active users and our gated flow only runs inside `CookieRegisterView` (the email/password path) — `GoogleLogin` never calls `verification.issue_and_send`, so social users are exempt by construction.

- [ ] **Step 3: Confirm GoogleLogin does not gate (read-only verification)**

```bash
grep -n -A 6 "class GoogleLogin" jokes/views.py
```
Expected: `GoogleLogin` only sets `adapter_class`, `callback_url`, `client_class` — no verification call. No code change needed. This task documents and locks the exemption with a test; if the grep ever shows gating logic added to GoogleLogin, that is a regression.

- [ ] **Step 4: Commit**

```bash
git add notifications/tests/test_google_exemption.py
git commit -m "test: lock Google OAuth exemption from email verification"
```

---

## Task 9: Read-only admin for audit

**Files:**
- Create: `notifications/admin.py`

- [ ] **Step 1: Write the admin**

Create `notifications/admin.py`:
```python
from django.contrib import admin

from .models import EmailMessageLog, EmailVerification


@admin.register(EmailMessageLog)
class EmailMessageLogAdmin(admin.ModelAdmin):
    list_display = ['to_email', 'template_name', 'status', 'created_at', 'sent_at']
    list_filter = ['status', 'template_name', 'created_at']
    search_fields = ['to_email', 'subject', 'provider_message_id']
    readonly_fields = [f.name for f in EmailMessageLog._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'expires_at', 'consumed_at', 'attempts', 'created_at']
    list_filter = ['created_at', 'expires_at']
    search_fields = ['user__email']
    readonly_fields = [f.name for f in EmailVerification._meta.fields]

    def has_add_permission(self, request):
        return False
```

- [ ] **Step 2: Verify admin loads**

```bash
python manage.py check
```
Expected: no issues.

- [ ] **Step 3: Run the full notifications suite**

```bash
python manage.py test notifications -v 2 --keepdb 2>&1 | tail -8
```
Expected: all tests from Tasks 2-8 pass together (models 4 + templates 2 + engine 2 + verification 8 + registration 3 + verify/resend 6 + google 1 = 26).

- [ ] **Step 4: Run the full project suite for regressions**

```bash
python manage.py test -v 1 --keepdb 2>&1 | tail -8
```
Expected: notifications tests pass and existing `jokes` tests still pass (registration legacy mode preserved by the env flag default).

- [ ] **Step 5: Commit**

```bash
git add notifications/admin.py
git commit -m "feat: read-only admin for email logs and verifications"
```

---

## Self-Review

**Spec coverage:**
- §4 architecture (3 layers) → Tasks 3 (templates), 4 (engine), 1 (transport config)
- §5 app structure → all tasks create the documented files
- §6 data model → Task 2 (both models, hashing in Task 5)
- §7 engine service → Task 4
- §7 code hashing (SHA-256 + compare_digest) → Task 5 `_hash` + `verify_code`
- §8 registration hard gate → Task 6; verify/resend → Task 7
- §8 Google exemption → Task 8
- §9 abuse controls: max attempts → Task 5; resend throttle → Task 7 (`ResendThrottle`, scope added Task 1); anti-enumeration → Task 7 uniform responses; send-failure logging → Task 4
- §10 config/secrets/env flag → Task 1
- §11 API surface → Tasks 6, 7
- §12 testing → every task is TDD
- §13 deploy sequencing → realized as `EMAIL_VERIFICATION_REQUIRED` flag (Task 1 + Task 6 legacy branch), with legacy mode preserving current behavior until Resend is live

**Placeholder scan:** No TBD/TODO; every code step has full code; every command has expected output.

**Type/name consistency:**
- `send_email(to_email, template_name, context, user=None)` defined Task 4, called identically in Task 5 (`issue_and_send`).
- `verify_code(user, code) -> (ok, err)` with errors `{no_active_code, expired, too_many_attempts, incorrect}` defined Task 5, mapped in Task 7 `_VERIFY_ERRORS` (all four keys present).
- `issue_code` / `issue_and_send` / `invalidate_codes` names consistent across Tasks 5, 6, 7.
- `EmailMessageLog` / `EmailVerification` field names consistent across Tasks 2, 4, 5, 9.
- Throttle scope `verification_resend` defined in settings (Task 1) matches `ResendThrottle.scope` (Task 7).
- Cookie name `jokes-access-token` (from REST_AUTH config) asserted in Tasks 6, 7 — matches settings.py:283.
