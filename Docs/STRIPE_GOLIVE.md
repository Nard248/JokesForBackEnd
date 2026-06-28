# Stripe Go-Live Runbook

Step-by-step guide to take JokesFor billing from dormant to live. This reflects
what the `billing/` code actually does — no invented behavior.

## How the integration behaves (summary)

- **Dormant by default.** Billing is gated on the `STRIPE_SECRET_KEY` env var
  (`billing.stripe_gateway.is_enabled()`). With it unset:
  - `POST /api/v1/billing/checkout-session` and `/portal-session` return **503**.
  - `POST /api/v1/billing/webhook` returns **200** (`{"detail": "billing_dormant"}`)
    so Stripe does not retry.
  - `GET /plans`, `/my-subscription`, `/entitlements` keep working off the
    seeded free plan.
- **Webhook is synchronous** (no workers/cron). It verifies the signature on the
  raw body, dedupes on `event.id` (`ProcessedStripeEvent`), updates the
  `Subscription` row, and returns. Safe for Stripe re-delivery.
- **Plans map to Stripe by `Plan.stripe_price_id`.** Webhooks resolve the plan
  from the price id on the subscription; unknown/blank price ids fall back to
  the default (free) plan.

---

## Step 1 — Create Stripe account, products, and prices

You have two options. **Option A (recommended)** lets the app create the
products/prices for you from the seeded Plans.

### Option A: Push-to-Stripe from Django admin (recommended)
1. Create a Stripe account and finish account activation.
2. Note this for later but do NOT skip Step 2 — the admin action needs
   `STRIPE_SECRET_KEY` set on the running server before it works.
3. Continue to Step 2, then Step 3.

### Option B: Create products/prices manually in the Stripe dashboard
1. Stripe Dashboard → **Products** → add a product per paid tier (e.g.
   "Supporter", "Creator Pro").
2. For each product add a **recurring** price (monthly, USD to match the seeded
   plans). Copy each `price_...` id.
3. You'll paste these into the matching Plan in Step 3.

The repo seeds three plans (migration `billing/0002_seed_plans.py`):
`free` (default, no price), `supporter` ($5/mo PLACEHOLDER), `creator_pro`
($15/mo PLACEHOLDER). **The amounts are placeholders — edit them in admin to
your real prices before going live.**

---

## Step 2 — Set environment variables on Cloud Run

Set these on the Cloud Run service (exact names, read in `JokesForProject/settings.py`):

| Env var | Required | Value |
| --- | --- | --- |
| `STRIPE_SECRET_KEY` | Yes | `sk_test_...` (test) → `sk_live_...` (live). Setting this is what un-dorms billing. |
| `STRIPE_WEBHOOK_SECRET` | Yes | `whsec_...` from the webhook endpoint you create in Step 4. |
| `STRIPE_PUBLISHABLE_KEY` | Optional | `pk_test_...`/`pk_live_...` (only if the frontend needs it). |
| `STRIPE_API_VERSION` | Optional | Defaults to `2026-05-27.dahlia`. Leave unless Stripe tells you otherwise. |
| `BILLING_SUCCESS_URL` | Yes | Where Checkout returns on success, e.g. `https://<frontend>/billing/success`. |
| `BILLING_CANCEL_URL` | Yes | Checkout cancel URL, e.g. `https://<frontend>/billing/cancel`. |
| `BILLING_PORTAL_RETURN_URL` | Yes | Customer-portal return URL, e.g. `https://<frontend>/account`. |

Notes:
- `BILLING_ENABLED` exists in settings but is not used for gating; gating is
  purely on `STRIPE_SECRET_KEY`. You don't need to set it.
- After changing env vars, deploy/redeploy the revision so they take effect.

---

## Step 3 — Map Stripe price IDs to Plans

Each paid `Plan` must have a non-blank `stripe_price_id`, or checkout returns
**422** ("This plan is not yet available for purchase").

First, in Django admin (`/admin/billing/plan/`), set each plan's real
`amount_cents`, `currency`, `interval`, and review `features`/`limits`.

Then choose:

**Option A — Push to Stripe (admin action):**
1. Admin → Billing → Plans → select the paid plans.
2. Action dropdown → **"Push to Stripe (idempotent — creates/updates Product+Price)"** → Go.
3. The action creates a Stripe Product + Price and writes back
   `stripe_product_id` and `stripe_price_id` on each plan. It's idempotent: if
   `amount_cents` changed it creates a new price and archives the old one. Free
   plans (no `amount_cents`) are skipped.

**Option B — Paste manually:**
1. For each paid plan, paste the `price_...` id you created in Stripe into the
   plan's **`stripe_price_id`** field (and optionally `stripe_product_id`).

Either way, leave the `free` plan's price fields blank.

---

## Step 4 — Configure the webhook endpoint in Stripe

1. Stripe Dashboard → **Developers → Webhooks → Add endpoint**.
2. Endpoint URL (no trailing slash):
   `https://jokesforbackend-q6w4ck2t2q-ue.a.run.app/api/v1/billing/webhook`
3. Subscribe to exactly these events (the only ones the handler acts on):
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.paid`
   - `invoice.payment_failed`
4. After creating the endpoint, copy its **Signing secret** (`whsec_...`) into
   the `STRIPE_WEBHOOK_SECRET` env var (Step 2) and redeploy.

---

## Step 5 — Verify in test mode

Use Stripe **test** keys for all of this.

1. **Dormant check (optional):** with `STRIPE_SECRET_KEY` unset, confirm
   checkout returns 503 and the webhook returns 200 `billing_dormant`.
2. Set test keys + test webhook secret; redeploy.
3. `GET /api/v1/billing/plans` returns your plans with prices.
4. From the frontend (logged in), start checkout: `POST /api/v1/billing/checkout-session`
   with `{"plan_slug": "supporter"}` → returns `{"url": ...}`. Complete payment
   with a Stripe test card (e.g. `4242 4242 4242 4242`).
5. Confirm the webhook delivered (Stripe dashboard → webhook → recent
   deliveries show 200) and that:
   - `GET /api/v1/billing/my-subscription` shows status `active` and the right plan.
   - `GET /api/v1/billing/entitlements` reflects the paid plan's features/limits.
   - The user's `UserProfile.is_premium` flips true (denormalized cache).
6. **Customer portal:** `POST /api/v1/billing/portal-session` → returns a `url`.
   In the portal, cancel the subscription; confirm a
   `customer.subscription.deleted` (or `.updated`) webhook downgrades the user
   back to the free plan and `is_premium` flips false.
7. **Dunning:** trigger a failed payment (Stripe test tools) and confirm the
   subscription goes `past_due` on `invoice.payment_failed`, then back to
   `active` on a subsequent `invoice.paid`.
8. **Idempotency (optional):** in the Stripe dashboard, "Resend" a delivered
   event and confirm no duplicate subscription changes (deduped on `event.id`).

---

## Step 6 — Switch test → live

1. In Stripe, toggle to **live mode** and create a **live** webhook endpoint
   (same URL, same event list as Step 4). Copy its live signing secret.
2. If you used Push-to-Stripe in test mode, the stored `stripe_price_id`s are
   **test-mode ids**. In live mode you must re-create live prices:
   - Re-run the Push-to-Stripe admin action with live keys set (it will create
     live products/prices and overwrite the ids), **or**
   - Paste live `price_...` ids into each plan manually.
3. Update Cloud Run env vars to the live values and redeploy:
   - `STRIPE_SECRET_KEY=sk_live_...`
   - `STRIPE_WEBHOOK_SECRET=whsec_...` (the live endpoint's secret)
   - `STRIPE_PUBLISHABLE_KEY=pk_live_...` (if used)
4. Run one real end-to-end purchase to confirm, then refund it in the dashboard.

---

## Rollback

To disable billing instantly without a code change: unset `STRIPE_SECRET_KEY`
on Cloud Run and redeploy. Checkout/portal return 503, the webhook returns 200
noop, and the rest of the app continues on the free plan.
