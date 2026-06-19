# Monetization Engine — Config-Driven Entitlements + Stripe (Design)

# Monetization System — Design Doc (config-driven, admin-editable)

## 0. Goal & flexibility principle

Build a subscription/monetization system for JokesForPeople that gates **feature access** and **numeric quotas** for both creators and regular users, via **Stripe** (Checkout + Customer Portal + webhooks).

**The whole point is flexibility.** There is no fixed pricing/tier spec. Plans, prices, feature flags, and numeric limits are **DATA, not code**. The business must be able to: add/rename/retire plans, change prices, flip a feature on/off, raise/lower a limit — **entirely from Django admin, reflected live on the next request, with no deploy.**

Three rules make this real:
1. **Our DB is the source of truth for business config** (names, copy, feature flags, numeric limits, visibility). Stripe owns **only money mechanics** (Product + Price + the charge). One-way push DB -> Stripe.
2. **A single resolver choke-point** — `billing/entitlements.py` — is the only place anything asks "can this user do X / what's their limit for Y." It mirrors the existing `jokes/serving.py:allowed_tiers()` pattern. Every gate reads through it, so an admin edit is reflected everywhere at once.
3. **Fail OPEN to a FREE default.** Any user with no subscription (the vast majority pre-launch, plus anon) resolves cleanly to the FREE plan. Gating never 403/429s everyone by accident.

This ships **dark** behind `BILLING_ENABLED` (mirrors `EMAIL_VERIFICATION_REQUIRED`) and **dormant** when Stripe keys are unset (mirrors `SENTRY_DSN`), so it can be merged, deployed, and demoed before pricing exists.

---

## 1. Where it lives

A **new `billing` Django app**, structured by copying the `creator_insights` app shape (the house template):

```
billing/
  __init__.py
  apps.py
  models.py            # Plan, Subscription, ProcessedStripeEvent, UsageCounter
  entitlements.py      # the single resolver choke-point (has_feature/get_limit/check_and_consume_quota)
  stripe_gateway.py    # thin wrapper around the stripe SDK (env-gated, dormant if unset)
  permissions.py       # HasFeature(key) DRF BasePermission (mirrors IsCreator)
  serializers.py       # MySubscriptionSerializer / EntitlementsSerializer
  views.py             # checkout-session, portal-session, webhook, my-subscription
  webhooks.py          # signature verify + idempotency + event dispatch (UPSERT)
  urls.py
  admin.py             # Plan/Subscription/UsageCounter/event admin (business self-service)
  migrations/
    0001_initial.py
    0002_seed_plans.py # data migration: EXAMPLE plans w/ PLACEHOLDER prices
  tests/
    __init__.py
    test_entitlements.py
    test_quota_lazy_reset.py
    test_checkout_portal.py
    test_webhook.py
    test_gating.py
```

Wire-up: append `'billing'` to `INSTALLED_APPS` and `path('api/v1/billing/', include('billing.urls'))` in `JokesForProject/urls.py` (alongside `api/v1/creators/`). The webhook is mounted **unauthenticated + CSRF-exempt** (like `healthz` / `joke_share_page`).

---

## 2. Data model

### 2.1 `Plan` — the editable business config (source of truth)

```python
class Plan(models.Model):
    slug = models.SlugField(unique=True)            # 'free', 'creator_pro' — stable program key
    name = models.CharField(max_length=120)         # display, editable freely
    description = models.TextField(blank=True)       # marketing copy
    is_active = models.BooleanField(default=True)    # can users subscribe?
    is_public = models.BooleanField(default=True)    # show in pricing UI?
    is_default = models.BooleanField(default=False)  # the FREE fallback (exactly one)
    sort_order = models.IntegerField(default=0)

    # Money mechanics — owned by Stripe, mirrored here. NULL for the free plan.
    interval = models.CharField(max_length=10, choices=[('month','month'),('year','year')], blank=True)
    amount_cents = models.PositiveIntegerField(null=True, blank=True)   # what admin edits
    currency = models.CharField(max_length=3, default='usd')
    stripe_product_id = models.CharField(max_length=80, blank=True)
    stripe_price_id   = models.CharField(max_length=80, blank=True)     # set by 'Push to Stripe'

    # The editable feature/limit payload (see normalized-vs-JSON below)
    features = models.JSONField(default=dict, blank=True)  # {"creator_analytics": true, ...}
    limits   = models.JSONField(default=dict, blank=True)  # {"mystery_box_rolls_per_day": 3, ...}
```

**Normalized rows vs. JSON — recommendation: JSON fields, with a documented vocabulary.**

I evaluated the two shapes:
- *Normalized* (`Feature` + `PlanFeature(bool_value, int_value)` rows, as one research output proposed): self-describing, queryable, FK integrity. But it adds 2 tables, a join on every resolve, and — crucially — **adding a new gated capability means inserting `Feature` rows / admin friction**, and editing a limit is a row hunt across a many-to-many grid.
- *JSON* (`features` + `limits` dicts on `Plan`): a limit edit is one field on one object in admin; a new capability is just a new key. This matches the **existing house style** (`jokes/models.py` already uses `JSONField`; the research explicitly notes "a JSONField of limits/flags fits the existing pattern"). Resolution is a single row read, no join — important since this is on the hot path of gated views.

**Decision: JSON fields.** To keep them safe and admin-friendly (JSON's weakness is typos/unknown keys), we add a **central registry** in `entitlements.py` — `KNOWN_FEATURES` and `KNOWN_LIMITS` dicts that define every valid key, its type, and its **free-tier default**. `get_limit()/has_feature()` resolve against the registry, so an unknown/missing key in a Plan's JSON safely falls back to the registered default rather than crashing. A lightweight admin form `clean()` warns on unknown keys. This gives JSON's editability with normalized's safety, and keeps "what gates exist" discoverable in one code location.

### 2.2 `Subscription` — the local mirror Stripe keeps in sync

```python
class Subscription(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscription')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions')
    stripe_customer_id     = models.CharField(max_length=80, blank=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=80, blank=True, db_index=True)
    stripe_price_id        = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=24, default='free')  # free|trialing|active|past_due|canceled|unpaid|incomplete...
    current_period_start = models.DateTimeField(null=True, blank=True)  # quota window anchor
    current_period_end   = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    ACTIVE_STATUSES = {'active', 'trialing'}
    def is_entitled(self): return self.status in self.ACTIVE_STATUSES
```

A user with no `Subscription` row is treated as the FREE plan. The `stripe_customer_id` lives here (Customer is created lazily at first checkout). `is_premium` on `UserProfile` is **NOT** the source of truth — the webhook keeps it synced as a denormalized read-cache (so the existing profile/data-export payloads keep working), but entitlement decisions read `Subscription` + the resolver.

### 2.3 `UsageCounter` — quota with LAZY period reset (no cron)

For quotas **not derivable by counting existing rows** (e.g. a monthly send/submission budget). Row-derivable daily caps like Mystery Box don't need this table — they count rows by date bucket (the existing pattern). For the ones that do:

```python
class UsageCounter(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='usage_counters')
    key = models.CharField(max_length=64)        # 'submissions_per_month'
    period_key = models.CharField(max_length=16) # 'YYYY-MM' (monthly) or 'YYYY-MM-DD' (daily)
    count = models.PositiveIntegerField(default=0)
    class Meta:
        unique_together = ('user', 'key', 'period_key')
```

**Lazy reset (the no-worker guarantee):** at check time we compute the *current* `period_key` from `now()` (and, for plan-aligned windows, optionally from `subscription.current_period_start`). We `get_or_create(user, key, period_key=current)`. If the period rolled, the lookup simply lands on a **new row at count 0** — the old row is ignored, no reset job needed. This is the exact precedent of Streak-freeze monthly refresh and Mystery Box date buckets. `invoice.paid` may stamp a fresh anchor as a convenience, but the read-time `period_key` compare is the real guarantee and survives missed webhooks.

### 2.4 `ProcessedStripeEvent` — webhook idempotency

```python
class ProcessedStripeEvent(models.Model):
    event_id = models.CharField(max_length=80, unique=True)  # Stripe event.id
    event_type = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
```

At handler start: if `event_id` already exists, return 200 immediately (Stripe re-delivers/duplicates). Insert it as part of the same transaction as the UPSERT.

### 2.5 Customer / Stripe linkage

There is no separate Customer model. `Subscription.stripe_customer_id` (1:1 with `User`) is the linkage. We get-or-create the Stripe Customer at first checkout (storing its id), `client_reference_id=user.id` + `metadata={user_id, plan_slug}` on the Checkout Session tie the webhook back to the user.

---

## 3. EntitlementService API (`billing/entitlements.py`)

The single choke-point. Pure functions over `(user, key)`, resolving the user's effective Plan (active/trialing Subscription's plan, else the `is_default` FREE plan) and reading flags/limits against the `KNOWN_*` registry.

```python
# Registry: the canonical list of gateable capabilities + their FREE defaults.
KNOWN_FEATURES = {
    'creator_analytics': False,
    'daily_joke_preview': False,
    'mature_content_addon': False,   # NOTE: addon != age gate (see §8)
}
KNOWN_LIMITS = {
    'mystery_box_rolls_per_day': 3,        # = MysteryBoxRoll.MAX_DAILY_ROLLS today
    'submissions_per_day': 5,              # PLACEHOLDER free default
    'daily_jokes_per_day': 1,              # today everyone gets 1
    'daily_joke_history_days': 30,         # today hard-coded [:30]
}

def effective_plan(user) -> Plan: ...         # active sub's plan OR default FREE plan
def has_feature(user, key) -> bool: ...       # plan.features.get(key, KNOWN_FEATURES[key])
def get_limit(user, key, default=None) -> int|None:  # plan.limits.get(key, default or KNOWN_LIMITS[key]); None = unlimited
def get_usage(user, key, period='day'|'month') -> int   # row-count or UsageCounter
def check_and_consume_quota(user, key, period, amount=1) -> QuotaResult
    # 1) limit = get_limit(user, key); if limit is None -> unlimited, allow
    # 2) current_period_key from now() (+ sub anchor if plan-aligned)
    # 3) UsageCounter.get_or_create(user, key, period_key) -> lazy reset
    # 4) if count + amount > limit -> QuotaResult(allowed=False, remaining=0, limit, reset_at)
    # 5) F()-increment count, return QuotaResult(allowed=True, remaining=...)
```

`QuotaResult` carries `allowed`, `limit`, `used`, `remaining`, `reset_at` so views can build both the 429 body and the status payload from one call. For **row-derivable** caps (Mystery Box), a sibling `check_quota_by_count(user, key, count_callable, period)` reads `get_limit` and compares against a live row count — no `UsageCounter` write.

**FREE default is the contract:** every function returns a clean free-tier answer for users with no Subscription and for anon users. Gating fails open.

---

## 4. Stripe integration

### 4.1 Env keys (mirror RESEND / EMAIL_* / SENTRY)

All via `os.getenv` in `settings.py`, placeholders in `.env.example`, real values only in gitignored `.env` + Cloud Run secrets:

```python
STRIPE_SECRET_KEY      = os.getenv('STRIPE_SECRET_KEY', '').strip()      # sk_test_ local, sk_live_ prod
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY', '').strip()
STRIPE_WEBHOOK_SECRET  = os.getenv('STRIPE_WEBHOOK_SECRET', '').strip()  # whsec_ — per-endpoint/env
STRIPE_API_VERSION     = os.getenv('STRIPE_API_VERSION', '2026-05-27.dahlia')  # PINNED
BILLING_ENABLED        = os.getenv('BILLING_ENABLED', 'false').lower() == 'true'
BILLING_SUCCESS_URL    = os.getenv('BILLING_SUCCESS_URL', 'http://localhost:5173/billing/success')
BILLING_CANCEL_URL     = os.getenv('BILLING_CANCEL_URL', 'http://localhost:5173/billing/cancel')
BILLING_PORTAL_RETURN_URL = os.getenv('BILLING_PORTAL_RETURN_URL', 'http://localhost:5173/account')
```

**Dormant when unset** (like Sentry): `stripe_gateway.py` checks `STRIPE_SECRET_KEY`; if empty, checkout/portal endpoints return `503 billing_unavailable`, the webhook returns 200-noop, and **entitlements still resolve to FREE** — the app is fully functional with billing off. Add `stripe` to `requirements.txt` (not yet installed). Pin `stripe.api_version` so webhook payload shapes don't shift under us.

### 4.2 Checkout (server flow)

`POST /api/v1/billing/checkout-session {plan_slug}`:
1. Resolve `Plan` by slug; reject if `not is_active` or no `stripe_price_id`.
2. Get-or-create Stripe Customer for `request.user`; persist `stripe_customer_id`.
3. `stripe.checkout.Session.create(mode='subscription', customer=cust, line_items=[{price: plan.stripe_price_id, quantity:1}], success_url, cancel_url, client_reference_id=user.id, metadata={user_id, plan_slug})`.
4. Return `{url}` (or `client_secret` for embedded). Frontend redirects.
5. **Access is granted by the webhook, not the redirect.** `success_url` is cosmetic ("activating…").

### 4.3 Webhook handler (`POST /api/v1/billing/webhook`)

CSRF-exempt, unauthenticated, **reads `request.body` raw** (never `request.data` — re-parsing breaks the signature):
1. `stripe.Webhook.construct_event(body, sig_header, STRIPE_WEBHOOK_SECRET)`; on `SignatureVerificationError` -> **400**.
2. **Idempotency:** if `event.id` in `ProcessedStripeEvent` -> return **200** immediately.
3. **Dispatch** (order-independent; re-fetch object from Stripe by id if payload looks stale):
   - `checkout.session.completed` -> link customer+subscription to user, UPSERT mirror, set plan.
   - `customer.subscription.created/updated` -> UPSERT status, price_id, period start/end, cancel_at_period_end; **re-resolve `plan` from price_id** (covers upgrades/downgrades/renewals/portal edits); sync `is_premium`.
   - `customer.subscription.deleted` -> set status `canceled`, **downgrade plan to FREE**, `is_premium=False`.
   - `invoice.paid` -> clear `past_due`, stamp new period anchor.
   - `invoice.payment_failed` -> mark `past_due` (and queue a dunning email **via the existing `notifications.service.send_email`**, kept quick so it never risks the 200).
4. Record `event.id`, **single fast UPSERT** in one transaction, return **200**.

**No-worker compliance:** the whole handler is verify + dedupe + one UPSERT — a few ms, well inside Stripe's timeout. No image processing, no blocking outbound work before the 200. This is the correct single-app adaptation of Stripe's "return fast" guidance. Stripe Smart Retries handle dunning server-side; we never build retry/cron logic.

### 4.4 Customer Portal

`POST /api/v1/billing/portal-session` -> `stripe.billing_portal.Session.create(customer=stripe_customer_id, return_url=...)` -> return `{url}`. The Portal handles **all** self-serve upgrade/downgrade/cancel/payment-method/invoices, and every action fires the **same webhooks** we already handle, so the mirror stays correct with zero extra code. Allowed switch targets are configured in the Stripe Dashboard Portal config (the real Plans). We do **not** hand-build change UIs; we skip custom proration logic for the first slice (Portal default = `create_prorations`).

### 4.5 Plan <-> Price mapping & sync direction (one-way DB -> Stripe)

Our `Plan` is authoritative for config. Money is pushed to Stripe via an **idempotent admin action "Push to Stripe"**:
- Create the Stripe Product **once** (store `stripe_product_id`).
- Prices are **immutable** — to change `amount_cents`/`interval`, create a **new** Stripe Price, archive the old (`active=false`), store the new `stripe_price_id`.
- **Rename / feature-flag / limit edits require NO Stripe call** — they're pure DB, reflected live. This is precisely what makes plans "admin-editable, no deploy."
No bidirectional sync (drift risk); import-from-Stripe only as a one-time bootstrap if ever needed. Entitlements API is intentionally **not** used (it would move config into Stripe and defeat the requirement — YAGNI).

---

## 5. Admin editability (business self-service)

All four models registered in Django admin (house style — `jokes/admin.py` registers everything):
- **`PlanAdmin`**: `list_display=(name, slug, interval, amount_display, is_active, is_public, is_default, stripe_price_id)`; `list_editable` for `is_active/is_public/amount_cents/sort_order`; JSON `features`/`limits` editable inline; a `clean()` that warns on keys outside `KNOWN_FEATURES/KNOWN_LIMITS`; the **"Push to Stripe" action**; read-only `stripe_*` ids. **This is the live control panel**: flip a feature, raise a limit, retire a plan — next request reflects it.
- **`SubscriptionAdmin`**: read-mostly mirror (status/plan/period/customer ids) for support; `search_fields` on user/email/stripe ids.
- **`UsageCounterAdmin`** & **`ProcessedStripeEventAdmin`**: read-only audit (mirrors the read-only email-log/verification admin already added).

---

## 6. Access points to gate (mapped to real views)

Demo gates wired in the first slice (the rest follow the same one-liner pattern):
1. **Mystery Box daily cap** — `jokes/views.py` `MysteryBoxStatusView.get` (~:1974) and `MysteryBoxRollView.post` (~:2005). Replace the literal `MysteryBoxRoll.MAX_DAILY_ROLLS` in **both** with `entitlements.get_limit(user, 'mystery_box_rolls_per_day', default=MysteryBoxRoll.MAX_DAILY_ROLLS)` (constant becomes the free fallback). Both call sites must change so the 429 and the status payload agree. Lowest-risk, no schema churn.
2. **Creator analytics feature flag** — `creator_insights/views.py` `CreatorInsightsView.permission_classes` -> append `HasFeature('creator_analytics')` alongside `IsCreator`. Additive; mirrors the existing permission pattern exactly. (For the demo, FREE default for `creator_analytics` should be `True` until business decides, so we don't break Wave 1 creator analytics — see openDecisions.)

Follow-on slots (designed, not in slice 1): `JokeSubmitView` submission quota (`check_and_consume_quota(user,'submissions_per_day')` -> 429), DailyJoke `daily_jokes_per_day` + `daily_joke_history_days` depth, `daily_joke_preview` for the tomorrow teaser.

---

## 7. Endpoints

- `POST /api/v1/billing/checkout-session` — auth; `{plan_slug}` -> `{url}` (503 if billing dormant).
- `POST /api/v1/billing/portal-session` — auth -> `{url}`.
- `POST /api/v1/billing/webhook` — public, CSRF-exempt, signature-verified, idempotent.
- `GET  /api/v1/billing/my-subscription` — auth -> current plan slug/name, status, `current_period_end`, `cancel_at_period_end`.
- `GET  /api/v1/billing/entitlements` — auth -> resolved `{features:{...}, limits:{...}, plan, usage:{...}}` so the frontend gates UI from the same truth the backend enforces.
- `GET  /api/v1/billing/plans` — public -> `is_public && is_active` plans (pricing page).

---

## 8. Coexistence with Wave 1 `content_tier` (CRITICAL)

`jokes/serving.py:allowed_tiers()` is the COPPA **age/consent** gate (tier_2 iff `is_adult AND show_mature`). Monetization **must never widen** what age allows. A `mature_content_addon` plan feature, if ever sold, is an **ADDITIONAL `AND` condition layered on top** of the age result — `entitled AND is_adult AND show_mature`. A paying minor **never** reaches tier_2. We do **not** fold a plan check into `allowed_tiers()`; the billing resolver can only further-restrict, never relax. The age gate stays authoritative and untouched in slice 1.

`is_premium` (UserProfile) stays as a **webhook-synced denormalized read-cache** so existing profile/data-export payloads keep working; it is not the entitlement source of truth.

---

## 9. Security & no-worker compliance

- Webhook: public + CSRF-exempt + **signature-verified** + **idempotent on event.id** + raw body. Never behind JWT/CSRF. Forged calls fail signature -> 400.
- PCI: all card entry stays on Stripe-hosted Checkout/Portal -> SAQ-A only. Never accept/log raw card data; no custom card form.
- Keys strictly env-per-environment; live keys only in Cloud Run secrets; each endpoint its own `whsec_`. API version pinned.
- **No Celery/cron/workers.** Webhooks are inbound HTTP (allowed). All quota period-resets are **lazy on read/write** via `period_key` compare — never scheduled. Missed events self-heal via lazy read-time resolution.

---

## 10. Seed: EXAMPLE editable plans (data migration 0002) — PLACEHOLDER prices

These are **EXAMPLES to be edited later**, not the real catalog. Amounts are PLACEHOLDER; `stripe_*` ids are blank until an admin runs "Push to Stripe" with real keys.

```python
# billing/migrations/0002_seed_plans.py  (idempotent get_or_create by slug)
PLANS = [
  dict(slug='free', name='Free', is_default=True, is_active=True, is_public=True,
       amount_cents=None, interval='', sort_order=0,
       features={'creator_analytics': True, 'daily_joke_preview': False, 'mature_content_addon': False},
       limits={'mystery_box_rolls_per_day': 3, 'submissions_per_day': 5,
               'daily_jokes_per_day': 1, 'daily_joke_history_days': 30}),

  dict(slug='creator_pro', name='Creator Pro (PLACEHOLDER)', is_active=True, is_public=True,
       amount_cents=1500, interval='month', sort_order=10,   # $15/mo PLACEHOLDER — EDIT BEFORE LAUNCH
       features={'creator_analytics': True, 'daily_joke_preview': True, 'mature_content_addon': False},
       limits={'mystery_box_rolls_per_day': 20, 'submissions_per_day': 50,
               'daily_jokes_per_day': 5, 'daily_joke_history_days': 365}),

  dict(slug='supporter', name='Supporter (PLACEHOLDER)', is_active=True, is_public=True,
       amount_cents=500, interval='month', sort_order=5,     # $5/mo PLACEHOLDER — EDIT BEFORE LAUNCH
       features={'creator_analytics': True, 'daily_joke_preview': True, 'mature_content_addon': False},
       limits={'mystery_box_rolls_per_day': 10, 'submissions_per_day': 15,
               'daily_jokes_per_day': 3, 'daily_joke_history_days': 90}),
]
```

Note `creator_analytics: True` on FREE in the seed so the existing Wave 1 analytics endpoint isn't broken when the gate is added; business flips it to a paid feature later by editing the FREE plan's `features` in admin (no deploy).

---

## 11. Testing

Django runner on local Postgres, mock Stripe — **no live calls**:
`DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test billing --keepdb`
Stripe SDK calls patched with `unittest.mock`; webhook tests patch `stripe.Webhook.construct_event` to return a fixture event (and a separate test forces `SignatureVerificationError` -> 400). Commit messages plain (no footers).
