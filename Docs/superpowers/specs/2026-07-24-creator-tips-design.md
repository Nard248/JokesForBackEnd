# Creator Tips — Design — 2026-07-24

Feature 4 (last) of the MVP slate. Owner-approved feature; built on the
existing env-gated Stripe rails so it's DORMANT until Stripe live-mode is
onboarded (owner action, parked) — ships code-complete and test-verified,
activates with the same key that activates subscriptions.

## Goal

Readers send a one-off tip to a creator whose joke they loved. Real revenue
depth on the rails already built for subscriptions.

## Model

`Tip` (billing app): `sender FK · creator FK · joke FK null · amount_cents ·
currency · status ∈ {pending, succeeded, failed, refunded} ·
stripe_payment_intent_id · stripe_checkout_session_id · created_at ·
completed_at`. Creator earnings are derived (sum of succeeded tips); no
payout ledger in v1 (payouts are a Stripe Connect concern, out of scope —
see below).

## Flow (mirrors CheckoutSessionView)

- `POST /api/v1/tips/checkout/` `{creator_id, joke_id?, amount_cents}` —
  IsAuthenticated; amount within an allowlist (fixed tiers: 100/300/500/1000
  cents — no arbitrary amounts, abuse/laundering guard); creator must exist,
  be a real creator (has published jokes), and NOT be the sender (no
  self-tipping). Creates a Stripe Checkout Session in `payment` mode (not
  subscription) with the tip metadata; returns the session URL. Dormant →
  503 billing_unavailable (same as subscriptions).
- Webhook: extend the existing `StripeWebhookView` handler —
  `checkout.session.completed` with a tip metadata marker → mark the Tip
  succeeded, stamp payment_intent + completed_at. Idempotent on session id
  (the handler already dedupes events; mirror it).
- `GET /api/v1/creators/{id}/tips/summary/` (public: total tips count +
  amount for a creator, for the profile) and `GET /api/v1/users/me/tips/`
  (sent tips history).

## Payout reality (scoped honestly)

- v1 collects tips into the PLATFORM Stripe account. Actually paying
  creators requires **Stripe Connect** (onboarding, KYC, transfers) — a
  large separate integration, explicitly OUT OF SCOPE. v1 records what's
  owed (succeeded tips per creator) so the platform can settle manually /
  build Connect later. The creator-facing UI says "tips received" (earned),
  not "available to withdraw" — no withdrawal affordance that can't be
  honored. Documented so we never imply instant payout we can't deliver.

## Frontend

- A "Tip creator" button on the creator profile + optionally on a joke
  detail (tip the creator for THIS joke → joke_id set). Tier picker modal
  → checkout redirect (reuse the subscription checkout redirect pattern).
- Creator profile shows tips-received summary (count + total) from the
  public summary endpoint; hidden when zero.
- Success/cancel return handling mirrors subscription checkout return.
- ALL of it dormant-aware: if billing is unavailable (503), the tip button
  is hidden/disabled with "coming soon" — never a broken checkout.

## Security

- Fixed-tier amounts only (server-validates against the allowlist — client
  can't send arbitrary cents). No self-tipping. Webhook signature
  verification (existing). Tip metadata on the session is
  server-constructed, never trusted from the client beyond creator_id/
  joke_id/tier. No PII in metadata beyond ids.

## Out of scope (v1)

Stripe Connect / real payouts; recurring/subscription tips; tip messages/
comments; refund UI (admin-only via Stripe dashboard); tip leaderboards;
arbitrary amounts.

## Activation

Fully dormant behind `STRIPE_SECRET_KEY` like subscriptions. When the owner
completes live-mode onboarding and sets the live key, tips activate with
zero code change — same switch as subscriptions. Tests run against the
Stripe test-mode/mocked gateway.
