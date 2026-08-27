# Backend Monetization Deep-Dive: Billing, Tips, Freemium Paywall, Creator Insights

Key: `be-billing-tips-paywall`
Repo: `/Users/narekmeloyan/PycharmProjects/JokesForProject` (BE), `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend` (FE, referenced for contract)
Date: 2026-08-25. All facts below are from code unless marked "(doc)" or "(memory)".

---

## 0. TL;DR status matrix

| Capability | Code state | Runtime state (prod) | Gate |
| --- | --- | --- | --- |
| Plans catalog (`GET /api/v1/billing/plans`) | complete | LIVE, serves seeded placeholder plans | none (public) |
| Entitlements resolver + `/entitlements`, `/my-subscription` | complete | LIVE (everyone resolves to `free`) | none |
| Freemium punchline paywall (10 reveals/day) | complete | LIVE since 2026-07-14 (memory) | `Plan.limits.free_joke_reads_per_day` (admin-editable) |
| Anonymous paywall ledger (signed cookie) | complete | LIVE | none |
| Stripe subscription checkout / portal / webhook | complete, test-mode-mocked | DORMANT: `STRIPE_SECRET_KEY` unset => 503 / 200-noop (memory 2026-08-04; cloudbuild.yaml injects no Stripe secret) | `STRIPE_SECRET_KEY` env |
| Creator tips (payment-mode checkout + webhook completion) | complete, deployed 2026-08-04 (memory) | DORMANT (same key) | `STRIPE_SECRET_KEY` env |
| `BILLING_ENABLED` setting | defined in settings, **never read by any view** | no effect | n/a |
| Mystery Box quota via plan limit | complete | LIVE (free=3/day) | `Plan.limits.mystery_box_rolls_per_day` |
| Daily-joke history window via plan limit | complete | LIVE (free=30 days) | `Plan.limits.daily_joke_history_days` |
| `creator_analytics` feature gate | complete | LIVE but free plan seeds it `True` (no-op gate) | `Plan.features.creator_analytics` |
| `submissions_per_day`, `daily_jokes_per_day`, `daily_joke_preview`, `mature_content_addon` | **registry entries only; no call site anywhere** | inert | n/a |
| `UsageCounter` / `check_and_consume_quota` | implemented + tested | **no production caller** (only tests) | n/a |
| Dunning email on `invoice.payment_failed` | code calls `send_email(template_name='payment_failed')` | **silently no-ops**: template not in registry, exception swallowed | n/a |
| Creator insights / telemetry ingest | complete | LIVE | `creator_analytics` feature (free=True) |

---

## 1. Billing app (`billing/`)

### 1.1 Files
- `billing/models.py` — `Plan`, `Subscription`, `UsageCounter`, `ProcessedStripeEvent`, `Tip`
- `billing/entitlements.py` — single resolver choke-point (`effective_plan`, `has_feature`, `get_limit`, `get_usage`, `check_and_consume_quota`, `check_quota_by_count`)
- `billing/stripe_gateway.py` — env-gated Stripe SDK wrapper
- `billing/views.py` — all HTTP views (subscriptions + tips)
- `billing/webhooks.py` — webhook dispatch
- `billing/permissions.py` — `HasFeature(key)` DRF permission factory
- `billing/serializers.py` — `PlanPublicSerializer`, `MySubscriptionSerializer`, `TipSerializer`, `EntitlementsSerializer` (the last is unused by views)
- `billing/urls.py` (mounted at `api/v1/billing/`), `billing/tip_urls.py` (mounted at `api/v1/tips/`)
- `billing/admin.py` — Plan/Subscription/UsageCounter/ProcessedStripeEvent admin. **`Tip` is NOT registered in admin** (memory's activation checklist also flags this).
- Migrations: `0001_initial`, `0002_seed_plans` (free/supporter/creator_pro with PLACEHOLDER prices), `0003_free_joke_read_cap` (adds `free_joke_reads_per_day`: free=10, paid=None), `0004_tip`.
- Dependency: `stripe==12.2.0` (`requirements.txt:41`), API version pinned by setting `STRIPE_API_VERSION` default `'2026-05-27.dahlia'`.

### 1.2 Settings (`JokesForProject/settings.py:507-515`)
```
STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET  (all default '' -> dormant)
STRIPE_API_VERSION = '2026-05-27.dahlia'
BILLING_ENABLED = env 'false'  -> DEFINED BUT UNUSED (grep: no reader outside settings)
BILLING_SUCCESS_URL     default http://localhost:5173/billing/success
BILLING_CANCEL_URL      default http://localhost:5173/billing/cancel
BILLING_PORTAL_RETURN_URL default http://localhost:5173/account
```
Throttle scope `tips-checkout: '30/hour'` (`settings.py:315`). `creator_insights: '120/hour'`.

`Docs/STRIPE_GOLIVE.md` explicitly states `BILLING_ENABLED` is not used for gating — matches code. The design doc `Docs/superpowers/2026-06-19-monetization-design.md` says it ships "dark behind BILLING_ENABLED" — **doc/code disagreement: gating is purely `STRIPE_SECRET_KEY`.**

`cloudbuild.yaml` passes only `DATABASE_URL` as a secret and updates the service image without `--set-env-vars`, so Stripe env presence in prod depends on manual Cloud Run env configuration. Memory (2026-08-04) says it is unset (tips checkout 503s in prod, TipButton shows "coming soon").

### 1.3 Gating (`billing/stripe_gateway.py:15-24`)
- `is_enabled()` = `bool(settings.STRIPE_SECRET_KEY)`.
- `_client()` raises `BillingUnavailable` if disabled; otherwise sets `stripe.api_key` + `stripe.api_version` globally on the module (process-global mutation, fine for single key).
- Views: `CheckoutSessionView`, `TipCheckoutView`, `PortalSessionView` return `503 {'detail': 'Billing is not configured.', 'code': 'billing_unavailable'}` when dormant (`views.py:28-32`). `StripeWebhookView` returns `200 {'detail': 'billing_dormant'}` when dormant (`views.py:261-263`) so Stripe does not retry.
- NOTE ordering: `IsAuthenticated` permission runs before `is_enabled()`, so an anonymous caller gets 401 not 503.

### 1.4 Models (`billing/models.py`)
- `Plan`: `slug` unique, `name`, `description`, `is_active`, `is_public`, `is_default` (the FREE fallback; no DB constraint enforcing exactly-one), `sort_order`, `interval` (`month|year|''`), `amount_cents` (null=free), `currency` default `usd`, `stripe_product_id`, `stripe_price_id`, `features` JSON, `limits` JSON. `amount_display` -> `'Free'` or `'$5.00/month'`.
- `Subscription`: OneToOne `user` (related_name `subscription`), FK `plan` (PROTECT), `stripe_customer_id`, `stripe_subscription_id`, `stripe_price_id`, `status` default `'free'`, `current_period_start/end`, `cancel_at_period_end`, `updated_at`. `ACTIVE_STATUSES={'active','trialing'}` -> `is_entitled()`. `LIVE_PAID_STATUSES={'active','trialing','past_due'}` used only by checkout double-bill guard.
- `UsageCounter`: (user, key, period_key) unique, `count`.
- `ProcessedStripeEvent`: `event_id` unique, `event_type`, `created_at`.
- `Tip`: `sender` FK (`tips_sent`), `creator` FK (`tips_received`), `joke` FK null SET_NULL (`tips`), `amount_cents`, `currency` default `usd`, `status` in `pending|succeeded|failed|refunded` (default pending, indexed), `stripe_payment_intent_id`, `stripe_checkout_session_id` (both indexed, not unique), `created_at`, `completed_at`. Ordering `-created_at`. **No code path ever sets `failed` or `refunded`** — those are admin/manual-only states and there is no admin registration for Tip.

### 1.5 Seeded plans (`billing/migrations/0002_seed_plans.py` + `0003`)
| slug | default | price | features | limits |
| --- | --- | --- | --- | --- |
| `free` | yes | None | creator_analytics=True, daily_joke_preview=False, mature_content_addon=False | mystery_box 3, submissions 5, daily_jokes 1, history 30, **free_joke_reads_per_day 10** |
| `supporter` | no | 500/month PLACEHOLDER | analytics True, preview True | mystery 10, submissions 15, daily 3, history 90, **reads None (unlimited)** |
| `creator_pro` | no | 1500/month PLACEHOLDER | analytics True, preview True | mystery 20, submissions 50, daily 5, history 365, **reads None** |

Names literally contain "(PLACEHOLDER)" and `stripe_price_id` is blank, so in prod `POST /billing/checkout-session` for either paid plan returns **422 "This plan is not yet available for purchase."** even after the key is set, until Push-to-Stripe / manual price ids (`views.py:60-64`). `GET /billing/plans` is public and currently exposes these placeholder names/prices to the frontend BillingPage.

### 1.6 Entitlement resolver (`billing/entitlements.py`)
- `KNOWN_FEATURES = {creator_analytics: True, daily_joke_preview: False, mature_content_addon: False}`; `KNOWN_LIMITS = {mystery_box_rolls_per_day: 3, submissions_per_day: 5, daily_jokes_per_day: 1, daily_joke_history_days: 30, free_joke_reads_per_day: 10}`.
- `effective_plan(user)`: anon or no sub or non-entitled sub -> `Plan(is_default=True)`; entitled sub -> `sub.plan`; if no default plan exists returns `None` (fail-open to registry defaults).
- `has_feature(user, key)` -> `plan.features.get(key, KNOWN_FEATURES.get(key, False))`.
- `get_limit(user, key, default=None)` -> `plan.limits.get(key, registry_default or default)`; **`None` in plan JSON means unlimited** and is returned as-is (dict `.get` returns the stored `None`).
- `_period_key` / `_reset_at` use `date.today()` (naive local date), whereas the paywall uses `timezone.now().date()`. Both resolve to UTC because `TIME_ZONE='UTC'`, but `date.today()` is not freezegun/`timezone`-consistent in principle; tests patch `date`.
- `check_and_consume_quota` is `@transaction.atomic`, `select_for_update` on the counter row, lazy period reset via `period_key`. Anonymous -> `allowed=False`. **No production caller** (grep across repo excluding tests: none).
- `check_quota_by_count` — informational, no caller in prod either (Mystery Box views call `get_limit` directly).

### 1.7 Where entitlements are actually enforced
1. **Mystery Box** (`jokes/views.py:2784, 2815, 2821, 2845`): `get_limit(user, 'mystery_box_rolls_per_day', default=MysteryBoxRoll.MAX_DAILY_ROLLS)`; roll returns **429** with `{rolls_used_today, max_per_day, ...}` at the cap. RISK: an admin setting this limit to `null` (unlimited) would raise `TypeError` on `max_per_day - used` — the code assumes an int.
2. **Daily-joke history window** (`jokes/views.py:1321-1326`): `get_limit(user, 'daily_joke_history_days', 30)`; `None` -> no cutoff (unlimited handled correctly here).
3. **Creator analytics** (`creator_insights/views.py:29`): `permission_classes = [IsAuthenticated, IsCreator, HasFeature('creator_analytics')]` -> 403 when the feature is False on the effective plan. Free plan seeds True, so it is a no-op today; test `test_free_user_with_creator_analytics_false_gets_403` proves the flip works without deploy.
4. **Freemium read cap** (`jokes/paywall.py:141`): `get_limit(user, 'free_joke_reads_per_day', 10)`.
5. `GET /billing/entitlements` (`views.py:310-323`) returns `{plan, features{...all KNOWN_FEATURES}, limits{...all KNOWN_LIMITS}}` for the FE. Note: spec §7 promised a `usage` map; **code does not return `usage`**.

### 1.8 Endpoints (subscriptions)
| Method/path | Auth | Behaviour |
| --- | --- | --- |
| `GET /api/v1/billing/plans` | AllowAny | `Plan.filter(is_active, is_public).order_by(sort_order)` -> `[{slug,name,description,interval,amount_cents,currency,amount_display,features,limits,sort_order}]` |
| `POST /api/v1/billing/checkout-session {plan_slug}` | IsAuthenticated | dormant->503; unknown/inactive slug->404; blank `stripe_price_id`->422; live paid sub (`status in {active,trialing,past_due}` and has customer or subscription id)->**409 `{code:'active_subscription', detail, portal_url?}`** (portal_url best-effort); else creates Stripe Customer lazily (`get_or_create_customer` also creates a `Subscription(status='free')` row) and a `mode='subscription'` Checkout Session with `success_url=BILLING_SUCCESS_URL`, `cancel_url=BILLING_CANCEL_URL`, `client_reference_id=user.pk`, `metadata={user_id, plan_slug}` -> `{url}`; Stripe error->502 |
| `POST /api/v1/billing/portal-session` | IsAuthenticated | dormant->503; no Subscription row or blank customer id->404 "No billing account found."; else `billing_portal.Session.create(return_url=BILLING_PORTAL_RETURN_URL)` -> `{url}`; error->502 |
| `POST /api/v1/billing/webhook` | none, CSRF-exempt | see 1.9 |
| `GET /api/v1/billing/my-subscription` | IsAuthenticated | `{plan_slug, plan_name, status, current_period_end, cancel_at_period_end, stripe_customer_id}`; no row -> synthesized free payload with `status:'free'` |
| `GET /api/v1/billing/entitlements` | IsAuthenticated | `{plan, features, limits}` |

Success/cancel URLs: **static** from settings — no `{CHECKOUT_SESSION_ID}` placeholder, no per-request override. The FE has **no `/billing/success` or `/billing/cancel` route** (`src/app/routes.tsx` only defines `/settings/billing`; catch-all `*` -> `NotFoundPage`), so unless prod `BILLING_SUCCESS_URL`/`BILLING_CANCEL_URL` are set to `https://jokesforfront.web.app/settings/billing` (or similar), a completed checkout lands on the SPA 404 page. Docs (`STRIPE_GOLIVE.md`) suggest `https://<frontend>/billing/success`, which does not exist in the FE router — **doc/FE mismatch to flag**. Access is granted by the webhook, not the redirect, so this is UX only.

### 1.9 Webhook (`billing/views.py:250-287`, `billing/webhooks.py`)
- Reads raw `request.body`, header `HTTP_STRIPE_SIGNATURE`; `stripe.Webhook.construct_event(payload, sig, settings.STRIPE_WEBHOOK_SECRET)`; `SignatureVerificationError` -> 400; any other construct error -> 400; handler exception -> **500** (Stripe will retry; since `handle_event` is `@transaction.atomic`, the `ProcessedStripeEvent` insert rolls back with the failure, so the retry is re-processed — correct).
- **Security gap (pre-existing, also in memory):** if `STRIPE_SECRET_KEY` is set but `STRIPE_WEBHOOK_SECRET` is left empty, `construct_event` verifies HMAC against `''` — forgeable. Both must be set together.
- `handle_event` (`webhooks.py:290-313`): atomic; if `ProcessedStripeEvent(event_id)` exists -> return (idempotent; the dedupe check is a plain `exists()` not `select_for_update`/`get_or_create`, so two concurrent deliveries of the same event could both pass the check; the unique constraint would make the second one raise IntegrityError -> 500 -> Stripe retry -> then deduped. Acceptable but worth a note). Dispatch table:
  - `checkout.session.completed` -> `_handle_checkout_completed`: if `metadata.type=='tip' and mode=='payment'` -> `_handle_tip_completed` (see §2); elif `mode` present and != `'subscription'` -> ignored with warning (anti-downgrade guard); else resolve user via `metadata.user_id` -> `client_reference_id` -> `Subscription.stripe_customer_id` and UPSERT `Subscription(plan=metadata.plan_slug or free, status='active', stripe_subscription_id, stripe_customer_id)`.
  - `customer.subscription.created|updated` -> resolve user by `stripe_customer_id` then `metadata.user_id`; `price_id = items.data[0].price.id`; `plan = Plan(stripe_price_id) or free`; upsert `status=subscription.status`, `current_period_start/end` (unix -> UTC datetime), `cancel_at_period_end`.
  - `customer.subscription.deleted` -> upsert `plan=free, status='canceled'`.
  - `invoice.paid` -> if `past_due` -> `active`; stamp `current_period_end` from `invoice.period_end`; sync `is_premium`.
  - `invoice.payment_failed` -> `status='past_due'`, `is_premium=False`, attempt `send_email(template_name='payment_failed')` inside `try/except Exception: pass`. **`payment_failed` is not in `notifications/templates_registry.py` (only verification_code, daily_digest, creator_milestone) -> `UnknownTemplate` -> swallowed. The dunning email never sends.** Design doc §4.3 claims it does — doc/code disagreement.
  - Every branch ends with `ProcessedStripeEvent.objects.create(...)`.
- `_upsert_subscription` (`webhooks.py:44-67`): `select_for_update().get_or_create(user)`; blank ids never overwrite existing ids; syncs `UserProfile.is_premium = sub.is_entitled()` (denormalized cache exposed by `GET /users/me/profile/` `jokes/views.py:1951` and data export `:2524`).
- `past_due` -> not entitled (`ACTIVE_STATUSES` excludes it): a user in dunning immediately drops to free limits (paywall re-engages) while Stripe retries. That is the coded product behaviour; flag as a product decision.
- Unknown event types are recorded as processed and return 200.

### 1.10 Admin (`billing/admin.py`)
- `PlanAdmin` warns (does not block) on unknown feature/limit keys; `push_to_stripe` action creates Product once, creates a new Price and archives the old when `amount_cents` changed (`stripe_gateway.push_plan_to_stripe`). Free plans skipped. Requires the running server to have `STRIPE_SECRET_KEY`.
- `SubscriptionAdmin` all read-only; `UsageCounterAdmin`, `ProcessedStripeEventAdmin` read-only.

---

## 2. Creator tips

Spec: `Docs/superpowers/specs/2026-07-24-creator-tips-design.md`. Plan: `Docs/superpowers/plans/2026-07-24-creator-tips-wave.md`.

### 2.1 Routing
- `POST /api/v1/tips/checkout/` -> `TipCheckoutView` (`billing/tip_urls.py`, mounted `JokesForProject/urls.py:59`)
- `GET /api/v1/creators/<int:creator_id>/tips/summary/` -> `CreatorTipsSummaryView` (`creator_insights/urls.py:9`)
- `GET /api/v1/users/me/tips/` -> `MyTipsView` (`follows/user_urls.py:8`, mounted at `api/v1/users/`)

### 2.2 `TipCheckoutView` (`billing/views.py:101-184`)
- `IsAuthenticated`; `ScopedRateThrottle` scope `tips-checkout` = 30/hour per user.
- Order of checks: dormant->503 (after auth); `amount_cents` must `int()`-parse else 400 `invalid_amount`; must be in `TIP_AMOUNT_TIERS_CENTS = {100, 300, 500, 1000}` else 400 `invalid_amount`; `creator_id` required else 400 `creator_required`; creator user must exist else 404; `Joke.objects.filter(creator=creator).exists()` (default manager excludes `is_removed`, so a creator whose only joke was taken down is "not a creator") else 400 `not_a_creator`; self-tip -> 400 `self_tip`; optional `joke_id` must exist (default manager: non-removed) else 400 "Joke not found." and `joke.creator_id == creator.pk` else 400 `joke_creator_mismatch`.
- NOTE: "is a creator" here means `Joke.creator` FK; `IsCreator` for insights means a `JokeSubmission(status='published')`. Legacy jokes with null `creator` (submission-join fallback used by insights) would NOT qualify for tips. Minor inconsistency.
- Then `create_tip_checkout_session(sender, creator, joke, amount_cents)` (`stripe_gateway.py:79-133`): creates Stripe Customer for the sender if needed (this also creates a `Subscription(status='free')` row for the sender as a side effect), creates `Tip(status='pending')` FIRST, then `checkout.Session.create(mode='payment', customer, payment_method_types=['card'], line_items=[price_data{currency, unit_amount, product_data.name='Tip for <display name>'}], success_url=BILLING_SUCCESS_URL, cancel_url=BILLING_CANCEL_URL, metadata={type:'tip', tip_id, creator_id, joke_id|''})`, stamps `tip.stripe_checkout_session_id`. If Stripe raises after the Tip row is created, the pending Tip row is orphaned (no cleanup) — harmless for totals (only succeeded counted) but leaves noise in `/users/me/tips/`.
- Response: `{checkout_url, tip_id}` (note: subscription checkout returns `{url}` — different key). Stripe error -> 502.
- Cancelled/abandoned checkouts leave the Tip `pending` forever (no `checkout.session.expired` handler).

### 2.3 Webhook completion (`webhooks.py:94-142`)
- Reached only for `checkout.session.completed` with `metadata.type=='tip' and mode=='payment'`.
- Finds Tip by `metadata.tip_id` then by `stripe_checkout_session_id` (`select_for_update`); missing -> warning, no-op.
- Already `succeeded` -> no-op (inner idempotency in addition to event.id dedupe).
- `payment_status != 'paid'` -> leave pending (ACH etc.). No `checkout.session.async_payment_succeeded` handler exists, so a non-card settlement would never complete — mitigated by `payment_method_types=['card']` at session creation.
- Else: `status='succeeded'`, `stripe_payment_intent_id=session.payment_intent`, `completed_at=now()`.
- Refunds (`charge.refunded`) are NOT handled; `refunded` status is manual-only, and there is no Tip admin to set it.

### 2.4 Read endpoints
- `CreatorTipsSummaryView` (AllowAny): `{count, total_cents}` aggregated over `status='succeeded'` only; unknown creator id -> `{0, 0}` (never 404, no existence leak).
- `MyTipsView` (IsAuthenticated): sender's tips, DRF page-number pagination page_size=10, `TipSerializer` fields `id, creator, creator_name (public_display_name), joke, amount_cents, currency, status, created_at, completed_at`. Includes pending/failed rows.
- No creator-facing "tips received" list endpoint (only the public summary); no payout/withdrawal (Stripe Connect explicitly out of scope per spec — money lands in the platform account).

### 2.5 FE contract (`src/lib/api.ts:1159-1197`, `src/features/tips/*`)
`TIP_TIERS=[100,300,500,1000]`; `TipButton` hides when `isFollowing === null` (self/anon), redirects anon to `/login`, on 503 flips to disabled "coming soon", on success `window.location.href = checkout_url`.

---

## 3. Freemium paywall (`jokes/paywall.py`, `jokes/serializers.py:169-317`, `jokes/views.py`)

### 3.1 Rules (code)
- Cap key `free_joke_reads_per_day`, default 10 (`paywall.py:34-35`, `entitlements.KNOWN_LIMITS`). Paid plans seed `None` = unlimited. **Any new paid plan must set this key to null or it inherits 10** (memory; confirmed by `get_limit` semantics).
- Unit = DISTINCT `joke_id` in `JokeView` rows for `(user, viewed_date == timezone.now().date())` (`paywall.py:147-153`). `JokeView.viewed_date` is set in `save()` from `timezone.now().date()` (`jokes/models.py:1072-1076`); `TIME_ZONE='UTC'` so reset boundary = midnight UTC. `reset_at` = ISO of next midnight UTC (`paywall.py:62-65`), e.g. `2026-08-26T00:00:00+00:00`.
- `over = used >= limit`. Lock decision per joke: `is_locked = state.over and joke.id not in state.consumed_ids` (`serializers.py:254-264`). Already-read-today jokes stay unlocked.
- Server-side stripping in `JokeSerializer.to_representation` (`serializers.py:302-317`): when locked -> `punchline=None`, `lines=None`; for text-only formats (formats whose `FORMAT_RULES.required == ['text']`, i.e. oneliner/story/observ) also `text=None`; `setup` is always kept as the teaser. `get_media` returns dims-only (`{kind,width,height}`, no `url`/`poster_url`) when locked (`serializers.py:269-300`).
- `JokeListSerializer` (creator profile page) has no punchline field and is ALWAYS dims-only for media — cannot leak the payoff.

### 3.2 Who gets what
| Requester | Ledger | Cap | Notes |
| --- | --- | --- | --- |
| Anonymous | signed cookie `jf_anon_reads` (`paywall.py:40-113`): payload `{date, ids[]}`, salt `jokes.paywall.anon`, max_age 48h, `httponly`, `secure=not DEBUG`, `samesite=CSRF_COOKIE_SAMESITE or 'Lax'`; stale date -> empty ledger; tampered -> empty | hard-coded `FREE_READS_DEFAULT` (10), NOT plan-driven | "soft wall" by design — clearing cookies resets. Written by `JokeViewSet.retrieve` on unlocked delivery (`views.py:205-208`) and by `POST /jokes/{id}/reveal/` (`JokeRevealView`, `views.py:647-684`). Reveal for an authenticated user -> 204 no-op. Note the cookie's `samesite` follows `CSRF_COOKIE_SAMESITE` which is `None` in prod (cross-site SPA) -> browsers require `Secure`, satisfied when `DEBUG=False`. |
| Free authenticated | `JokeView` rows | `Plan.limits.free_joke_reads_per_day` (10) | consumption logged by `JokeViewSet.retrieve` ONLY when delivered unlocked (`views.py:175-204`, 60s debounce) and by telemetry `reveal` events (`views.py:3423-3440` create a `JokeView` if none exists). Feed/list responses do NOT consume; only detail opens/reveals do. |
| Paid (`active`/`trialing`) | not queried | None | `_unlimited_state()` -> `limit=None, remaining=None, over=False` |
| `past_due`/`canceled` | as free | 10 | because `effective_plan` falls back to free |

### 3.3 Serving paths that inject `paywall_state` (all use `JokeSerializer`)
`JokeViewSet` list/retrieve (`views.py:168-173`), `random` (`:383`), `trending` (`:579`), `CollectionViewSet.jokes` (`:990`), `SavedJokeViewSet` (`:1086`), `FavoriteViewSet` (`:1874`), `MysteryBoxRollView` (`:2842`), `RecentlyViewedView` (`:2882`), `JokePackViewSet` + `featured` (`:3018`, `:3034`).
**Exempt on purpose:** `DailyJokeViewSet.today` serializes `JokeSerializer(joke, context={'request': request})` with no `paywall_state` (`views.py` ~1195) -> never locked (test `DailyEditorialExemptTests`). `DailyJokeSerializer.joke` nested (history) likewise has no paywall context.
Public share page (`joke_share_page`) is server-rendered HTML outside DRF — out of scope here but note it is not paywalled (SEO by design per recent commits).

### 3.4 Status endpoint
`GET /api/v1/jokes/daily-reads/` (`views.py:400-413`, AllowAny) -> `{limit: int|null, used: int, remaining: int|null, over: bool, reset_at: ISO}`. Anonymous callers get the cookie-ledger view (limit 10).
`POST /api/v1/jokes/{id}/reveal/` (anon) -> same shape with counters updated; consumes one read if not over and not already consumed; 404 if joke not in allowed tiers / removed / blocked.

### 3.5 FE contract
`useDailyReads` treats `limit: number` as active cap; `null` or endpoint failure -> no cap. `FlowJokeCard` renders `is_locked === true` as blurred + "Unlock with Supporter" CTA -> `/settings/billing`. Client also soft-locks optimistically when `remaining <= 0`.

### 3.6 Tests (`jokes/test_paywall.py`, freezegun)
Under limit unlocked + distinct counting; over limit -> new joke locked, punchline null, setup kept, no JokeView written; already-consumed stays unlocked; text-only format blurs whole card; paid never locked & status reports unlimited; daily editorial exempt; day N over -> day N+1 `used=0`; status shape; history entitlement 30 vs 90 days. Anon cookie ledger tests live in `FlowJokeCard.anon.test.tsx` (FE) and presumably `jokes/tests_launch_blockers.py`/others (not enumerated here).

---

## 4. Creator insights & telemetry

### 4.1 Ingest: `POST /api/v1/telemetry/events` (`jokes/views.py:3287-3445`, `jokes/urls.py:66`)
- `IsAuthenticated` only (no consent check server-side; FE gates on auth + analytics consent + adult + real API). Anonymous -> 401.
- Body `{"events": [...]}`; non-list -> treated as empty; batch truncated to 50. Always `202 {"accepted": N}`; malformed events skipped silently; unknown joke ids skipped (`Joke.objects.filter(pk).exists()` per event = N queries, and default manager hides removed jokes).
- Event shapes the client must send:
  - `{"joke": id, "type": "impression", "source": str}` -> `JokeImpression.get_or_create(user, joke, created_date=today)` (one per user/joke/day; `source` truncated to 16 chars, default `'other'`). Counted as accepted even when deduped.
  - `{"joke": id, "type": "reveal", "source": str}` -> sets `revealed_punchline=True` on the user's most recent `JokeView` for that joke, or creates a `JokeView(revealed_punchline=True, source)` if none — **this also consumes a paywall read** for free users because it creates a JokeView.
  - `{"joke": id, "type": "dwell", "value": ms, "scroll_pct": 0-100?, "source": str}` -> `value` must be int (bool rejected), clamped to `[0, 600000]`, dropped if `< 500`; `scroll_pct` optional int clamped 0-100 else null; append-only `JokeDwell`.
  - `{"joke": id, "type": "watch", "watch_ms": ms, "watch_pct": 0-100?, "source": str}` -> same clamps into `JokeWatch` (append-only, `watched_at`).
- FE (`src/lib/telemetry.ts`): batches at 10, flushes on page-hide via `sendBeacon` (cookie-auth) or `fetch keepalive`; dwell min on client is 1000ms; sources `feed|explore|search|daily|pack|other`.

### 4.2 Insights: `GET /api/v1/creators/me/insights/?period=month|week|all` (`creator_insights/views.py:21-45`)
- Permissions: `IsAuthenticated`, `IsCreator` (has a `JokeSubmission(status='published')` — 403 message "You must have at least one published joke..."), `HasFeature('creator_analytics')`. Throttle scope `creator_insights` 120/hour.
- `period` default/unknown -> `month` (29-day window: today-29), `week` (today-6), `all` (None). Echoed as `period`.
- Jokes resolved owner-scoped (`resolve_creator_jokes`: `Joke.creator == user` OR legacy `creator null & submission.user == user & published`), bypassing content-tier lock (creator sees own tier_2).
- `overview` (`services.py:82-181` + followers at `:533-543`): `published_jokes`, `views` (JokeView count in window), `reach` (distinct viewers), `payoff_rate` = revealed views / views (null if 0 views), `impressions`, `unique_reach` (distinct impression users), `open_rate` = min(views/impressions, 1) (null if 0 impressions), `avg_read_seconds` (avg dwell_ms/1000, 2dp), `read_rate` = dwell rows >= 4000ms / dwell rows (4dp), `completion_rate` = dwell rows with scroll_pct >= 90 / rows with non-null scroll_pct, `reactions`, `favorites`, `saves`, `shares`, `peak_read_hour` (UTC hour with most views), `daily_reach_28d` (28 ints of daily view counts — despite the name it is views not distinct users), `followers`, `follower_growth_28d`.
- `reactions_breakdown [{reaction,count}]`, `shares_breakdown [{platform,count}]`, `source_mix [{source,count}]` (JokeView.source).
- `top_jokes` (top 10 by views, correlated subqueries to avoid fan-out): `{id, text, views, impressions, reactions, saves, shares, payoff_rate, avg_read_seconds, read_rate, avg_watch_seconds, watch_completion_rate}`; watch metrics only for jokes with video/audio media, threshold 90%.
- `audience {top_themes[8], top_categories[8], top_formats[5]}` as `{label,count}`.
- `suggestions` exactly three kinds in order: `peak_hour`, `what_resonates`, `consistency` (each `{kind,title,detail,data}`).
- Response is a plain dict; `CreatorInsightsSerializer` is schema-doc only.

### 4.3 Public profile: `GET /api/v1/creators/<id>/profile/` (AllowAny) -> 404 if no published jokes visible in the viewer's tiers or blocked pair; jokes paginated (10) with `JokeListSerializer` (no payoff). Tips summary is a separate call.

---

## 5. Live vs test vs dormant (precise)
- **Live in prod now:** plans catalog (placeholder data), entitlements/my-subscription (free for all), paywall (auth + anon), Mystery Box plan limits, daily-history window, telemetry ingest, creator insights, `creator_analytics` gate (no-op), tips read endpoints (return zeros), tips checkout endpoint (returns 503).
- **Dormant (code deployed, env unset):** subscription checkout/portal, webhook processing, tip checkout. Activation = set `STRIPE_SECRET_KEY` AND `STRIPE_WEBHOOK_SECRET` (+ success/cancel/portal URLs) on Cloud Run, then push prices to Stripe and edit placeholder plan names/amounts in admin. Memory notes Stripe live-mode onboarding is an owner action still parked.
- **Test-mode only:** all Stripe interaction in the test suite is mocked (`unittest.mock` patches of `billing.stripe_gateway.stripe`/`construct_event`); no recorded test-mode run against real Stripe in the repo. `STRIPE_GOLIVE.md` Step 5 describes the manual test-mode verification but there is no evidence it was executed.
- **Inert scaffolding:** `BILLING_ENABLED`, `UsageCounter`/`check_and_consume_quota`, `submissions_per_day`, `daily_jokes_per_day`, `daily_joke_preview`, `mature_content_addon`, dunning email, `EntitlementsSerializer`, Tip `failed`/`refunded` states.

---

## 6. iOS / Apple in-app-purchase considerations (flag only)
- The paywall unlocks **digital content consumed in-app** (punchline reveals, media URLs) via a Stripe subscription. In a native iOS app (or a WebView wrapper submitted to the App Store) Apple's guideline 3.1.1 generally requires such digital unlocks to use StoreKit IAP; linking out to Stripe Checkout from inside the app is restricted (region-dependent exceptions, e.g. US external-link entitlement post-2024, EU DMA terms). A pure PWA/Safari experience is unaffected. Decision needed: PWA-only vs native; if native, an IAP receipt-validation path that writes `Subscription` rows would be required — nothing in the backend supports that today (webhook only understands Stripe events; `Plan.stripe_price_id` is the only price linkage).
- **Tips** to creators are also digital "tipping" that Apple treats as IAP when initiated in-app (3.1.1 / 3.2.1(vii) allows 100% pass-through creator tips only via IAP). Stripe-hosted Checkout for tips inside a native app is the same concern.
- The "reader" mode exemption (3.1.3(a)) could let an iOS app show content purchased elsewhere without offering purchase in-app, but the FE currently embeds "Unlock with Supporter" CTAs linking to `/settings/billing`, which would need to be hidden in a native build.
- The `is_locked` server-side stripping model is IAP-agnostic and would work with any entitlement source; the missing piece is a non-Stripe path to set `Subscription.status='active'`.
- Not deciding here; flagging that both monetization rails (subscriptions + tips) are Stripe-web-only.

---

## 7. Risks / gaps found (code-verified)
1. `invoice.payment_failed` dunning email silently never sends (`payment_failed` template missing from `notifications/templates_registry.py`; exception swallowed at `webhooks.py:286-287`).
2. `STRIPE_WEBHOOK_SECRET` empty + `STRIPE_SECRET_KEY` set => webhook signatures verified against `''` (forgeable) — activation must set both.
3. Placeholder plans (`Supporter (PLACEHOLDER)` $5, `Creator Pro (PLACEHOLDER)` $15) are publicly served by `/billing/plans` and rendered by the FE BillingPage in prod; checkout for them 422s even with keys until prices are pushed.
4. `BILLING_SUCCESS_URL`/`BILLING_CANCEL_URL` default to localhost and the FE has no `/billing/success|cancel` routes; docs suggest routes that do not exist.
5. `BILLING_ENABLED` documented as a gate but unused.
6. Mystery Box views assume an int limit; `null` (unlimited) in plan JSON would 500.
7. Anonymous paywall cap is hard-coded to 10 (`FREE_READS_DEFAULT`), not read from the free plan — editing the plan's limit in admin changes authenticated users only; anon stays at 10.
8. `reveal` telemetry creates a `JokeView` (consumes a free read) even for a joke the client only "revealed" in-feed — consistent with product intent (reveal == consumption) but means feed reveals count without a detail open.
9. Tip rows orphaned as `pending` on abandoned/expired checkouts or Stripe errors; no `checkout.session.expired` / `charge.refunded` handlers; no Tip admin.
10. Webhook dedupe uses `exists()` then `create()` — concurrent duplicate deliveries can produce a 500 on the second (unique violation) rather than a clean 200; Stripe retry resolves it.
11. `past_due` immediately loses entitlement (paywall re-engages during Stripe Smart Retries) — product decision to confirm.
12. `date.today()` in `entitlements._period_key/_reset_at` vs `timezone.now()` elsewhere — same result under `TIME_ZONE='UTC'` but inconsistent with freezegun-driven tests that freeze `timezone`.
13. Tips "is creator" check (Joke.creator FK) differs from insights `IsCreator` (published JokeSubmission); legacy null-creator jokes make a user a creator for insights but not tippable.
14. `GET /billing/entitlements` lacks the `usage` map promised in the design doc §7.

---

## 8. Docs vs code disagreements
- Design doc: gated by `BILLING_ENABLED` -> code: only `STRIPE_SECRET_KEY` (STRIPE_GOLIVE.md agrees with code).
- Design doc §4.3: dunning email queued -> code: template missing, never sent.
- Design doc §7: entitlements endpoint includes `usage` -> code: no.
- Design doc §3: `creator_analytics` free default `False` -> code/seed: `True` (commit d4c3a99 "creator_analytics is free for all creators").
- Design doc §6 follow-on gates (submission quota, daily_jokes_per_day, daily_joke_preview) -> not implemented.
- Tips spec: "creator must ... be a real creator (has published jokes)" -> code checks `Joke.creator` FK existence (non-removed), not submissions.
- Tips spec: `GET /users/me/tips/` "sent tips history" -> matches; spec says checkout returns "session URL" -> code returns `{checkout_url, tip_id}`.
- STRIPE_GOLIVE.md webhook URL uses the old `jokesforbackend-q6w4ck2t2q-ue.a.run.app` host; task brief gives `jokesforbackend-332865216810.us-east1.run.app` — verify which hostname Stripe should target.
- Memory `project_paywall.md` says anon policy was TODO — code now implements the anon cookie ledger (commit 39cff08), so that note is stale.
