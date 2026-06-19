# Monetization Engine — Foundational Slice Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Ship the flexible monetization ENGINE now, before pricing exists: a new `billing` app with editable Plan/Subscription/UsageCounter/ProcessedStripeEvent models, an entitlements resolver choke-point with FREE-tier defaults, env-gated (dormant-if-unset) Stripe checkout/portal/webhook endpoints processed synchronously with lazy quota resets (no worker), Django admin self-service with a Push-to-Stripe action, seeded EXAMPLE plans with PLACEHOLDER prices, and two real demo gates (Mystery Box quota + creator-analytics feature) — all behind BILLING_ENABLED, fully TDD, Stripe mocked, no Wave 1 regressions.

**Architecture:** New Django app `billing/` modeled on the `creator_insights` app shape. Source of truth for business config is OUR DB (Plan.features/limits JSON + money fields); Stripe owns only Product/Price/charge via one-way push. Single resolver `billing/entitlements.py` (mirrors `jokes/serving.py:allowed_tiers`) is the only entitlement choke-point; it reads the user's effective Plan (active/trialing Subscription's plan, else is_default FREE plan) against a KNOWN_FEATURES/KNOWN_LIMITS registry that supplies safe free-tier defaults (fail open for unsubscribed + anon). Quotas reset LAZILY via period_key get_or_create (no cron); row-derivable caps count rows by date bucket. Stripe access through `billing/stripe_gateway.py`, env-gated like Sentry (dormant if STRIPE_SECRET_KEY unset) and flag-gated by BILLING_ENABLED like EMAIL_VERIFICATION_REQUIRED. Webhook is public + CSRF-exempt + signature-verified + idempotent on event.id, doing one fast synchronous UPSERT (correct no-worker adaptation). Endpoints under api/v1/billing/. Demo gates touch jokes/views.py (Mystery Box, both call sites) and creator_insights/views.py (HasFeature permission). All tests use the Django runner against local Postgres with Stripe SDK fully mocked — no live calls. is_premium kept as a webhook-synced read-cache, never the entitlement truth; allowed_tiers stays strictly age-based.

---

**Files:**

| Action | Path | Responsibility |
|---|---|---|
| edit | `requirements.txt` | Add `stripe` (pinned to a version whose default API matches STRIPE_API_VERSION 2026-05-27.dahlia). Not currently installed. |
| edit | `JokesForProject/settings.py` | Add STRIPE_SECRET_KEY/PUBLISHABLE_KEY/WEBHOOK_SECRET, STRIPE_API_VERSION (pinned), BILLING_ENABLED flag, BILLING_SUCCESS_URL/CANCEL_URL/PORTAL_RETURN_URL — all os.getenv with safe defaults (mirror RESEND/EMAIL_*/SENTRY). Append 'billing' to INSTALLED_APPS. |
| edit | `.env.example` | Add commented placeholders for all STRIPE_* keys, BILLING_ENABLED=false, and the billing redirect URLs, with notes (test vs live, per-endpoint whsec_, leave empty = dormant). |
| edit | `JokesForProject/urls.py` | Add path('api/v1/billing/', include('billing.urls')). |
| create | `billing/__init__.py` | Empty package marker. |
| create | `billing/apps.py` | BillingConfig(AppConfig) with default_auto_field BigAutoField, name='billing' (copy creator_insights/apps.py). |
| create | `billing/models.py` | Plan (slug,name,description,is_active,is_public,is_default,sort_order,interval,amount_cents,currency,stripe_product_id,stripe_price_id,features JSON,limits JSON), Subscription (OneToOne user, plan FK PROTECT, stripe ids, status, current_period_start/end, cancel_at_period_end, ACTIVE_STATUSES, is_entitled()), UsageCounter (user,key,period_key,count; unique_together), ProcessedStripeEvent (event_id unique, event_type, created_at). |
| create | `billing/entitlements.py` | KNOWN_FEATURES/KNOWN_LIMITS registries (free defaults). effective_plan(user), has_feature(user,key), get_limit(user,key,default=None), get_usage(user,key,period), check_and_consume_quota(user,key,period,amount=1)->QuotaResult, check_quota_by_count(user,key,count_callable,period). Fail open to FREE for no-sub/anon. Lazy period_key reset via get_or_create. |
| create | `billing/stripe_gateway.py` | Thin env-gated wrapper: is_enabled() (STRIPE_SECRET_KEY set), configured stripe client with pinned api_version, get_or_create_customer(user), create_checkout_session(...), create_portal_session(...), construct_event(payload,sig). Raises BillingUnavailable when dormant. |
| create | `billing/permissions.py` | HasFeature(feature_key) factory returning a DRF BasePermission whose has_permission reads entitlements.has_feature(request.user, key). Mirrors creator_insights IsCreator. Includes a clear `message`. |
| create | `billing/serializers.py` | PlanPublicSerializer, MySubscriptionSerializer, EntitlementsSerializer (features/limits/usage/plan). |
| create | `billing/webhooks.py` | handle_event(event): idempotency check on ProcessedStripeEvent; dispatch checkout.session.completed / customer.subscription.created\|updated\|deleted / invoice.paid / invoice.payment_failed to order-independent UPSERT helpers that resolve plan from price_id, sync Subscription mirror + is_premium, stamp period anchor; record event.id; all in one transaction. |
| create | `billing/views.py` | CheckoutSessionView (POST, auth), PortalSessionView (POST, auth), StripeWebhookView (POST, AllowAny, csrf_exempt, raw body, construct_event->400 on sig error, delegates to webhooks.handle_event, returns 200), MySubscriptionView (GET, auth), EntitlementsView (GET, auth), PlansView (GET, public). |
| create | `billing/urls.py` | Routes: checkout-session, portal-session, webhook, my-subscription, entitlements, plans. |
| create | `billing/admin.py` | PlanAdmin (list_display incl amount/flags, list_editable for is_active/is_public/amount_cents/sort_order, clean() warns on unknown JSON keys, 'Push to Stripe' idempotent action). SubscriptionAdmin (read-mostly, search). UsageCounterAdmin + ProcessedStripeEventAdmin (read-only audit). |
| create | `billing/migrations/0001_initial.py` | Schema for the four models. |
| create | `billing/migrations/0002_seed_plans.py` | Idempotent data migration get_or_create-ing EXAMPLE plans Free/Supporter/Creator Pro with PLACEHOLDER amounts and blank stripe ids; reverse is no-op-safe. |
| create | `billing/tests/__init__.py` | Test package marker. |
| create | `billing/tests/test_entitlements.py` | Resolver + FREE-default + registry tests. |
| create | `billing/tests/test_quota_lazy_reset.py` | UsageCounter lazy period_key reset + check_and_consume_quota tests (no cron). |
| create | `billing/tests/test_checkout_portal.py` | Checkout/portal endpoints with Stripe mocked + dormant-mode 503. |
| create | `billing/tests/test_webhook.py` | Signature verify (400), idempotency, each event type UPSERT, plan downgrade on delete. |
| create | `billing/tests/test_gating.py` | Mystery Box quota gate (both views) + creator-analytics HasFeature gate + Wave 1 non-regression. |
| edit | `jokes/views.py` | In MysteryBoxStatusView.get and MysteryBoxRollView.post, replace literal MysteryBoxRoll.MAX_DAILY_ROLLS with entitlements.get_limit(request.user,'mystery_box_rolls_per_day', default=MysteryBoxRoll.MAX_DAILY_ROLLS) at BOTH sites so cap and status agree. |
| edit | `creator_insights/views.py` | Append billing.permissions.HasFeature('creator_analytics') to CreatorInsightsView.permission_classes (additive, after IsCreator). |

### Task 1: Task 1 — Scaffold billing app + env config (dormant, no behavior change)

**Files:** `requirements.txt`, `JokesForProject/settings.py`, `.env.example`, `JokesForProject/urls.py`, `billing/__init__.py`, `billing/apps.py`, `billing/urls.py`, `billing/views.py`

- [ ] **Step 1 (test): Write test asserting the app is installed and the URL include resolves, and that with no STRIPE_SECRET_KEY the checkout endpoint returns 503 (dormant) rather than 500.**

```
# billing/tests/test_checkout_portal.py (initial stub)
from django.urls import reverse, resolve
from rest_framework.test import APITestCase
class DormantBillingTests(APITestCase):
    def test_checkout_dormant_returns_503_when_no_keys(self):
        # user authed, settings.STRIPE_SECRET_KEY == '' -> 503 billing_unavailable
        ...
```

  - Expected: FAIL initially (app/urls/view not present).

- [ ] **Step 2 (implement): Add `stripe` to requirements; add STRIPE_*/BILLING_* settings via os.getenv (mirror Sentry/EMAIL_*); append 'billing' to INSTALLED_APPS; add the billing URL include; add .env.example placeholders.**

  - Expected: Settings import cleanly; stripe importable in venv.

- [ ] **Step 3 (implement): Create billing/apps.py, urls.py, and a minimal views.py where CheckoutSessionView/PortalSessionView return 503 when stripe_gateway.is_enabled() is False (dormant-if-unset, like Sentry).**

  - Expected: Dormant test passes.

- [ ] **Step 4 (verify): Run the dormant test.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test billing.tests.test_checkout_portal --keepdb
```

  - Expected: PASS; existing suites unaffected.

### Task 2: Task 2 — Models + migrations + seed EXAMPLE plans (PLACEHOLDER prices)

**Files:** `billing/models.py`, `billing/migrations/0001_initial.py`, `billing/migrations/0002_seed_plans.py`, `billing/tests/test_entitlements.py`

- [ ] **Step 1 (test): Write tests: exactly one is_default Plan exists after seed; seed creates free/supporter/creator_pro; Subscription.is_entitled() true only for active/trialing; UsageCounter unique_together enforced.**

  - Expected: FAIL (models absent).

- [ ] **Step 2 (implement): Implement Plan, Subscription, UsageCounter, ProcessedStripeEvent per the design. makemigrations -> 0001_initial.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py makemigrations billing
```

  - Expected: 0001_initial generated; no collision with notifications cache-table / pgtrigger migrations.

- [ ] **Step 3 (implement): Write 0002_seed_plans data migration: idempotent get_or_create by slug for Free (is_default, amount None), Supporter ($5 PLACEHOLDER), Creator Pro ($15 PLACEHOLDER), blank stripe ids, features/limits per seed. Reverse = safe no-op.**

  - Expected: Migration applies on local Postgres; re-running is a no-op.

- [ ] **Step 4 (verify): migrate + run model/seed tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test billing.tests.test_entitlements --keepdb
```

  - Expected: PASS.

### Task 3: Task 3 — Entitlements resolver + lazy quota (the choke-point)

**Files:** `billing/entitlements.py`, `billing/tests/test_entitlements.py`, `billing/tests/test_quota_lazy_reset.py`

- [ ] **Step 1 (test): Tests: anon + no-Subscription user resolve to FREE plan; has_feature/get_limit return registry defaults for unknown/missing keys; effective_plan returns active sub's plan, FREE when status=canceled; check_and_consume_quota blocks at limit and returns remaining/reset_at; lazy reset — same key new period_key starts at 0 with no scheduled job; check_quota_by_count compares live row count.**

```
def test_quota_resets_lazily_on_period_rollover(self):
    # consume to limit in period 'YYYY-MM'; simulate now() in next month;
    # get_or_create lands on fresh row count=0 -> allowed again. No cron called.
    ...
```

  - Expected: FAIL (resolver absent).

- [ ] **Step 2 (implement): Implement KNOWN_FEATURES/KNOWN_LIMITS, effective_plan, has_feature, get_limit, get_usage, check_and_consume_quota (period_key from now(), get_or_create, F()-increment), check_quota_by_count, QuotaResult. Fail open to FREE everywhere.**

  - Expected: Pure functions, single Plan row read on hot path, no joins.

- [ ] **Step 3 (verify): Run entitlement + quota tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test billing.tests.test_entitlements billing.tests.test_quota_lazy_reset --keepdb
```

  - Expected: PASS.

### Task 4: Task 4 — Stripe gateway + checkout/portal endpoints (mocked, env-gated)

**Files:** `billing/stripe_gateway.py`, `billing/views.py`, `billing/serializers.py`, `billing/urls.py`, `billing/tests/test_checkout_portal.py`

- [ ] **Step 1 (test): With stripe mocked and STRIPE_SECRET_KEY set: checkout-session returns the mocked session.url, creates+stores stripe_customer_id, passes client_reference_id+metadata, rejects plans without stripe_price_id; portal-session returns mocked portal url. With keys unset: both 503. my-subscription/entitlements/plans return correct shapes.**

```
from unittest.mock import patch
@patch('billing.stripe_gateway.stripe')
def test_checkout_returns_session_url(self, mstripe):
    mstripe.checkout.Session.create.return_value.url = 'https://stripe.test/cs'
    ...
```

  - Expected: FAIL.

- [ ] **Step 2 (implement): Implement stripe_gateway (is_enabled, configured client w/ pinned api_version, get_or_create_customer, create_checkout_session, create_portal_session, construct_event). Implement the six views + serializers + urls. No live calls; gateway is the only stripe import.**

  - Expected: Endpoints work against mocked stripe.

- [ ] **Step 3 (verify): Run checkout/portal tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test billing.tests.test_checkout_portal --keepdb
```

  - Expected: PASS; zero network calls (mock asserts).

### Task 5: Task 5 — Webhook: signature verify + idempotency + UPSERT (no worker)

**Files:** `billing/webhooks.py`, `billing/views.py`, `billing/tests/test_webhook.py`

- [ ] **Step 1 (test): Tests: bad signature -> 400 (patch construct_event to raise SignatureVerificationError); duplicate event.id -> 200 short-circuit, no second UPSERT; checkout.session.completed links customer+sub+plan and sets is_premium; subscription.updated re-resolves plan from price_id; subscription.deleted downgrades to FREE + is_premium False; invoice.payment_failed marks past_due; out-of-order updated-before-created still converges. Webhook view is AllowAny + csrf_exempt + reads raw body.**

```
@patch('billing.stripe_gateway.stripe.Webhook.construct_event')
def test_bad_signature_returns_400(self, m):
    from stripe.error import SignatureVerificationError
    m.side_effect = SignatureVerificationError('bad','sig')
    resp = self.client.post('/api/v1/billing/webhook', data=b'{}', content_type='application/json')
    self.assertEqual(resp.status_code, 400)
```

  - Expected: FAIL.

- [ ] **Step 2 (implement): Implement webhooks.handle_event (idempotency on ProcessedStripeEvent, order-independent dispatch, single transactional UPSERT, plan-from-price resolution, is_premium sync, period anchor stamp, optional quick dunning email via notifications.service.send_email). Implement StripeWebhookView (raw request.body, construct_event->400, delegate, 200).**

  - Expected: Synchronous fast handler; no worker; all paths covered.

- [ ] **Step 3 (verify): Run webhook tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test billing.tests.test_webhook --keepdb
```

  - Expected: PASS.

### Task 6: Task 6 — Admin self-service (editable plans/limits + Push to Stripe)

**Files:** `billing/admin.py`, `billing/permissions.py`, `billing/tests/test_gating.py`

- [ ] **Step 1 (test): Tests: editing a Plan.limits value is reflected by get_limit on next call (live, no deploy); PlanAdmin.clean warns on unknown JSON keys; 'Push to Stripe' action is idempotent (skips when stripe_price_id already matches amount/interval; creates new Price + archives old on amount change) with stripe mocked; HasFeature('x') BasePermission allows iff has_feature true.**

  - Expected: FAIL (admin/permission absent).

- [ ] **Step 2 (implement): Implement billing/admin.py (PlanAdmin with list_editable, clean(), Push-to-Stripe action via stripe_gateway; read-only Subscription/UsageCounter/ProcessedStripeEvent admins) and billing/permissions.py HasFeature factory.**

  - Expected: Business can flip features/limits/prices from admin; price push idempotent.

- [ ] **Step 3 (verify): Run admin/permission tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test billing.tests.test_gating.AdminEditabilityTests --keepdb
```

  - Expected: PASS.

### Task 7: Task 7 — Demo gates: Mystery Box quota + creator analytics feature (no Wave 1 regression)

**Files:** `jokes/views.py`, `creator_insights/views.py`, `billing/tests/test_gating.py`

- [ ] **Step 1 (test): Tests: with FREE plan, Mystery Box status max_per_day==3 and the 429 fires after 3 (unchanged behavior); raising the FREE plan's mystery_box_rolls_per_day to 10 in DB lets a 4th roll succeed and status shows 10 — both views agree. creator analytics: with creator_analytics default True (seed) an existing creator still gets 200 (Wave 1 intact); flipping the FREE feature to False yields 403 for free users, 200 for an entitled plan. allowed_tiers unchanged (age gate not widened).**

```
def test_mystery_box_limit_is_plan_driven_both_views(self):
    # default 3 -> 4th roll 429; bump FREE limit to 10 -> 4th roll 200; status.max_per_day==10
    ...
```

  - Expected: FAIL until views read entitlements.

- [ ] **Step 2 (implement): Edit jokes/views.py: in MysteryBoxStatusView.get and MysteryBoxRollView.post replace MysteryBoxRoll.MAX_DAILY_ROLLS with entitlements.get_limit(request.user,'mystery_box_rolls_per_day', default=MysteryBoxRoll.MAX_DAILY_ROLLS) at BOTH sites. Edit creator_insights/views.py: append HasFeature('creator_analytics') to permission_classes.**

  - Expected: Constant becomes free-tier fallback; gates are plan-driven.

- [ ] **Step 3 (verify): Run gating tests plus the full jokes + creator_insights suites for non-regression.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test billing jokes creator_insights --keepdb
```

  - Expected: PASS; Wave 1 behavior unchanged with seed defaults.

### Task 8: Task 8 — Full suite + dark-deploy sanity

**Files:** `billing/tests/test_entitlements.py`, `billing/tests/test_quota_lazy_reset.py`, `billing/tests/test_checkout_portal.py`, `billing/tests/test_webhook.py`, `billing/tests/test_gating.py`

- [ ] **Step 1 (verify): Run the entire test suite to confirm no regressions anywhere and that billing works with keys unset (dormant) and with BILLING_ENABLED false.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test --keepdb
```

  - Expected: All green. App runs fully with Stripe dormant; entitlements resolve to FREE.

- [ ] **Step 2 (implement): Commit in logical chunks with plain messages (no footers), e.g. 'billing: add config-driven Plan/Subscription/UsageCounter models', 'billing: entitlement resolver with free-tier defaults + lazy quota', 'billing: Stripe checkout/portal/webhook (test-mode, env-gated)', 'billing: admin self-service + Push-to-Stripe', 'billing: gate Mystery Box quota and creator analytics'.**

  - Expected: Branch ready for review; shippable dark.
