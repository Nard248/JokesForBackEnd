# Creator subscription launch runbook

Updated 2026-09-27. Viewers read for free. Creator Pro is a $15/month pilot
hypothesis; Supporter is retired from new sales. Keep legacy subscriptions and
customer-portal cancellation access intact. Do not activate tips without a payout
rail. No live configuration or Stripe resources were changed by this checkpoint.

## Gates and runtime behavior

| Setting | Purpose |
| --- | --- |
| `STRIPE_SECRET_KEY` | Enables the Stripe transport, portal and webhook reconciliation. Store in Secret Manager; never commit or print it. |
| `STRIPE_WEBHOOK_SECRET` | Required for authenticated webhook processing. A key without this secret returns 503. |
| `CREATOR_CHECKOUT_ENABLED=false` | Default-off switch for new creator subscription sales. Turn on only after the checks below. |
| `TIPS_ENABLED=false` | Independent switch. Leave off: there is no creator payout rail. |
| `BILLING_ENABLED` | Legacy setting; does not control billing. |
| `STRIPE_API_VERSION` | Explicit version, currently `2026-05-27.dahlia`; verify the actual account/webhook version during testing. |
| `BILLING_SUCCESS_URL`, `BILLING_CANCEL_URL`, `BILLING_PORTAL_RETURN_URL` | Trusted application destinations; require HTTPS for live use. |

With creator checkout off, new subscription requests return 503
`creator_checkout_unavailable`. Existing portal and webhook processing still
work. With no Stripe key at all, checkout/portal return 503 and webhook returns
200 `billing_dormant`; **do not remove the key as a sales rollback while paying
subscribers exist**, because it discards subsequent payment events.

Checkout uses a per-user database lock and a persisted `SubscriptionCheckout`
request identity. A repeated request reuses the open session. It stores the exact
parameters and retries uncertain creates with the same Stripe idempotency key.
Open checkouts cannot be silently switched to another price. Only Stripe-confirmed
expired sessions or completed subscriptions now canceled/expired allow a new
attempt. Unresolved creates older than 23 hours fail closed for operator review,
before Stripe's idempotency retention can expire. Existing `active`, `trialing`,
`past_due`, `incomplete`, `unpaid`, and `paused` subscriptions block a second sale;
a bounded Stripe subscription-list read also catches delayed webhooks.

## Merchant and catalog checks

1. Confirm the intended US business account with the owner and complete onboarding.
   The test-key account read during this session reported US, with
   `details_submitted=false`, `charges_enabled=false`, `payouts_enabled=false`.
   That is evidence of an activation blocker, not proof of live account readiness.
2. Set test keys and a test webhook signing secret in a nonproduction environment.
   Verify the business name, support contact, statement descriptor, tax treatment,
   terms and refund/cancellation policy. Account country alone does not establish
   legal, tax or App Store readiness.
3. Apply migrations through `billing/0009_creator_catalog_labels.py`. Migration 0006
   preserves catalog prices and known non-default live subscription prices.
   Conflicting historical price ownership must be reconciled before continuing.
4. Configure only the creator offer for new sales. `Plan` controls amount,
   currency, interval, entitlements and limits. The admin **Push to Stripe** action
   performs writes and therefore needs deliberate operator execution; the readiness
   command below never creates or changes a product or price. Price replacement
   preserves `PlanPrice` history so existing subscribers retain their mapping.
5. Confirm the price is active and recurring and matches the plan's product,
   amount, currency and interval. The existing admin price/product fields are
   read-only; do not rely on a manual-paste UI that does not exist.

Read-only readiness command (default requires a **test** key/catalog):

```sh
DATABASE_URL='' DB_HOST=localhost DB_NAME=jokesfor_payments DEBUG=True \
  DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
  .venv/bin/python manage.py check_sales_readiness --expected-country US
```

Use the intentionally configured environment; local `.env` may otherwise target
production. This command makes read-only Stripe calls using the selected key. It
prints pass/fail booleans and numbered catalog entries, never account/resource IDs,
secrets or exception payloads. `--live` requires a live key/catalog and HTTPS
redirects; it does not activate sales. A successful result still requires the
end-to-end exercise below and owner confirmation of the intended account.

## Signed webhook and payment exercise

Register `/api/v1/billing/webhook` on the intended backend and subscribe to:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`

Use the matching endpoint's signing secret. Snapshot events authenticate the
notification; the handler retrieves the referenced subscription's **current**
state under the account lock. Invoice events must identify a subscription (legacy
`subscription` or newer `parent.subscription_details.subscription`); unrelated
invoices cannot change access. Customer identity and subscription metadata must
agree with local ownership. Older subscriptions cannot overwrite newer live ones.
Unknown prices resolve to free entitlements. Checkout completion alone never
sets `active`. Duplicate events claim a unique database row before side effects;
errors roll back the claim and return 500 for Stripe retry.

The Stripe transport uses a five-second request timeout and zero automatic network
retries. Reconciliation is synchronous, so an outage delays access until successful
redelivery. There is no worker. Monitor repeated failures and ownership conflicts.

In the isolated test environment, explicitly set `CREATOR_CHECKOUT_ENABLED=true`
and exercise all of the following with test cards and signed events:

1. Start Creator Pro checkout; complete it and confirm current subscription state,
   correct price mapping and creator-tool access. Reading remains free throughout.
2. Repeat checkout from two tabs and retry a lost response. Confirm one Stripe
   customer/session/subscription, not parallel bills.
3. Simulate failed initial payment and renewal failure. Incomplete/past-due access
   must remain unavailable; recovery follows current Stripe subscription state.
4. Cancel in the portal, then resubscribe. Replay the old checkout, cancellation
   and invoices; they must not replace the new subscription.
5. Resend an event concurrently and confirm one processed-event row. Temporarily
   fail the Stripe read, restore it and confirm redelivery reconciles successfully.
6. Replace a price, then deliver a renewal for the old price. Its plan mapping
   must remain intact. Verify inactive/unknown prices cannot grant arbitrary tools.
7. Turn the sales gate off: checkout returns 503, signed webhooks still reconcile,
   portal cancellation remains available, and tips remain unavailable.

Automated local regression tests cover these boundaries with actual `StripeObject`
shapes and mocked network responses, including two real PostgreSQL connections for
concurrency. They are **not** evidence that the intended Stripe account, webhook
registration, catalog, or real payment flow has passed this exercise.

## Live activation and rollback

Require owner confirmation of the intended US account, enabled charges/payouts,
verified live catalog and portal configuration, successful signed test-mode
exercise, and customer-facing legal/tax setup. Native distribution needs its own
App Store review; web creator SaaS does not prove an in-app-purchase exemption.

Use separate test/live environments and catalogs. Test product IDs cannot simply
be retrieved using live keys, so rerunning the admin action against stale test IDs
is not a valid migration procedure. Provision and verify a clean live catalog
without overwriting legacy subscription mappings. Use live signing secrets and
verify the live endpoint before enabling `CREATOR_CHECKOUT_ENABLED`.

Rollback new sales by setting `CREATOR_CHECKOUT_ENABLED=false`; leave the Stripe
key and webhook secret available. If a checkout attempt has no known session and
has exceeded 23 hours, inspect Stripe before changing/deleting its local record.
Expire any still-open session and reconcile all subscriptions first. Never delete
the attempt merely to make an uncertain create retry succeed.

References: [Stripe webhook ordering and retries](https://docs.stripe.com/webhooks),
[Checkout session expiration](https://docs.stripe.com/api/checkout/sessions/expire),
[Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests).
